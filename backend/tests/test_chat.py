"""稽查助手（ADR-0005）：找園、個資擋下、限流退回模板、節流間隔、引用檢核。"""

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.chat import AssistantUnavailable, BedrockPacer, has_person_name
from backend.config import Settings

BASE = "/api/v1"
LAW = {
    "text": "《幼兒教育及照顧法》第16條\n三歲以上至入國民小學前幼兒，每班以三十人為限。",
    "law_name": "幼兒教育及照顧法",
    "article": "第16條",
    "source_url": "https://edu.law.moe.gov.tw/LawContent.aspx?id=GL000542",
    "score": 0.61,
}


class FakeClients:
    def __init__(self, answer="總結。\n風險現況\n- 高\n建議稽查重點\n- 師生比《幼兒教育及照顧法》第16條",
                 fail=None):
        self.answer_text = answer
        self.fail = fail
        self.queries, self.prompts = [], []

    def retrieve(self, query, k=6):
        if self.fail == "retrieve":
            raise AssistantUnavailable
        self.queries.append(query)
        return [LAW]

    def answer(self, system, user):
        if self.fail == "answer":
            raise AssistantUnavailable
        self.prompts.append(user)
        return self.answer_text


class NoWaitPacer(BedrockPacer):
    def __init__(self):
        super().__init__(interval=1.1, clock=lambda: 0.0, sleep=lambda s: None)


@pytest.fixture
def fake():
    return FakeClients()


def make_client(serving_dir, clients):
    app = create_app(Settings(serving_dir=serving_dir), chat_clients=clients)
    return TestClient(app)


