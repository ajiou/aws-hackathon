"""§4 特徵字典。前綴即維度：vio_ / eval_ / media_ / oper_ / display_。

三條貫穿全檔的規則：

1. **一律以 CUTOFF 為界**。任何用到日期的來源都先過濾，不是算完再濾。
2. **缺失填 None，不填 0**。`eval_base_fail_count = 0` 是「評鑑全數通過」（被罰率 9.2%），
   缺失是「沒有評鑑紀錄」（5.8%）——方向相反，混在一起會讓新立案園看起來像模範生。
3. **`display_` 欄位不進模型**，只供前端顯示與分層（§4.5，實測 lift 都在 0.85–1.2x）。
"""
import collections
import math
from datetime import date

from .categories import classify
from .constants import CUTOFF, PUNISH_HALFLIFE_DAYS, SEVERITY, MEDIA_HALFLIFE, MEDIA_HALFLIFE_DEFAULT, SRI_SATURATION

# 不代表風險的輿情事件類型，不進熱度與 SRI
NON_RISK_EVENTS = {"無關", "正面訊息", "政策制度"}
# ptt 是匿名論壇，可信度低於新聞；SPEC §5.5 的 source_weight 沒給值，這裡明訂
SOURCE_WEIGHT = {"gnews": 1.0, "ptt": 0.7}
CATEGORY_KEYS = ["師資", "超收", "不當管教", "師生比", "收費爭議",
                 "食安衛生", "交通車", "設施安全", "性平事件", "其他行政"]


def _days_before(iso_date, ref=CUTOFF):
    return (ref - date.fromisoformat(iso_date)).days


def _decay(days, halflife):
    return 0.5 ** (days / halflife)


def _iso_week(iso_date):
    d = date.fromisoformat(iso_date)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------- 違規維度

def violation_features(parks, punishments, owner_priors):
    """切點前裁罰、負責人前科、兄弟園。SPEC §4.1、§5.3。

    **一次處分 = 一個日期，不是一條法條。** 同一次稽查常同時開出多條法規
    （嘉府 2024-05-31 一天就有超收、師生比、未具資格三條），按法條數算會
    高估「被抓幾次」。實測以 distinct date 聚合後，與 `園所裁罰特徵.json`
    的 `園_處分次數` **1,212 / 1,212 完全相符**——那份檔就是這樣算的。

    嚴重度取當日各法條的**最大值**（最嚴重的那件事代表這次處分），
    不是加總；加總會讓「一次稽查開三條輕罪」看起來比「一次不當對待」嚴重。
    """
    pre = [p for p in punishments if p["date"] and p["date"] < CUTOFF.isoformat()]
    by_park = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in pre:
        by_park[row["park_id"]][row["date"]].append(row)

    def event_count(pid):
        return len(by_park.get(pid, {}))

    # 同負責人分組。owner_key 為 None 的 68 園**不可視為同一人**（§2.2 第 4 項）
    chain = collections.defaultdict(list)
    for park in parks:
        if park["owner_key"]:
            chain[park["owner_key"]].append(park["park_id"])

    out = {}
    for park in parks:
        pid = park["park_id"]
        events = by_park.get(pid, {})
        weighted = 0.0
        cats = collections.Counter()
        for day, rows_of_day in events.items():
            severities = [SEVERITY[classify(r["law"])] for r in rows_of_day]
            weighted += max(severities) * _decay(_days_before(day), PUNISH_HALFLIFE_DAYS)
            for name in {classify(r["law"]) for r in rows_of_day}:
                cats[name] += 1                     # 同日同類別只算一次
        siblings = [q for q in chain.get(park["owner_key"] or "", []) if q != pid]
        prior = owner_priors.get(park["owner_key"] or "", {})

        feat = {
            "vio_pun_weighted": round(weighted, 4),
            "vio_pun_count": len(events),
            "vio_owner_prior_count": prior.get("count", 0),
            "vio_sibling_pun_count": sum(event_count(q) for q in siblings),
            "vio_abuse_count": cats.get("不當管教", 0),
            "vio_days_since_last": (
                min(_days_before(d) for d in events) if events else None
            ),
            "vio_owner_cross_park": bool(prior.get("cross_park", False)),
            "vio_sibling_count": len(siblings),
            "vio_sibling_pun_park_count": sum(1 for q in siblings if event_count(q)),
            "vio_chain_size": len(chain.get(park["owner_key"] or "", [])) or 1,
        }
        for key in CATEGORY_KEYS:
            feat[f"vio_cat_{key}"] = cats.get(key, 0)
        feat["vio_archetype"] = _archetype(feat)
        out[pid] = feat
    return out


