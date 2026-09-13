import json
import uuid
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.services import current_week

BASE = "/api/v1"


def write(directory, name, document):
    (directory / f"{name}.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/meta",
        "/parks",
        "/parks/park-1",
        "/parks/park-1/brief",
        "/risk/top",
        "/districts",
        "/map",
        "/curve",
        "/worklist",
    ],
)
def test_all_nine_contracts(client, path):
    response = client.get(BASE + path)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    uuid.UUID(response.headers["x-request-id"])
    assert response.headers["x-data-version"] == "test-v1"
    assert response.headers["cache-control"] == "public, max-age=60"


def test_list_pagination_filters_and_aliases(client):
    page = client.get(BASE + "/parks", params={"page": 2, "size": 2}).json()
    assert page["total"] == 3
    assert [p["park_id"] for p in page["items"]] == ["park-3"]
    assert page["items"][0]["type"] == page["items"][0]["institution_type"]
    params = [
        ("town", "板橋區"),
        ("town", "新店區"),
        ("type", "公立,非營利"),
        ("tier", "中"),
        ("q", "  測試  "),
    ]
    result = client.get(BASE + "/parks", params=params).json()
    assert [p["park_id"] for p in result["items"]] == ["park-2"]
    flagged = client.get(BASE + "/parks?has_finance_flag=true").json()
    assert [p["park_id"] for p in flagged["items"]] == ["park-2"]
    assert client.get(BASE + "/parks?page=99").json()["items"] == []
    assert client.get(BASE + "/parks?q=不存在").json()["total"] == 0


def test_media_page_aggregates_by_park_and_anchors_the_window_to_the_data(client):
    """/media 的四個容易走偏的地方一次釘住。

    觀察窗錨在資料最後一則報導，不是今天——錨在今天的話，資料一週沒更新，
    「近 12 個月」就會悄悄少掉一週，同一份 demo 在不同日子跑出不同名單。
    """
    body = client.get(BASE + "/media").json()
    assert body["as_of"] == "2025-03-06"  # 含查無園所那列的日期，錨點看的是資料
    assert body["since"] < body["as_of"]
    items = {i["park_id"]: i for i in body["items"]}

    # 1. 指向不存在園所的報導直接丟掉，不會生出一列沒有名字的園。
    assert "park-404" not in items
    # 2. 觀察窗外的報導不計入（park-3 只有 2019 那一則）。
    assert "park-3" not in items
    # 3. 聚合數字。切點後的報導照收並單獨計數，讓前端標示得出來。
    assert items["park-1"]["article_count"] == 3
    assert items["park-1"]["after_cutoff_count"] == 2
    assert items["park-1"]["latest_date"] == "2025-03-05"
    assert items["park-1"]["max_severity"] == 3  # severity 為 None 的那列略過
    # 4. 平手時用類型名決勝。超收與師生比各 1 次，靠 Counter 的插入順序會拿到
    #    「超收」（列序在前），重跑 ETL 換個排序就會變；穩定實作回「師生比」。
    assert items["park-1"]["top_event_type"] == "師生比"

    # 排序：報導數多的在前。
    assert [i["park_id"] for i in body["items"]] == ["park-1", "park-2"]


def test_media_window_narrows_with_months_and_never_shows_names(client):
    narrow = client.get(BASE + "/media?months=1").json()
    assert narrow["months"] == 1
    assert narrow["since"] > client.get(BASE + "/media").json()["since"]
    # 一個月的窗只留 2025-02-05 之後的，park-2 那則 2025-02-01 掉出去。
    assert [i["park_id"] for i in narrow["items"]] == ["park-1"]
    assert narrow["items"][0]["article_count"] == 2
    # 契約裡沒有任何自然人欄位，回應也不得夾帶。
    assert "owner" not in json.dumps(narrow, ensure_ascii=False)


def test_punished_filter_separates_parks_with_and_without_records(client):
    """有無裁罰紀錄要兩邊都篩得出來。

    省略參數＝不篩。false 這一邊不是湊數的：零裁罰卻排進高風險的園，
    分數全部來自評鑑，是稽查人員會特別想挑出來看的一群。
    """
    everyone = client.get(BASE + "/parks").json()
    with_records = client.get(BASE + "/parks?punished=true").json()
    without = client.get(BASE + "/parks?punished=false").json()
    assert [p["park_id"] for p in with_records["items"]] == ["park-1", "park-2"]
    assert [p["park_id"] for p in without["items"]] == ["park-3"]
    assert with_records["total"] + without["total"] == everyone["total"]
    assert all(p["pun_count"] > 0 for p in with_records["items"])
    assert all(p["pun_count"] == 0 for p in without["items"])
    ids = lambda body: {f["properties"]["park_id"] for f in body["features"]}
    assert ids(client.get(BASE + "/map?punished=false").json()) == {"park-3"}
    assert "park-3" not in ids(client.get(BASE + "/map?punished=true").json())


