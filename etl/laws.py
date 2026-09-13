"""法規 PDF → 知識庫文件（一條條文一份）。ADR-0005。

    python -m etl.laws                    # 核心批 → out/kb/laws.jsonl
    python -m etl.laws --batch all        # 核心 + 延伸

為什麼一條一份、不讓 Bedrock 自己切塊：競賽規範要求 Bedrock 請求 ≤ 每秒 1 次。
交給 Knowledge Base 的 StartIngestionJob 批次切塊時，嵌入呼叫的速度由 Bedrock
決定；預先切好、chunking = NONE，再由 `infra/rag/setup_kb.py` 一份一份送，
每份文件恰好對應一次嵌入，速度才握在我們手上。

需要 poppler 的 `pdftotext`（macOS：`brew install poppler`）。
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAWS = ROOT / "法規"

# 核心批：稽查現場會引用、或新北裁罰實際涉及的法規。
CORE = {
    "全國性法律": [
        "幼兒教育及照顧法",                  # 新北 1,464 筆裁罰引用的主法
        "幼兒教育及照顧法施行細則",
        "教保服務人員條例",                  # 師資、不適任
        "教保服務人員條例施行細則",
        "幼兒園及其分班基本設施設備標準",      # 設施安全
        "幼兒教保及照顧服務實施準則",          # 食安衛生、教保禁止規定
        "幼兒園與其分班設立變更及管理辦法",    # 超收、擴充
        "幼兒園幼童專用車輛與其駕駛人及隨車人員督導管理辦法",  # 交通車
        "幼兒園餐點食物內容及營養基準",        # 食安衛生
        "幼兒園評鑑辦法",                    # 評鑑維度
        "教保服務機構收費項目及用途",          # 收費爭議
        "教保相關人員違法事件調查處理辦法",    # 不當對待
        "教保相關人員違法對待幼兒事件罰鍰金額及終身或一定期間不得聘任任用進用或運用之裁量基準",
        "教保服務人員輔導與管教幼兒注意事項",  # 不當管教
        "教保服務機構不適任人員認定通報資訊蒐集查詢處理利用及違法事件通報辦法",
        "幼兒教育及照顧法與教保服務人員條例公布負責人行為人機構名稱及場址之公布期間",
        "幼兒園兼辦國民小學兒童課後照顧服務辦法",  # 其他行政（課後照顧）
        "幼兒園行政組織及員額編制標準",        # 師生比、人員配置
        "非營利幼兒園實施辦法",
        "兒童及少年福利與權益保障法",
    ],
    "地方性法規": [
        "新北市政府處理違反幼兒教育及照顧法與教保服務人員條例事件裁罰基準",
        "新北市教保服務機構收退費辦法",
        "新北市幼兒園辦理校外教學活動注意事項",
        "新北市公私立學校及幼兒園腸病毒通報及停課作業規定",
    ],
}

# 延伸批刻意排除的主題：與園所稽查無關，進了只會稀釋檢索。
EXCLUDE = re.compile(
    r"師資|教師證書|教師資格|教師進修|學分|補助|獎勵|獎補助|敘獎|激勵|遴選|遴聘|請假|超額|"
    r"介聘|代理人員|地域加給|諮詢會|輔導團|設置要點|設置辦法|系科|學程|考試|命題|"
    r"國立自然科學博物館|H7N9|身心障礙學生|特殊教育|鑑定|轉銜|母語|語言能力"
)

# 全國法規資料庫用「第 16 條」，教育部主管法規系統用「第十六條」「第十條之一」。
ARTICLE_HEAD = re.compile(
    r"^第\s*([\d一二三四五六七八九十百零]+)(?:-(\d+))?\s*條(?:之([一二三四五六七八九十\d]+))?$")
_DIGIT = dict(zip("零一二三四五六七八九", range(10)))


def cn_number(text):
    """「一百零二」→ 102；阿拉伯數字原樣回傳。"""
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch in _DIGIT:
            current = _DIGIT[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


def article_label(match):
    sub = match.group(2) or match.group(3)
    number = cn_number(match.group(1))
    return f"第{number}-{cn_number(sub)}條" if sub else f"第{number}條"


CHAPTER = re.compile(r"^第\s*[一二三四五六七八九十]+\s*章")
MAX_CHARS = 2000


def pdf_text(path: Path) -> str:
    return subprocess.run(["pdftotext", str(path), "-"], check=True,
                          capture_output=True, text=True).stdout


def unwrap(lines):
    """pdftotext 會在固定寬度斷行；句末不是標點的行接回下一行。"""
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out and not re.search(r"[。：:；;！？」）)]$", out[-1]):
            out[-1] += line
        else:
            out.append(line)
    return "\n".join(out)


def render_box_tables(lines):
    """把 pdftotext 抽出的框線表格（┌─┬─┐│├┼┤└┴┘）改寫成一列一行的「欄名：值」。

    不改寫的話，unwrap 會把整張表接成一行框線字元，前端顯示與模型閱讀都會亂掉。
    合併儲存格在下一列是空的，填「同上」；分隔線 ├…┤ 後面若還有文字，是上一列
    跨列欄位的續行（例如「十四公分」換行接「以下」）。
    """
    out, header, rows, current, inside = [], None, [], None, False

    def cells(text):
        return [c.strip() for c in text.strip().strip("│").split("│")]

    def close():
        nonlocal current, header
        if current is not None and any(current):
            if header is None:
                header = current
            else:
                rows.append(current)
        current = None

    for line in lines:
        s = line.strip()
        if s.startswith("┌"):
            inside, header, rows, current = True, None, [], None
            continue
        if not inside:
            out.append(line)
            continue
        if s.startswith("│"):
            parts = cells(s)
            if current is None:
                current = [""] * len(parts)
            for i, part in enumerate(parts[:len(current)]):
                current[i] += part
        elif s.startswith("├"):
            tail = s.rsplit("┤", 1)[1] if "┤" in s else ""
            if tail.strip() and current is not None:
                parts = cells(tail)
                for i, part in enumerate(parts):
                    current[len(current) - len(parts) + i] += part
            close()
        elif s.startswith("└"):
            close()
            for n, row in enumerate(rows):
                values = [v or ("同上" if n else "—") for v in row]
                out.append("；".join(f"{h}：{v}" for h, v in zip(header, values)) + "。")
            inside = False
    return out


def split_long(text, limit=MAX_CHARS):
    """過長條文依句號切開，每段不超過 limit 字。"""
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for sentence in re.split(r"(?<=[。；\n])", text):
        if buf and len(buf) + len(sentence) > limit:
            parts.append(buf)
            buf = ""
        buf += sentence
    if buf:
        parts.append(buf)
    return parts


def sections(name, raw):
    """回傳 [(條號標籤, 內文)]。有「第N條」用條，否則用「一、」，都沒有就整份。"""
    lines = render_box_tables(raw.replace("\f", "\n").splitlines())
    # 標題可能折成兩行，出現在最前面；它不是內文。
    skip = 0
    while skip < len(lines) and lines[skip].strip() and lines[skip].strip() in name:
        skip += 1
    lines = [l for l in lines[skip:] if not CHAPTER.match(l.strip())]

    heads = [i for i, l in enumerate(lines) if ARTICLE_HEAD.match(l.strip())]
    if heads:
        out = []
        for n, start in enumerate(heads):
            end = heads[n + 1] if n + 1 < len(heads) else len(lines)
            label = article_label(ARTICLE_HEAD.match(lines[start].strip()))
            out.append((label, unwrap(lines[start + 1:end])))
        return out

    text = unwrap(lines)
    points = [m for m in re.finditer(r"(?m)^([一二三四五六七八九十百]+)、", text)]
    if len(points) >= 2:
        out = []
        for n, m in enumerate(points):
            end = points[n + 1].start() if n + 1 < len(points) else len(text)
            out.append((m.group(1) + "、", text[m.start():end].strip()))
        return out
    return [("全文", text)]


# 法規本文只寫「如附表」、真正的條文→罰鍰對照在附表 PDF。收錄清單沒抓到附件，
# 2026-09-13 從新北市法規查詢系統 FLAWDAT0202.aspx?fcode=C0050134 另行下載。
ATTACHMENTS = {
    "新北市政府處理違反幼兒教育及照顧法與教保服務人員條例事件裁罰基準": ["附表一", "附表二"],
}
TABLE_ROW = re.compile(r"^([一二三四五六七八九十]+)\s+本\s*[法條]")
TABLE_NOISE = re.compile(r"^\s*(項\s+法條.*|違規事件.*|次\s+依據.*|\d+|附表[一二].*)\s*$")


def table_rows(raw):
    """附表是四欄表格；用 -layout 保留欄位位置，依「項次＋本法/本條例」切列。
    欄位文字會交錯，但每列的違規事件、罰則與裁罰基準都完整留在同一份文件裡。"""
    lines = [l for l in raw.replace("\f", "\n").splitlines()
             if l.strip() and not TABLE_NOISE.match(l)]
    starts = [i for i, l in enumerate(lines) if TABLE_ROW.match(l)]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        text = "\n".join(re.sub(r"\s{2,}", "  ", l.strip()) for l in lines[start:end])
        yield f"第{TABLE_ROW.match(lines[start]).group(1)}項", text


def catalog():
    with open(LAWS / "收錄清單.csv", encoding="utf-8-sig") as fh:
        return {(r["類別"], r["法規名稱"]): r for r in csv.DictReader(fh)}


def selected(batch):
    rows = catalog()
    chosen = [(level, name) for level, names in CORE.items() for name in names]
    if batch == "all":
        for (level, name), row in sorted(rows.items()):
            if (row["狀態"] == "完成" and (level, name) not in chosen
                    and not EXCLUDE.search(name)
                    and (LAWS / level / f"{name}.pdf").exists()):
                chosen.append((level, name))
    return chosen, rows


def build(batch):
    chosen, rows = selected(batch)
    core = {(level, name) for level, names in CORE.items() for name in names}
    docs, stats = [], []
    for level, name in chosen:
        path = LAWS / level / f"{name}.pdf"
        if not path.exists():
            raise FileNotFoundError(f"核心批缺檔：{path}")
        url = rows.get((level, name), {}).get("官方來源", "")
        count = 0
        units = list(sections(name, pdf_text(path)))
        for table in ATTACHMENTS.get(name, []):
            raw = subprocess.run(["pdftotext", "-layout", str(LAWS / level / f"{name}_{table}.pdf"), "-"],
                                 check=True, capture_output=True, text=True).stdout
            units += [(f"{table}{label}", text) for label, text in table_rows(raw)]
        for seq, (label, text) in enumerate(units):
            if not text:
                continue
            pieces = split_long(text)
            for i, piece in enumerate(pieces, 1):
                part = f"（{i}/{len(pieces)}）" if len(pieces) > 1 else ""
                # 以段落序號當鍵：「一、」在分章的注意事項裡會重複出現。
                key = f"{level}|{name}|{seq}|{i}"
                docs.append({
                    "id": "law-" + hashlib.sha1(key.encode()).hexdigest()[:20],
                    "text": f"《{name}》{label}{part}\n{piece}",
                    "metadata": {
                        "law_name": name, "article": label, "level": level,
                        "source_url": url,
                        "batch": "core" if (level, name) in core else "extended",
                    },
                })
                count += 1
        stats.append((count, name))
    return docs, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["core", "all"], default="core")
    ap.add_argument("--out", default=str(ROOT / "out" / "kb" / "laws.jsonl"))
    args = ap.parse_args()

    docs, stats = build(args.batch)
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids)), "文件 id 重複"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    for count, name in stats:
        print(f"{count:>5}  {name}")
    chars = sum(len(d["text"]) for d in docs)
    print(f"\n{len(stats)} 部法規、{len(docs)} 份文件、{chars:,} 字 → {out}")


if __name__ == "__main__":
    main()