def _archetype(f):
    """§4.1 的四種樣態。實測分布：未被罰 730 / 單園被罰 320 /
    未被罰・負責人他園有前科 66 / 連鎖累犯 96。"""
    punished = f["vio_pun_count"] > 0
    others = f["vio_sibling_pun_count"] > 0 or f["vio_owner_prior_count"] > 0
    if punished and others:
        return "連鎖累犯"
    if punished:
        return "單園被罰"
    if others:
        return "未被罰・負責人他園有前科"
    return "未被罰"


# ---------------------------------------------------------------- 評鑑維度

def evaluation_features(parks, evaluations):
    """§4.2。只取 `評鑑完成日 < CUTOFF` 的列；137 園無紀錄 → missing=True，
    **不是 0 分**，該維度 Coverage = 0。"""
    by_name = collections.defaultdict(list)
    for row in evaluations:
        done = row.get("評鑑完成日")
        if done and done < CUTOFF.isoformat():
            by_name[row["園名"]].append(row)

    out = {}
    for park in parks:
        rows = by_name.get(park["name"], [])
        if not rows:
            out[park["park_id"]] = {
                "eval_base_fail_count": None, "eval_admin_count": None,
                "eval_followup_count": None, "eval_admin_penalty": None,
                "eval_years_since": None, "eval_missing": True,
            }
            continue
        base_fail = sum(1 for r in rows if r["類型"] == "基礎評鑑" and not r["是否全數通過"])
        admin = sum(1 for r in rows if r["類型"] == "行政處分")
        followup = sum(1 for r in rows if r["類型"] == "追蹤評鑑")
        latest = max(r["評鑑完成日"] for r in rows)
        out[park["park_id"]] = {
            "eval_base_fail_count": base_fail,
            "eval_admin_count": admin,
            "eval_followup_count": followup,
            "eval_admin_penalty": admin > 0,
            "eval_years_since": round(_days_before(latest) / 365.25, 2),
            "eval_missing": False,
        }
    return out


# ---------------------------------------------------------------- 輿情維度