@pytest.mark.parametrize(
    "query,expected",
    [
        ("sort=risk", ["park-1", "park-2", "park-3"]),
        ("sort=risk&dir=desc", ["park-3", "park-2", "park-1"]),
        ("sort=name", ["park-1", "park-2", "park-3"]),
        ("sort=name&dir=desc", ["park-3", "park-2", "park-1"]),
        ("sort=pun_count", ["park-2", "park-1", "park-3"]),
        ("sort=pun_count&dir=asc", ["park-3", "park-1", "park-2"]),
    ],
)
def test_sorting(client, query, expected):
    assert [p["park_id"] for p in client.get(BASE + "/parks?" + query).json()["items"]] == expected


def test_inactive_detail_and_top_limit(client):
    detail = client.get(BASE + "/parks/park-4").json()
    assert detail["is_active"] == 0
    assert detail["risk"]["rank"] is None
    assert detail["dimensions"]["operation"]["score"] is None
    result = client.get(BASE + "/risk/top?k=2").json()
    assert result["k"] == 2
    assert [p["park_id"] for p in result["items"]] == ["park-1", "park-2"]
    assert all("reasons" in p and "finance_flags" in p for p in result["items"])


def test_map_joins_town_without_mutating_cache(client):
    filtered = client.get(BASE + "/map?town=板橋區&tier=低").json()["features"]
    assert [f["properties"]["park_id"] for f in filtered] == ["park-3"]
    assert filtered[0]["properties"]["town"] == "板橋區"
    assert len(client.get(BASE + "/map").json()["features"]) == 3
    assert client.get(BASE + "/map?town=不存在").json()["features"] == []


def test_brief_fallback_including_park_without_reasons(client):
    for park_id in ("park-1", "park-3"):
        brief = client.get(f"{BASE}/parks/{park_id}/brief").json()
        assert brief["source"] == "template"
        assert brief["summary"] and brief["generated_at"] and brief["reasons"]
        assert len(brief["actions"]) <= 3
        assert "核定 100 人" in str(brief["actions"])


def test_offline_brief_and_failed_llm_fallback(serving_dir):
    valid = {
        "park_id": "park-1",
        "source": "llm",
        "summary": "預先產生的查核建議",
        "reasons": ["已有裁罰紀錄"],
        "actions": [{"focus": "師生比", "why": "第16條第4項"}],
        "generated_at": "2026-09-12T06:00:00Z",
    }
    write(serving_dir, "briefs", {"park-1": valid})
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        assert c.get(BASE + "/parks/park-1/brief").json()["source"] == "llm"
    valid["summary"] = ""
    write(serving_dir, "briefs", {"items": [valid]})
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        assert c.get(BASE + "/parks/park-1/brief").json()["source"] == "template"


def test_worklist_generates_exactly_three_reasons_grounded_actions(client):
    worklist = client.get(BASE + "/worklist?k=3").json()
    assert worklist["week"] == current_week()
    assert len(worklist["items"]) == 3
    for seq, row in enumerate(worklist["items"], 1):
        assert row["seq"] == seq
        assert len(row["reasons"]) == 3
        assert len(row["actions"]) <= 3
        assert row["attachments"]["evaluation_count"] is None  # Do not fabricate four evaluations.
        assert "owner_key" not in row
        for action in row["actions"]:
            assert "第16條第4項" in action["why"] or "核定 100 人" in str(action)


def test_offline_worklist_week_and_limit(serving_dir, client):
    stored = client.get(BASE + "/worklist?k=2").json()
    stored["week"] = "2020-W01"
    write(serving_dir, "worklist", stored)
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        result = c.get(BASE + "/worklist?week=2020-W01&k=1").json()
        assert result["week"] == "2020-W01" and len(result["items"]) == 1
        assert c.get(BASE + "/worklist?week=2020-W02").status_code == 503
        assert c.get(BASE + "/worklist").json()["week"] == current_week()


