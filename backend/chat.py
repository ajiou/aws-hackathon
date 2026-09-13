"""稽查 AI 助手：園況事實 + 法規檢索 + Claude 白話回答。ADR-0005。

三條不可違反的規則：

1. **LLM 不碰分數**（SPEC §8.8）。分級、名次、裁罰紀錄一律從 ServingStore 取出、
   原樣放進 prompt，要求模型照抄；回傳給前端的 `park` 也直接取自 store。
2. **Bedrock ≤ 每秒 1 次**（競賽規範）。一題恰好兩個 Bedrock 請求（Retrieve、
   messages.create），全部經過 `BedrockPacer`；回應前補足間隔，搭配 Lambda
   reserved concurrency = 1，跨容器也不會有兩個請求落在同一秒。SDK 自動重試
   一律關掉——重試會打破間隔。
3. **不把個人資料送進 AWS**（競賽規範第 2 條）。訊息看起來含自然人姓名就直接擋下，
   不送 Bedrock、不寫 log。這是樣式比對，不是姓名辨識器；前端另有提示。
"""

import json
import logging
import re
import threading
import time
from collections import Counter

from backend.privacy import PERSON_LABEL
from backend.schemas import ChatPark, ChatRequest, ChatResponse, Citation, Park
from backend.services import brief_for
from backend.store import ServingStore

# 稱謂前面接姓氏＋0–2 字，例如「王小明老師」「陳園長」。
# 刻意不收「任、方、石、史、連」這類同時是常用字的姓：「專任教保員」「現任園長」
# 「兼任主任」是稽查員最自然的問法，誤擋的代價高於漏擋。前面接職稱修飾字時也不算。
SURNAMES = (
    "王李張劉陳楊黃趙吳周徐孫馬朱胡郭何高林羅鄭梁謝宋唐許韓馮鄧曹彭曾蕭田董袁潘蔣蔡余杜葉程"
    "蘇魏呂丁沈姚盧姜崔鍾譚陸汪范金廖賈夏韋白鄒孟熊秦邱江尹薛閻段雷侯龍黎賀顧毛郝龔"
    "邵萬錢嚴武戴莫孔向湯詹洪游柯賴翁巫涂簡鄞施紀溫"
)
TITLED_NAME = re.compile(
    rf"(?<![專現兼離到新前副主歷升後代])[{SURNAMES}][一-鿿]{{0,2}}"
    r"(?:老師|園長|負責人|主任|教保員|先生|小姐|女士)"
)

# 裁罰類別 → 檢索時補上的關鍵字（類別名稱本身對法規原文不夠貼近）。
CATEGORY_QUERY = {
    "師生比": "班級人數 師生比 教保服務人員配置",
    "超收": "招收人數限制 超收 擴充",
    "交通車": "幼童專用車 隨車人員 駕駛人",
    "不當管教": "不當對待 不當管教 體罰",
    "食安衛生": "衛生保健 餐點 教保服務禁止規定",
    "設施安全": "安全管理規範 保護措施 設施設備",
    "師資": "未具教保服務人員資格 進用 不適任",
    "收費爭議": "收費數額 退費",
    "其他行政": "課後照顧 公開資訊 團體保險",
}

SYSTEM = """你是新北市教育局稽查人員的助理。回答要讓稽查人員出發前三十秒內看完就知道要查什麼，全文 350 字以內。

規則：
- 園所的風險分級、名次、裁罰次數與類別、評鑑結果，只能照抄 <園況資料> 裡的數字與文字。不要加總罰鍰、不要推算期間或頻率、不要寫資料裡沒有的數字。
- 法規依據只能引用 <法規條文> 裡出現的條文，格式固定為《法規名稱》條號，例如《幼兒教育及照顧法》第16條，不要寫到「項」「款」。<法規條文> 查不到依據的重點，寫「法規庫查無直接依據」，不要憑記憶補。
- 裁罰紀錄的條號沒有標明是哪一部法規，且 2023 年修法前後條號不同；請以裁罰「類別」對應 <法規條文> 裡的現行條文，不要把紀錄上的條號直接當成現行條號。
- 這是稽查排序參考，不是違規認定。不要寫「該園違法」「應予處分」這類結論。
- 不要寫出任何自然人姓名。
- 若 <法規條文> 寫著「法規庫尚未啟用」，建議稽查重點只依裁罰類別、評鑑與原因提出，不要引用任何法規名稱或條號，最後一行寫「法規依據待法規庫啟用後補上」。
- 格式用純文字：第一行一句話總結；接著一行「風險現況」，下面 2–4 個「- 」開頭的條列；再一行「建議稽查重點」，下面至多 4 個「- 」開頭的條列，每條結尾附法規依據。不要用 #、**、--- 等 Markdown 符號。
- 沒有指定園所時會附 <全市資料>（系統依問題篩選好的風險名單與行政區統計）。問「該查哪幾間」「哪一區風險高」這類問題，只能從名單裡挑，照抄園名、行政區、全市名次、分級、裁罰次數與原因，並說明名單的篩選條件；不要提名單以外的園所，也不要寫「全市最多」「最嚴重」這類超出名單範圍的比較。這時格式改為：第一行一句話總結；一行「建議優先稽查」，下面至多 5 個「- 園名（行政區，全市第N名）：理由」；需要時再一行「稽查時留意」附法規依據。
- 純法規問題就只回答法規，同樣 350 字以內，不要編造園況。"""