def media_features(parks, media_tables):
    """§4.3、§5.5 三層設計。**全部先過 `published_at < CUTOFF`**。

    這是本專案最隱蔽的洩漏點：`docs.json` 有 2,900 篇，其中 1,540 篇在切點之後
    （2026 年就有 917 篇），而 `park_risk.json` / `district_heat.json` 的 as_of
    是 2026-08-23。直接拿來當特徵就是用 2026 年的新聞預測 2025 年的裁罰。
    那兩份現成結果只當前端展示與對照，不進這裡。
    """
    docs, resolution, links, analysis = media_tables
    cutoff_iso = CUTOFF.isoformat()

    def usable(doc_id):
        doc = docs.get(doc_id)
        a = analysis.get(doc_id)
        if not doc or not a:
            return None
        published = (doc.get("published_at") or "")[:10]
        if not published or published >= cutoff_iso:
            return None
        if a.get("is_ad") or not a.get("targets_institution"):
            return None
        if a.get("event_type") in NON_RISK_EVENTS:
            return None
        return doc, a, published

    # ---- L1 園級：A 級連結，同園 × 同事件類型 × 同 ISO 週視為同一起事件
    events = collections.defaultdict(dict)
    for link in links:
        hit = usable(link["doc_id"])
        if not hit:
            continue
        doc, a, published = hit
        key = (a["event_type"], _iso_week(published))
        bucket = events[link["park_id"]].setdefault(key, {
            "event_type": a["event_type"],
            "severity": a["severity"], "credibility": a["credibility"],
            "conf": link.get("confidence", 1.0), "date": published,
            "outlets": set(), "source": doc.get("source"),
        })
        bucket["outlets"].add(doc.get("outlet"))
        bucket["severity"] = max(bucket["severity"], a["severity"])
        bucket["date"] = max(bucket["date"], published)

    park_level = {}
    for pid, buckets in events.items():
        total = 0.0
        for b in buckets.values():
            halflife = MEDIA_HALFLIFE.get(b["event_type"], MEDIA_HALFLIFE_DEFAULT)
            resonance = 1.3 if len(b["outlets"]) >= 3 else 1.0
            total += (b["severity"] * b["credibility"] * b["conf"]
                      * SOURCE_WEIGHT.get(b["source"], 0.7) * resonance
                      * _decay(_days_before(b["date"]), halflife))
        dates = sorted(b["date"] for b in buckets.values())
        recent = [d for d in dates if _days_before(d) <= 30]
        earlier = [d for d in dates if 30 < _days_before(d) <= 120]
        park_level[pid] = {
            "sri": round(100 * (1 - math.exp(-total / SRI_SATURATION)), 2),
            "event_count": len(buckets),
            "top_severity": max(b["severity"] for b in buckets.values()),
            "last_event_date": dates[-1],
            "is_burst": len(recent) >= 2 and not earlier,
        }

    # ---- L2 區級：B 級文件聚到 town，覆蓋全部園所
    town_heat = collections.defaultdict(float)
    town_docs = collections.Counter()
    for row in resolution:
        if row["level"] != "B" or not row.get("town"):
            continue
        hit = usable(row["doc_id"])
        if not hit:
            continue
        _, a, published = hit
        halflife = MEDIA_HALFLIFE.get(a["event_type"], MEDIA_HALFLIFE_DEFAULT)
        town_heat[row["town"]] += a["severity"] * a["credibility"] * _decay(_days_before(published), halflife)
        town_docs[row["town"]] += 1

    active_by_town = collections.Counter(p["town"] for p in parks if p["is_active"] == 1)
    district = []
    for town, park_count in active_by_town.items():
        heat = town_heat.get(town, 0.0)
        district.append({
            "town": town, "heat": round(heat, 6), "doc_count": town_docs.get(town, 0),
            "park_count": park_count,
            "heat_per_park": round(heat / park_count, 6) if park_count else 0.0,
            "has_signal": town in town_heat,
        })
    district.sort(key=lambda d: -d["heat_per_park"])
    for i, row in enumerate(district, 1):
        row["rank"] = i
    by_town = {d["town"]: d for d in district}

    out = {}
    for park in parks:
        l1 = park_level.get(park["park_id"])
        town = by_town.get(park["town"], {})
        out[park["park_id"]] = {
            "media_sri": l1["sri"] if l1 else None,
            "media_event_count": l1["event_count"] if l1 else 0,
            "media_has_signal": bool(l1),
            "media_top_severity": l1["top_severity"] if l1 else None,
            "media_is_burst": l1["is_burst"] if l1 else False,
            "media_last_negative_at": l1["last_event_date"] if l1 else None,
            "media_town_heat_per_park": town.get("heat_per_park", 0.0),
            "media_town_heat_rank": town.get("rank"),
            "media_town_has_signal": town.get("has_signal", False),
        }
    return out, park_level, district


# ---------------------------------------------------------------- 組裝

def build_features(parks, punishments, evaluations, media_tables, owner_priors, finance=None):
    """一列一園。營運維度（B 軌）未交付時只帶 oper_applicable，不帶任何數值欄。"""
    vio = violation_features(parks, punishments, owner_priors)
    ev = evaluation_features(parks, evaluations)
    md, park_level, district = media_features(parks, media_tables)
    finance = finance or {}

    post_cutoff = {p["park_id"] for p in punishments
                   if p["date"] and p["date"] >= CUTOFF.isoformat()}

    rows = []
    for park in parks:
        pid = park["park_id"]
        row = {
            "park_id": pid,
            "institution_type": park["type"],
            "peer_group": park["peer_group"],
            "cutoff": CUTOFF.isoformat(),
            "label": pid in post_cutoff,
            "is_active": park["is_active"],
        }
        row.update(vio[pid])
        row.update(ev[pid])
        row.update(md[pid])
        row["oper_applicable"] = park["peer_group"] in (
            "公立-獨立", "公立-附設", "非營利-有財報")
        row.update(finance.get(pid, {}))          # B 軌交付後才有 oper_* 數值欄
        area = park["size_in"]
        row.update({
            "display_count_approved": park["count_approved"],
            "display_area_per_child": (
                round(area / park["count_approved"], 2)
                if area and park["count_approved"] else None),
            "display_years_since_reg": (
                round(_days_before(park["reg_date"]) / 365.25, 1)
                if park["reg_date"] else None),
            "display_monthly_fee": park["monthly_fee"],
            "display_town": park["town"],
        })
        rows.append(row)
    return rows, park_level, district
