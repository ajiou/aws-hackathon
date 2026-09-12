"""原始檔載入與清洗。SPEC §2.2、§3.10 第 1–3 步。

抽出來獨立一支，是因為 build_curated 與 operation（B 軌）都要讀同一批來源，
而「preschools.json 其實是 GeoJSON」「reg_date 有 1970 佔位值」這類事實
只該有一個地方知道。
"""
import json
import re
from pathlib import Path

from .constants import CITY, DROP_COLUMNS
from .pii import hash_person

DATA = Path(__file__).resolve().parent.parent / "data"

_NUM = re.compile(r"[\d,]+(?:\.\d+)?")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_area(value):
    """`"254.88平方公尺"` → 254.88；空字串 → None。SPEC §2.2 第 5 項。"""
    if not value:
        return None
    m = _NUM.search(str(value))
    return float(m.group(0).replace(",", "")) if m else None


def parse_int(value):
    if value in (None, ""):
        return None
    m = _NUM.search(str(value))
    return int(float(m.group(0).replace(",", ""))) if m else None


def parse_floors(value):
    """`"1樓、2樓"` → 2。SPEC §2.2 第 6 項。"""
    if not value:
        return None
    parts = [p for p in re.split(r"[、,，]", str(value)) if p.strip()]
    return len(parts) or None


def parse_afterschool(value):
    """`"有，人數：60"` → (True, 60)；`"無"` → (False, None)。SPEC §2.2 第 7 項。"""
    text = str(value or "").strip()
    if not text or text.startswith("無"):
        return False, None
    return True, parse_int(text)


def parse_date(value):
    """`2020/09/23` → `2020-09-23`。1970/01/01 是佔位值，回 None（SPEC §2.2 第 3 項）。"""
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    if text.startswith("1970-01-01"):
        return None
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def load_parks():
    """`preschools.json` 是 **GeoJSON**，園所在 features[].properties，座標在 geometry。

    回傳新北 1,215 園的清洗後 dict，已雜湊 owner、已刪 DROP_COLUMNS。
    """
    raw = _load(DATA / "preschools.json")["features"]
    parks = []
    for feature in raw:
        p = feature["properties"]
        if p.get("city") != CITY:
            continue
        lon, lat = (feature.get("geometry") or {}).get("coordinates", (None, None))
        has_after, after_count = parse_afterschool(p.get("is_after"))
        reg_date = parse_date(p.get("reg_date"))
        owner = (p.get("owner") or "").strip() or None
        parks.append({
            "park_id": p["id"],
            "name": p["title"],
            "type": p["type"],
            "town": p["town"],
            "address": p.get("address"),
            "tel": p.get("tel"),
            "lon": lon,
            "lat": lat,
            "count_approved": parse_int(p.get("count_approved")),
            "reg_date": reg_date,
            "reg_date_missing": reg_date is None,
            "is_active": p.get("is_active"),
            "is_public_ish": p["type"] in ("公立", "非營利"),
            "pre_public_period": None if p.get("pre_public") in ("無", "", None) else p["pre_public"],
            "owner_key": hash_person(owner),       # None 不可視為同一人（§2.2 第 4 項）
            "size": parse_area(p.get("size")),
            "size_in": parse_area(p.get("size_in")),
            "size_out": parse_area(p.get("size_out")),
            "size_out_missing": parse_area(p.get("size_out")) is None,
            "floor_count": parse_floors(p.get("floor")),
            "has_afterschool": has_after,
            "afterschool_count": after_count,
            "monthly_fee": p.get("monthly"),
            "url": p.get("url") or None,
        })
    assert not (DROP_COLUMNS & set(parks[0])), "DROP_COLUMNS 外洩進 parks"
    return parks


def parse_fine(penalty_raw):
    """從「罰鍰：60,000元」抽出金額，抽不到就回 None。

    141 / 7,007 筆沒有金額：停止招生、減少招收人數、停辦、廢止設立許可。
    這些實質嚴重度高於多數罰鍰，所以回 None 而不是 0——寫 0 會讓前端把最重
    的案子顯示成「罰 0 元」。SPEC §2 第 10 項：嚴重度一律由 category 決定，
    fine 只是給人看的顯示欄位，不進任何權重。
    """
    if not penalty_raw:
        return None
    m = re.search(r"罰鍰：\s*([0-9,]+)\s*元", str(penalty_raw))
    return float(m.group(1).replace(",", "")) if m else None


def load_punishments():
    """`punish.json` 的 key 是 `"負責人：姓名"` / `"行為人：姓名"`，value 的 `id` 是 park_id。

    **這份檔就是 SPEC 說的 `watchdog.db.punishments` 等價匯出**（實測 7,007 筆的 `id`
    100% 對得上 preschools.json）。姓名在 key 上，必須拆出來雜湊，不可原樣帶出。
    """
    raw = _load(DATA / "punish.json")
    out = []
    for key, rows in raw.items():
        role, _, name = str(key).partition("：")
        for row in rows:
            out.append({
                "park_id": row["id"],
                "date": parse_date(row.get("date")),
                "law": (row.get("law") or "").strip(),
                "penalty_raw": row.get("punishment"),
                "fine": parse_fine(row.get("punishment")),
                "target_role": role.strip() or None,
                "target_key": hash_person(name),
            })
    return out


def load_evaluations():
    """`評鑑結果.json`：3,353 列，以 `園名` join（實測 1,101/1,101 完全相符）。"""
    return _load(DATA / "評鑑結果.json")


def load_fees():
    """收費明細：dict of 園名 → 列。每列自帶 `id`（park_id），實測 280 筆全為公立。"""
    return _load(DATA / "新北市公立與非營利幼兒園_115學年度收費明細.json")


def load_media():
    """`data/media/` 七份匯出。回傳 (docs, resolution, links, analysis)。"""
    base = DATA / "media"
    docs = {d["doc_id"]: d for d in _load(base / "docs.json")}
    resolution = _load(base / "doc_resolution.json")
    links = _load(base / "doc_links.json")
    analysis = {a["doc_id"]: a for a in _load(base / "doc_analysis.json")}
    return docs, resolution, links, analysis


def public_standalone_names():
    """公立-獨立同儕群的名冊（SPEC §5.6.0）。

    唯一可靠的來源是 `docs/總說明/*.md` 的 `## ` 標題——那是決算書第五冊的
    預算單位清單。**不可用「名稱含市立」猜**：實測那樣會抓出 64 園（把附設也算進去）。
    三份檔的 union 有 24 個名稱，其中 3 個是錯字變體，正規化後對得上母體。
    """
    docs_dir = DATA.parent / "docs" / "總說明"
    names = set()
    for path in sorted(docs_dir.glob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                names.add(line[3:].strip())
    return {normalize_public_name(n) for n in names}


def normalize_public_name(name):
    """修掉總說明標題的三種錯字：`新北立市八里` / `新北市萬里`（漏「立」）/ 全形空白。"""
    text = name.replace(" ", "").replace("　", "")
    text = text.replace("新北立市", "新北市立")
    if text.startswith("新北市") and not text.startswith("新北市立"):
        text = "新北市立" + text[len("新北市"):]
    return text