def test_archive_worklist(serving_dir, client):
    stored = client.get(BASE + "/worklist?k=2").json()
    stored["week"] = "2021-W01"
    write(serving_dir, "worklist-2021-w01", stored)
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        result = c.get(BASE + "/worklist?week=2021-W01&k=1")
        assert result.status_code == 200 and len(result.json()["items"]) == 1


def test_historical_worklist_does_not_rewrite_evidence_from_latest_scores(serving_dir, client):
    stored = client.get(BASE + "/worklist?k=1").json()
    stored["week"] = "2020-W01"
    stored["items"][0]["park_id"] = "park-no-longer-in-current-snapshot"
    stored["items"][0]["actions"] = [{"focus": "師生比", "why": "歷史紀錄涉及第43條第2項"}]
    write(serving_dir, "worklist", stored)
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        result = c.get(BASE + "/worklist?week=2020-W01&k=1")
        assert result.status_code == 200
        assert result.json()["items"] == stored["items"]


def test_detail_merges_related_data(serving_dir):
    write(serving_dir, "fees", {"items": [{"park_id": "park-1", "school_year": 115, "items": []}]})
    write(
        serving_dir,
        "finance",
        {
            "park-1": [
                {"school_year": 113, "validated": False, "source_pdf": "raw/pdf/park-1/113.pdf"}
            ]
        },
    )
    write(serving_dir, "evaluations", [{"park_id": "park-1", "year": 113}])
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        detail = c.get(BASE + "/parks/park-1").json()
        assert detail["fees"][0]["school_year"] == 115
        assert detail["finance"][0]["pdf_url"] is None  # No public URL invented in local mode.
        assert len(detail["evaluations"]) == 1
        assert (
            c.get(BASE + "/worklist?k=1").json()["items"][0]["attachments"]["evaluation_count"] == 1
        )


def test_detail_without_media_coverage_file_returns_empty_list(serving_dir):
    """沒有這份 serving 檔就是沒有輿情明細，不得回退到別的來源。"""
    (serving_dir / "media_coverage.json").unlink()
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        assert c.get(BASE + "/parks/park-1").json()["media_coverage"] == []
        # 輿情分頁同樣不得無中生有，且空窗要回得乾淨而不是 500。
        assert c.get(BASE + "/media").json()["items"] == []


def test_media_coverage_is_the_one_place_after_cutoff_dates_are_allowed(serving_dir):
    """輿情明細**刻意**帶切點之後的報導，這是它與所有計分資料的分界。

    分數那條路由 etl.quality.assert_no_leakage 守著切點；這一份走另一條路，
    只要標明 is_after_cutoff 就可以顯示，否則像欣勵德 2026-04 的虐童案
    （全部在切點之後）在稽查人員面前會完全不存在。
    """
    write(
        serving_dir,
        "media_coverage",
        {
            "items": [
                {
                    "park_id": "park-1",
                    "date": "2026-04-11",
                    "outlet": "測試報",
                    "title": "測試甲幼兒園遭指不當管教",
                    "url": "https://example.invalid/a",
                    "event_type": "不當管教",
                    "severity": 5,
                    "is_after_cutoff": True,
                },
                {
                    "park_id": "park-2",
                    "date": "2024-05-01",
                    "title": "別園的報導",
                    "is_after_cutoff": False,
                },
            ]
        },
    )
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        coverage = c.get(BASE + "/parks/park-1").json()["media_coverage"]
        assert len(coverage) == 1, "別園的報導不得掛到這一園"
        assert coverage[0]["is_after_cutoff"] is True
        assert coverage[0]["date"] > "2025-01-01"
        assert coverage[0]["severity"] == 5


@pytest.mark.parametrize(
    "path",
    [
        "/parks?size=0",
        "/parks?size=201",
        "/parks?page=0",
        "/parks?page=abc",
        "/parks?sort=bad",
        "/parks?dir=bad",
        "/parks?type=bad",
        "/parks?tier=bad",
        "/parks?has_finance_flag=bad",
        "/parks?punished=bad",
        "/map?punished=bad",
        "/risk/top?k=abc",
        "/risk/top?k=0",
        "/risk/top?k=201",
        "/map?tier=bad",
        "/worklist?k=201",
        "/worklist?week=bad",
        "/worklist?week=2026-W00",
        "/worklist?week=2021-W53",
        "/worklist?week=2026-W54",
    ],
)
def test_invalid_parameters(client, path):
    response = client.get(BASE + path)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARAM"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/parks/missing", "/parks/missing/brief", "/not-a-route"])