class BedrockPacer:
    """相鄰兩個 Bedrock 請求至少間隔 interval 秒（程序內，搭配 reserved concurrency = 1）。"""

    def __init__(self, interval: float = 1.1, clock=time.monotonic, sleep=time.sleep):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.last = float("-inf")
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.last + self.interval - self.clock()
            if delay > 0:
                self.sleep(delay)
            self.last = self.clock()

    def settle(self):
        """回應前補足間隔，讓下一題（可能在另一個容器）不會緊貼著這一題。"""
        with self.lock:
            delay = self.last + self.interval - self.clock()
            if delay > 0:
                self.sleep(delay)


class AssistantUnavailable(Exception):
    """Bedrock 被限流或失敗；呼叫端改回模板版。"""


def has_person_name(message: str) -> bool:
    return bool(PERSON_LABEL.search(message) or TITLED_NAME.search(message))


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", "", text).replace("幼稚園", "幼兒園")
    for word in ("新北市立", "新北市", "私立", "市立", "附設", "附屬"):
        text = text.replace(word, "")
    return text.casefold()


def _core(name: str) -> str:
    return re.sub(r"(幼兒園|教保服務中心)$", "", _normalize(name))


def find_parks(store: ServingStore, message: str) -> list[Park]:
    """園名比對。同時命中多家時只留最長的名稱（「大同國小附幼」勝過「大同」）。

    先把行政區名從訊息拿掉：「板橋區要查哪間」不能被當成「私立板橋幼兒園」。
    """
    text = _normalize(message)
    for town in towns(store):
        text = text.replace(town, "")
    hits = [p for p in store.parks().values() if len(_core(p.name)) >= 2 and _core(p.name) in text]
    if not hits:
        return []
    longest = max(len(_core(p.name)) for p in hits)
    hits = [p for p in hits if len(_core(p.name)) == longest]
    return sorted(hits, key=lambda p: (p.risk.rank is None, p.risk.rank or 0, p.name))


def towns(store: ServingStore) -> list[str]:
    return sorted({p.town for p in store.parks().values() if p.town}, key=len, reverse=True)


# 問題裡的字 → 裁罰類別。用來回答「超收最嚴重的是哪幾間」這類問題。
CATEGORY_WORDS = {
    "超收": ("超收", "招收人數", "擴充"),
    "師生比": ("師生比", "班級人數", "編班"),
    "交通車": ("交通車", "幼童專用車", "娃娃車", "隨車"),
    "不當管教": ("不當管教", "不當對待", "體罰", "虐待"),
    "食安衛生": ("食安", "衛生", "餐點", "食物"),
    "設施安全": ("設施", "安全"),
    "師資": ("師資", "資格", "不適任"),
    "收費爭議": ("收費", "退費"),
}
CITY_LIST_SIZE = 10


def city_facts(store: ServingStore, message: str) -> tuple[dict, list[Park]]:
    """沒有指定園所時給模型的全市資料：依問題裡的行政區、設立別、裁罰類別篩選風險名單。

    篩選與排序全部在這裡做完，模型只負責挑選與說明——名次、分級一律照 serving 資料。
    """
    text = message.replace("私幼", "私立")
    town_hits = [t for t in towns(store) if t in text or (len(t) > 2 and t.rstrip("區") in text)]
    type_hits = [k for k in ("公立", "私立", "非營利") if k in text]
    category = next((c for c, words in CATEGORY_WORDS.items() if any(w in text for w in words)), None)

    rows = [p for p in store.ranked()
            if (not town_hits or p.town in town_hits)
            and (not type_hits or p.institution_type in type_hits)]
    if category:
        count = lambda p: sum(1 for x in p.timeline if x.category == category)
        rows = sorted((p for p in rows if count(p)), key=lambda p: (-count(p), p.risk.rank))
    top = rows[:CITY_LIST_SIZE]

    ranked = store.ranked()
    facts = {
        "篩選條件": {
            "行政區": town_hits or "全市",
            "設立別": type_hits or "全部",
            "裁罰類別": f"{category}（依該類裁罰次數排序）" if category else "無（依全市風險名次排序）",
        },
        "符合條件的營運中園所數": len(rows),
        "名單": [
            {
                "園名": p.name, "行政區": p.town, "設立別": p.institution_type,
                "全市名次": p.risk.rank, "分級": p.risk.tier,
                "裁罰次數": len(p.timeline),
                "主要裁罰類別": dict(Counter(x.category for x in p.timeline).most_common(3)),
                "原因": [r.label for r in p.reasons],
            }
            for p in top
        ],
        "全市": {
            "營運中園數": len(ranked),
            "高風險園數": sum(1 for p in ranked if p.risk.tier == "高"),
        },
    }
    districts = store.load("districts", optional=True)
    if districts and any(w in text for w in ("區", "行政區", "哪一區", "哪區")):
        items = sorted(districts.get("items", []), key=lambda d: -d.get("high_risk_count", 0))
        facts["行政區統計（依高風險園數排序，前 8）"] = [
            {k: d.get(k) for k in ("town", "park_count", "high_risk_count", "high_risk_ratio")}
            for d in items[:8]
        ]
    return facts, top