def test_disabled_without_knowledge_base(client):
    response = client.post(BASE + "/chat", json={"message": "師生比規定"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASSISTANT_DISABLED"


def test_park_by_name_grounds_prompt_in_serving_facts(serving_dir, fake, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    with make_client(serving_dir, fake) as c:
        response = c.post(BASE + "/chat", json={"message": "測試1幼稚園最近狀況如何？"})
    body = response.json()
    assert response.status_code == 200 and body["source"] == "llm"
    assert body["park"]["park_id"] == "park-1" and body["park"]["rank"] == 1
    assert body["citations"][0]["article"] == "第16條"
    assert body["unverified_refs"] == []
    # 名次與裁罰類別來自 store，並被用來擴充檢索字詞。
    assert '"全市名次": 1' in fake.prompts[0]
    assert "師生比" in fake.queries[0] and "班級人數" in fake.queries[0]
    assert "owner_key" not in fake.prompts[0] and "012345abcdef" not in fake.prompts[0]
    assert response.headers["cache-control"] == "no-store"


def test_explicit_park_id_and_unknown_id(serving_dir, fake, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    with make_client(serving_dir, fake) as c:
        ok = c.post(BASE + "/chat", json={"message": "要查什麼", "park_id": "park-2"})
        missing = c.post(BASE + "/chat", json={"message": "要查什麼", "park_id": "nope"})
    assert ok.json()["park"]["park_id"] == "park-2"
    assert missing.status_code == 404


def test_general_question_has_no_park(serving_dir, fake, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    with make_client(serving_dir, fake) as c:
        body = c.post(BASE + "/chat", json={"message": "班級人數上限是多少"}).json()
    assert body["source"] == "llm" and body["park"] is None
    assert "<全市資料>" in fake.prompts[0]


def prompt_data(prompt, tag="全市資料"):
    import json

    return json.loads(prompt.split(f"<{tag}>")[1].split(f"</{tag}>")[0])


def test_which_park_to_inspect_uses_backend_ranking(serving_dir, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    # 模型寫簡稱「測試1幼兒園」而名單是全名時也要能連結。
    clients = FakeClients(answer="總結\n建議優先稽查\n- 測試1幼兒園（板橋區，全市第1名）：裁罰多")
    with make_client(serving_dir, clients) as c:
        body = c.post(BASE + "/chat", json={"message": "我們現在應該要查哪一間幼兒園"}).json()
    data = prompt_data(clients.prompts[0])
    # 停辦園不進名單；名次照 serving 資料排序。
    assert [row["全市名次"] for row in data["名單"]] == [1, 2, 3]
    assert data["名單"][0]["園名"] == "測試1幼兒園"
    assert [p["park_id"] for p in body["parks"]] == ["park-1"]


def test_city_list_filters_by_district_type_and_category(serving_dir, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    clients = FakeClients()
    with make_client(serving_dir, clients) as c:
        c.post(BASE + "/chat", json={"message": "新店區公立的要查哪間"})
        c.post(BASE + "/chat", json={"message": "師生比問題最多的是哪幾間"})
    district = prompt_data(clients.prompts[0])
    assert district["篩選條件"]["行政區"] == ["新店區"]
    assert [row["園名"] for row in district["名單"]] == ["測試2幼兒園"]
    category = prompt_data(clients.prompts[1])
    # park-2 有 2 筆師生比、park-1 有 1 筆；非營利 park-3 沒有裁罰被排除。
    assert [row["園名"] for row in category["名單"]] == ["測試2幼兒園", "測試1幼兒園"]


def test_district_name_is_not_mistaken_for_a_park(serving_dir, artifacts, fake, monkeypatch):
    import json

    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    artifacts["scores"]["items"][0]["name"] = "新北市私立板橋幼兒園"
    (serving_dir / "scores.json").write_text(json.dumps(artifacts["scores"], ensure_ascii=False),
                                             encoding="utf-8")
    with make_client(serving_dir, fake) as c:
        district = c.post(BASE + "/chat", json={"message": "板橋區要查哪間"}).json()
        park = c.post(BASE + "/chat", json={"message": "板橋幼兒園狀況"}).json()
    assert district["park"] is None
    assert park["park"]["park_id"] == "park-1"


def test_ambiguous_name_returns_candidates_without_calling_bedrock(serving_dir, artifacts, fake):
    artifacts["scores"]["items"][1]["name"] = "測試1幼兒園"
    import json

    (serving_dir / "scores.json").write_text(json.dumps(artifacts["scores"], ensure_ascii=False),
                                             encoding="utf-8")
    with make_client(serving_dir, fake) as c:
        body = c.post(BASE + "/chat", json={"message": "測試1幼兒園"}).json()
    assert body["source"] == "candidates" and len(body["candidates"]) == 2
    assert fake.queries == [] and fake.prompts == []


@pytest.mark.parametrize("message", ["負責人：王小明 的園", "王小明老師是不是有問題", "陳園長最近怎樣"])
def test_person_names_are_blocked_before_bedrock(serving_dir, fake, message):
    with make_client(serving_dir, fake) as c:
        body = c.post(BASE + "/chat", json={"message": message}).json()
    assert body["source"] == "blocked"
    assert fake.queries == [] and fake.prompts == []


@pytest.mark.parametrize(
    "message",
    [
        "園長的資格規定是什麼",
        "林口區的幼兒園超收怎麼罰",
        "專任教保員的配置規定",
        "現任園長的資格",
        "兼任主任要具備什麼資格",
    ],
)
def test_ordinary_questions_are_not_blocked(message):
    assert not has_person_name(message)


@pytest.mark.parametrize("fail", ["retrieve", "answer"])
def test_bedrock_failure_falls_back_to_template(serving_dir, monkeypatch, fail):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    with make_client(serving_dir, FakeClients(fail=fail)) as c:
        body = c.post(BASE + "/chat", json={"message": "測試1幼兒園狀況"}).json()
    assert body["source"] == "fallback" and body["park"]["park_id"] == "park-1"
    assert "測試1幼兒園" in body["answer"] and body["citations"] == []


def test_references_outside_retrieved_laws_are_flagged(serving_dir, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    answer = "依《幼兒教育及照顧法》第16條與《幼兒教育及照顧法》第99條，另見《不存在法》。"
    with make_client(serving_dir, FakeClients(answer=answer)) as c:
        body = c.post(BASE + "/chat", json={"message": "測試1幼兒園"}).json()
    assert body["unverified_refs"] == ["《幼兒教育及照顧法》第99條", "《不存在法》"]


def test_input_validation(serving_dir, fake):
    with make_client(serving_dir, fake) as c:
        assert c.post(BASE + "/chat", json={"message": ""}).status_code == 400
        assert c.post(BASE + "/chat", json={"message": "x" * 501}).status_code == 400
        assert c.post(BASE + "/chat", json={"message": "hi", "extra": 1}).status_code == 400


def test_pacer_spaces_every_bedrock_call():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(round(seconds, 3))
        now[0] += seconds

    pacer = BedrockPacer(interval=1.1, clock=lambda: now[0], sleep=sleep)
    pacer.wait()              # 第一個請求不等
    now[0] += 0.3
    pacer.wait()              # 距上一個 0.3 秒 → 補 0.8
    now[0] += 2.0
    pacer.wait()              # 已超過間隔 → 不等
    pacer.settle()            # 回應前補足 → 1.1
    assert sleeps == [0.8, 1.1]


def test_basic_mode_without_knowledge_base_skips_retrieval(serving_dir, monkeypatch):
    monkeypatch.setattr("backend.chat.BedrockPacer", NoWaitPacer)
    clients = FakeClients(answer="總結。\n建議稽查重點\n- 師生比\n法規依據待法規庫啟用後補上")
    clients.has_laws = False
    with make_client(serving_dir, clients) as c:
        body = c.post(BASE + "/chat", json={"message": "測試1幼兒園狀況"}).json()
    assert body["source"] == "llm" and body["laws_enabled"] is False
    assert body["citations"] == [] and clients.queries == []
    assert "法規庫尚未啟用" in clients.prompts[0]


def test_chat_enabled_env_turns_on_basic_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAT_ENABLED", "true")
    monkeypatch.delenv("KB_ID", raising=False)
    settings = Settings.from_env()
    assert settings.chat_enabled and settings.kb_id is None