def test_not_found(client, path):
    response = client.get(BASE + path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PARK_NOT_FOUND"


def test_method_and_request_trace(client, caplog):
    caplog.set_level("INFO", logger="watchdog.api")
    first = client.get(BASE + "/meta")
    second = client.get(BASE + "/meta")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert first.headers["x-request-id"] in caplog.text
    response = client.post(BASE + "/meta")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_cors_and_openapi(client):
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    preflight = client.options(BASE + "/parks", headers=headers)
    assert preflight.status_code == 200 and "x-request-id" in preflight.headers
    allowed = client.get(BASE + "/parks/missing", headers={"Origin": headers["Origin"]})
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    denied = client.get(BASE + "/meta", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in denied.headers
    bad_preflight = client.options(
        BASE + "/parks",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert bad_preflight.status_code == 400
    assert bad_preflight.json()["error"]["code"] == "INVALID_PARAM"
    schema = client.get("/openapi.json").json()
    # 凍結契約的 9 支 GET、/media，加上 ADR-0005 新增的 POST /chat。
    assert len(schema["paths"]) == 11
    assert set(schema["paths"][BASE + "/chat"]) == {"post"}
    assert "400" in schema["paths"][BASE + "/parks"]["get"]["responses"]
    assert "422" not in schema["paths"][BASE + "/parks"]["get"]["responses"]


def test_missing_data_recovers_and_errors_do_not_leak(tmp_path, artifacts):
    with TestClient(create_app(Settings(serving_dir=tmp_path))) as c:
        response = c.get(BASE + "/meta")
        assert response.status_code == 503
        assert str(tmp_path) not in response.text
        write(tmp_path, "meta", artifacts["meta"])
        assert c.get(BASE + "/meta").status_code == 200


@pytest.mark.parametrize("mutation", ["score", "operation", "reason", "pii", "hash", "json"])
def test_corrupt_serving_is_500_not_user_error(serving_dir, artifacts, mutation):
    data = deepcopy(artifacts["scores"])
    row = data["items"][0]
    if mutation == "score":
        row["risk"]["score"] = 101
    elif mutation == "operation":
        row["dimensions"]["operation"]["score"] = 0
    elif mutation == "reason":
        row["reasons"][0]["code"] = "UNKNOWN"
    elif mutation == "pii":
        row["owner"] = "Example Person"
    elif mutation == "hash":
        row["owner_key"] = "Example Person"
    write(serving_dir, "scores", data)
    if mutation == "json":
        (serving_dir / "scores.json").write_text("{invalid")
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        response = c.get(BASE + "/parks", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "Example Person" not in response.text and "Traceback" not in response.text
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_pii_in_offline_worklist_rejected(serving_dir, client):
    sheet = client.get(BASE + "/worklist?k=1").json()
    sheet["items"][0]["reasons"][0] = "負責人：測試姓名"
    write(serving_dir, "worklist", sheet)
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        response = c.get(BASE + "/worklist")
        assert response.status_code == 500 and "測試姓名" not in response.text


def test_real_scores_can_join_basic_parks(serving_dir, artifacts):
    scores, basics = [], []
    basic_fields = {"name", "town", "address", "tel", "lon", "lat", "is_active", "count_approved"}
    for row in artifacts["scores"]["items"]:
        scores.append({k: v for k, v in row.items() if k not in basic_fields})
        basics.append({k: v for k, v in row.items() if k in basic_fields or k == "park_id"})
    write(serving_dir, "scores", scores)
    write(serving_dir, "parks", basics)
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as c:
        assert c.get(BASE + "/parks").json()["total"] == 3


def test_dropped_dimension_weight_is_null_not_zero(client):
    """SPEC 5.0: a dimension removed from scoring carries weight null.

    ADR-0001 measured the sentiment dimension and took it out (district heat
    scored 0.74x lift, below random). out/serving/meta.json therefore ships
    sentiment: null. The schema originally allowed null only for operation,
    so every route returned 500 the first time real data was uploaded - the
    mock's sentiment: 0.15 had validated fine for weeks. Null and zero are
    not interchangeable here: zero would claim the dimension was scored and
    contributed nothing, null says it was never scored.
    """
    weights = client.get(BASE + "/meta").json()["weights"]
    for institution, w in weights.items():
        assert w["sentiment"] is None, institution
        total = sum(v for v in w.values() if v is not None)
        assert abs(total - 1.0) < 1e-6, (institution, total)