def park_card(park: Park) -> ChatPark:
    return ChatPark(
        park_id=park.park_id, name=park.name, town=park.town,
        institution_type=park.institution_type, is_active=park.is_active,
        tier=park.risk.tier, rank=park.risk.rank,
    )


def park_facts(store: ServingStore, park: Park) -> dict:
    """送進 prompt 的園況。刻意不含 owner_key、地址、電話。"""
    timeline = sorted(park.timeline, key=lambda p: p.date, reverse=True)
    evaluations = sorted(store.related("evaluations", park.park_id),
                         key=lambda e: str(e.get("評鑑完成日") or ""), reverse=True)
    return {
        "園名": park.name,
        "行政區": park.town,
        "設立別": park.institution_type,
        "營運中": bool(park.is_active),
        "資料基準日": park.as_of_date,
        "風險": {
            "分級": park.risk.tier,
            "全市名次": park.risk.rank,
            "加權總分": park.risk.score,
            "同類名次": f"{park.risk.peer_rank}/{park.risk.peer_n}" if park.risk.peer_rank else None,
        },
        "原因": [r.label for r in park.reasons],
        "裁罰次數": len(timeline),
        "裁罰類別統計": dict(Counter(p.category for p in timeline).most_common()),
        "最近裁罰": [
            {"日期": p.date, "類別": p.category, "條號": p.law, "處分": p.penalty_raw}
            for p in timeline[:8]
        ],
        "評鑑": [
            {k: e.get(k) for k in ("評鑑學年度", "評鑑完成日", "類型", "評鑑結果")}
            for e in evaluations[:4]
        ],
        "財務旗標（未經裁罰驗證）": [f.label for f in park.finance_flags],
        "核定人數": park.count_approved,
    }


def retrieval_query(message: str, park: Park | None) -> str:
    if park is None:
        return message
    categories = [c for c, _ in Counter(p.category for p in park.timeline).most_common(3)]
    extra = " ".join(CATEGORY_QUERY.get(c, c) for c in categories)
    return f"{message} {extra}".strip()


REF = re.compile(r"《([^》]+)》\s*(第[\d-]+條|附表[一二]第[一二三四五六七八九十]+項|[一二三四五六七八九十]+、)?")


def unverified_refs(answer: str, citations: list[Citation]) -> list[str]:
    """回答裡引用、但檢索結果中沒有的法規或條號。前端據此加警示。"""
    known = {(c.law, c.article) for c in citations}
    laws = {c.law for c in citations}
    out = []
    for law, article in REF.findall(answer):
        if law not in laws or (article and (law, article) not in known):
            ref = f"《{law}》{article}"
            if ref not in out:
                out.append(ref)
    return out


class BedrockClients:
    """正式環境的 Retrieve 與 Claude 呼叫。測試以假物件取代。

    `kb_id` 可以是 None：法規知識庫還沒建好時，助手照樣能用園況回答，只是不附法規。
    """

    def __init__(self, kb_id: str | None, model: str, region: str):
        import anthropic
        import boto3
        from botocore.config import Config

        self.kb_id = kb_id
        self.has_laws = bool(kb_id)
        self.model = model
        self.agent = boto3.client(
            "bedrock-agent-runtime", region_name=region,
            config=Config(retries={"max_attempts": 1}, connect_timeout=2, read_timeout=4),
        )
        # 逾時預算：檢索 6 + 間隔 1.1 + 生成 20 ≈ 27 秒 < Lambda 29 秒。生成成功時已過了
        # 間隔，settle 不再等待。超過 29 秒 Lambda 會被直接砍掉，連模板退路都跑不到。
        # 2026-09-13 實測 Opus 4.6：輸入 4k tokens、輸出 758 tokens 要 14.2 秒，所以
        # 同時用 prompt 限 350 字、max_tokens 1200 把輸出壓短。
        self.claude = anthropic.AnthropicBedrock(aws_region=region, max_retries=0, timeout=20)
        self._anthropic = anthropic

    def retrieve(self, query: str, k: int = 6) -> list[dict]:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            results = self.agent.retrieve(
                knowledgeBaseId=self.kb_id, retrievalQuery={"text": query[:1000]},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}},
            )["retrievalResults"]
        except (ClientError, BotoCoreError) as exc:
            raise AssistantUnavailable from exc
        return [
            {"text": r["content"]["text"], "score": r.get("score"), **r.get("metadata", {})}
            for r in results
        ]

    def answer(self, system: str, user: str) -> str:
        try:
            response = self.claude.messages.create(
                model=self.model, max_tokens=1200, system=system,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIError as exc:
            raise AssistantUnavailable from exc
        if response.stop_reason == "refusal":
            raise AssistantUnavailable
        return "".join(b.text for b in response.content if b.type == "text").strip()


class ChatService:
    def __init__(self, store: ServingStore, clients, pacer: BedrockPacer | None = None):
        self.store = store
        self.clients = clients
        self.pacer = pacer or BedrockPacer()

    def reply(self, request: ChatRequest) -> ChatResponse:
        if has_person_name(request.message):
            return ChatResponse(
                source="blocked",
                answer="訊息疑似包含人名。為避免個人資料送出，請改用園所名稱提問，例如「某某幼兒園最近狀況」。",
            )

        park, candidates, listed = None, [], []
        if request.park_id:
            park = self.store.parks().get(request.park_id)
        else:
            found = find_parks(self.store, request.message)
            if len(found) == 1:
                park = found[0]
            elif found:
                candidates = [park_card(p) for p in found[:5]]
                return ChatResponse(
                    source="candidates", candidates=candidates,
                    answer=f"找到 {len(found)} 家名稱相符的園所，請點選要查詢的那一家。",
                )

        laws_enabled = getattr(self.clients, "has_laws", True)
        try:
            docs = []
            if laws_enabled:
                self.pacer.wait()
                docs = self.clients.retrieve(retrieval_query(request.message, park))
            citations = [
                Citation(law=d.get("law_name", ""), article=d.get("article", ""),
                         snippet=d["text"][:600], url=d.get("source_url") or None)
                for d in docs if d.get("law_name")
            ]
            laws = ("\n\n".join(d["text"] for d in docs) or "（沒有檢索到條文）") if laws_enabled \
                else "（法規庫尚未啟用：本次不引用任何法條）"
            if park:
                context = ("園況資料", park_facts(self.store, park))
            else:
                city, listed = city_facts(self.store, request.message)
                context = ("全市資料", city)
            tag, data = context
            facts = json.dumps(data, ensure_ascii=False, indent=1)
            user = (f"<{tag}>\n{facts}\n</{tag}>\n\n<法規條文>\n{laws}\n</法規條文>\n\n"
                    f"<稽查人員問題>\n{request.message}\n</稽查人員問題>")
            self.pacer.wait()
            answer = self.clients.answer(SYSTEM, user)
        except AssistantUnavailable as exc:
            # 只記錯誤型別，不記訊息內容（可能帶到使用者輸入）。
            logging.getLogger("watchdog.api").warning(json.dumps(
                {"chat_fallback": type(exc.__cause__).__name__ if exc.__cause__ else "refusal"}))
            return self.fallback(park)
        finally:
            self.pacer.settle()

        return ChatResponse(
            source="llm", answer=answer, park=park_card(park) if park else None,
            citations=citations, unverified_refs=unverified_refs(answer, citations),
            laws_enabled=laws_enabled,
            # 回答裡提到的園所可能在名單中，前端列成可點的連結；只列模型真的有提到的。
            # 模型常省略「新北市私立」，比對去掉前綴後的園名。
            parks=[park_card(p) for p in listed if _core(p.name) in _normalize(answer)],
        )

    def fallback(self, park: Park | None) -> ChatResponse:
        if park is None:
            return ChatResponse(source="fallback",
                                answer="助理目前忙碌中（Bedrock 限流），請幾秒後再問一次。")
        brief = brief_for(self.store, park)
        focus = "\n".join(f"- {a.focus}：{a.why}" for a in brief.actions)
        return ChatResponse(
            source="fallback", park=park_card(park),
            answer=f"助理目前忙碌中，先提供系統整理的摘要（未含法規檢索）：\n\n{brief.summary}"
                   + (f"\n\n建議稽查重點：\n{focus}" if focus else ""),
        )
