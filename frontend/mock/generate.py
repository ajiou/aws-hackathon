"""從真實資料產生符合 SPEC §8 契約的 mock，讓前端 D0 就能開工。

刻意涵蓋 FRONTEND.md §9.4 列的邊界案例：無座標、無財報、無輿情、
無評鑑、裁罰超過 8 筆、已停辦。

用法: python frontend/mock/generate.py
"""
import json
import os
import re
import random
import hashlib
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
OUT = os.path.dirname(os.path.abspath(__file__))
random.seed(20260912)

CUTOFF = "2025-01-01"
# 跟 out/serving/meta.json 一致。sentiment 是 None：ADR-0001 量測後把輿情移出計分。
# mock 若繼續寫數字，契約上的 null 就永遠不會被測到——這正是上傳真實資料
# 那天全部路由 500 的原因。
WEIGHTS = {
    "公立": {"violation": 0.266, "evaluation": 0.434, "sentiment": None, "operation": 0.30},
    "非營利": {"violation": 0.266, "evaluation": 0.434, "sentiment": None, "operation": 0.30},
    "私立": {"violation": 0.38, "evaluation": 0.62, "sentiment": None, "operation": None},
}
REASON = {
    "VIO_PUNISH_COUNT": "切點前已被裁罰 {n} 次，同類型前 {pct}%",
    "VIO_OWNER_PRIOR": "同一負責人名下另有 {n} 園，其中 {m} 園亦有裁罰紀錄",
    "VIO_ABUSE": "曾有 {n} 次幼兒不當對待裁罰紀錄",
    "EVAL_FAIL": "基礎評鑑 {n} 次未全數指標通過",
    "EVAL_ADMIN": "曾受幼照法第 51 條行政處分 {n} 次",
    "EVAL_MISSING": "查無切點前評鑑紀錄，可能為新立案園所",
    "MEDIA_TOWN_HEAT": "所在行政區近 90 天輿情熱度全市第 {rank}",
    "OPER_PERSONNEL_EXEC": "人事費執行率 {pct}%，同儕中位數 90%",
}


def load(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def hashkey(s):
    return hashlib.sha256(("mock" + str(s)).encode()).hexdigest()[:12] if s else None


# SPEC §5.6.0：只有「市立獨立幼兒園」自己是預算單位，才有獨立決算書。
# 國中／國小／實驗小學附設與分班的財務都併入所屬學校，制度上取不到。
NONPROFIT_WITH_REPORT = {
    "安溪", "山北", "龍埔", "海工", "漢翔", "昌平",
    "北大", "鷺江", "安興", "大觀", "新林", "昌福",
}


def peer_group(p):
    t, title = p["type"], p["title"]
    if t == "私立":
        return "私立"
    if t == "非營利":
        has = any(k in title for k in NONPROFIT_WITH_REPORT)
        return "非營利-有財報" if has else "非營利-無財報"
    standalone = (re.fullmatch(r"新北市立[一-鿿]+幼兒園", title)
                  and "附設" not in title and "分班" not in title)
    return "公立-獨立" if standalone else "公立-附設"


geo = load("preschools.json")
base = {f["properties"]["id"]: (f["properties"], f.get("geometry"))
        for f in geo["features"] if f["properties"].get("city") == "新北市"}
feat = {x["id"]: x for x in load("園所裁罰特徵_cutoff20250101.json")}
fee_ids = {r["id"] for v in load("新北市公立與非營利幼兒園_115學年度收費明細.json").values() for r in v}

name2id = {p["title"]: i for i, (p, _) in base.items()}
ev = collections.defaultdict(lambda: {"bf": 0, "fu": 0, "ad": 0, "n": 0})
for r in load("評鑑結果.json"):
    pid, d = name2id.get(r["園名"]), r["評鑑完成日"]
    if not pid or not d or d >= CUTOFF:
        continue
    e = ev[pid]
    e["n"] += 1
    if r["類型"] == "基礎評鑑" and not r["是否全數通過"]:
        e["bf"] += 1
    if r["類型"] == "追蹤評鑑":
        e["fu"] += 1
    if r["類型"] == "行政處分":
        e["ad"] += 1

records = []
for pid, (p, gm) in base.items():
    f = feat.get(pid, {})
    e = ev.get(pid, {"bf": 0, "fu": 0, "ad": 0, "n": 0})
    pg = peer_group(p)
    pun = f.get("園_處分次數", 0)
    abuse = f.get("園_不當對待次數", 0)
    owner_prior = len(f.get("被罰負責人", []))
    town_rank = (abs(hash(p["town"])) % 29) + 1

    vio = min(100, pun * 12 + abuse * 20 + owner_prior * 14)
    eva = min(100, e["bf"] * 22 + e["ad"] * 30 + e["fu"] * 12)
    med = round(max(0, 60 - town_rank * 1.8), 1)
    has_oper = WEIGHTS[p["type"]]["operation"] is not None and pg != "非營利-無財報"
    oper = round(random.uniform(10, 95), 1) if has_oper else None

    w = WEIGHTS[p["type"]]
    # 輿情權重為 None = 該維度不進分數（ADR-0001）。跟營運維度一樣，
    # 權重與覆蓋率都算 0，而不是拿 0 分去拉低均值。
    has_media = w["sentiment"] is not None
    # 園級（L1）輿情訊號。真實資料只有 14 / 1,178 園有，note 也因此分兩種寫法
    # （見 model/score.py 的 SENTIMENT_L1_NOTE）。mock 若一律 False，前端那條
    # 分支就永遠沒被畫過——契約凍結後靠 mock 開發的東西一律要在 mock 出現。
    has_l1_media = abs(hash(("l1", p["id"]))) % 84 == 0
    # 第三種園：有明文點名的報導，但全部在切點之後。真實資料有 22 園，
    # 2026 年的虐童案全落在這一類——維度說明必須跟「完全沒有報導」分開，
    # 否則會在它自己的頁面上寫「本園無明文點名的報導」，而下方就列著十幾則。
    # mock 若沒有這一類，那條分支永遠不會被畫到。
    has_after_media = not has_l1_media and abs(hash(("after", p["id"]))) % 55 == 0
    parts = [("violation", vio, w["violation"], 1.0),
             ("evaluation", eva, w["evaluation"], 0.0 if e["n"] == 0 else 1.0),
             ("sentiment", med, w["sentiment"] or 0.0, 1.0 if has_media else 0.0),
             ("operation", oper, w["operation"] or 0.0, 1.0 if has_oper else 0.0)]
    num = sum(wt * cov * (sc or 0) for _, sc, wt, cov in parts)
    den = sum(wt * cov for _, _, wt, cov in parts) or 1.0
    total_w = sum(wt for _, _, wt, _ in parts) or 1.0
    raw = num / den
    coverage = round(den / total_w, 2)

    cand = []
    if pun >= 2:
        cand.append(("VIO_PUNISH_COUNT", "violation", {"n": pun, "pct": max(1, 30 - pun * 3)}, 0.40))
    if owner_prior:
        cand.append(("VIO_OWNER_PRIOR", "violation", {"n": owner_prior + 2, "m": owner_prior}, 0.24))
    if abuse:
        cand.append(("VIO_ABUSE", "violation", {"n": abuse}, 0.30))
    if e["bf"]:
        cand.append(("EVAL_FAIL", "evaluation", {"n": e["bf"]}, 0.26))
    if e["ad"]:
        cand.append(("EVAL_ADMIN", "evaluation", {"n": e["ad"]}, 0.28))
    if e["n"] == 0:
        cand.append(("EVAL_MISSING", "evaluation", {}, 0.08))
    if town_rank <= 5:
        cand.append(("MEDIA_TOWN_HEAT", "sentiment", {"rank": town_rank}, 0.12))
    if has_oper and oper and oper > 70:
        cand.append(("OPER_PERSONNEL_EXEC", "operation", {"pct": 64}, 0.18))

    seen = collections.Counter()
    picked = []
    for code, dim, kw, wgt in sorted(cand, key=lambda r: -r[3]):
        if seen[dim] >= 2 or len(picked) >= 3:
            continue
        seen[dim] += 1
        picked.append({"code": code, "label": REASON[code].format(**kw), "weight": wgt,
                       "dimension": dim, "validated": dim != "operation"})

    coords = (gm or {}).get("coordinates") or [None, None]
    cap = str(p.get("count_approved", ""))
    records.append({
        # SPEC §8.2：type 與 institution_type 兩個名字都在契約上且必須一致。
        "park_id": pid, "name": p["title"], "institution_type": p["type"], "type": p["type"],
        "peer_group": pg, "town": p["town"], "address": p["address"], "tel": p["tel"],
        "lon": coords[0], "lat": coords[1], "is_active": p["is_active"],
        "count_approved": int(cap) if cap.isdigit() else None,
        "owner_key": hashkey(p.get("owner")),
        "_raw": raw, "_coverage": coverage,
        "dimensions": {
            "violation": {"applicable": True, "score": vio, "coverage": 1.0,
                          "weight": w["violation"], "validated": True, "note": None},
            # applicable=false 時 weight 也必須是 null，不是原本的權重。
            # 前端拿 weight 畫「這個維度占幾成」的堆疊條，留著數字會畫出一段
            # 根本沒計分的面積。Dimension.check_applicability 會擋。
            "evaluation": {"applicable": e["n"] > 0, "score": eva if e["n"] else None,
                           "coverage": 1.0 if e["n"] else 0.0,
                           "weight": w["evaluation"] if e["n"] else None,
                           "validated": True,
                           "note": None if e["n"] else "查無切點前之評鑑紀錄，可能為新立案園所"},
            "sentiment": {"applicable": has_media, "score": med if has_media else None,
                          "coverage": 1.0 if has_l1_media else 0.4,
                          "weight": w["sentiment"], "validated": True,
                          # 三種園三句話，跟 model/score.py 的分支一一對應。
                          "note": None if has_media else (
                              "本園有切點前明文點名的報導，但全市僅 14 園有園級輿情訊號，"
                              "樣本太小無法驗證預測力，依 ADR-0001 暫不計入風險分數；"
                              "報導明細仍列於本頁下方" if has_l1_media else
                              f"本園有 2 則明文點名的報導，但全部落在資料切點（{CUTOFF}）之後。"
                              "用切點後的事實去預測切點後的裁罰是資料洩漏，因此不計入風險分數"
                              "——這不代表這些報導不重要，請直接看本頁下方的報導明細"
                              if has_after_media else
                              "本園無明文點名的報導，僅有所在行政區的輿情熱度；"
                              "區級熱度實測無鑑別力（Precision@50 8.0%，低於隨機抽查的 10.9%），"
                              "依 ADR-0001 不計入風險分數；輿情資料仍供本頁與行政區熱力圖檢視")},
            "operation": {"applicable": has_oper, "score": oper,
                          "coverage": 1.0 if has_oper else 0.0,
                          "weight": w["operation"] if has_oper else None,
                          "validated": False,
                          "note": None if has_oper else (
                              "私立幼兒園依法不需公告財務報告" if p["type"] == "私立"
                              else "查無本園財務報告，營運維度不適用")},
        },
        "reasons": picked,
        "finance_flags": ([{"code": "OPER_PERSONNEL_EXEC",
                            "label": "人事費執行率 64%，同儕中位數 90%",
                            "severity": 3, "year": 112, "validated": False}]
                          if has_oper and oper and oper > 80 else []),
        "media": {"sri": round(med, 2) if has_l1_media else 0.0,
                  "has_signal": has_l1_media,
                  "town_heat_per_park": round(med / 100, 3),
                  "town_heat_rank": town_rank,
                  "last_negative_at": "2024-08-27" if has_l1_media else None},
        # 證據鏈（輿情分頁與詳情頁第 5 個分頁）。mock 用的是真實園名，所以
        # 這裡的「報導」一律寫明是示範資料、來源寫「示範來源」、不給連結——
        # 掛真實媒體名與像真的標題在真實園所底下，就算只在 demo 裡也是抹黑。
        # 欄位形狀與 out/serving/media_coverage.json 相同，前端才測得到同一條路。
        "media_coverage": ([
            {"date": d, "outlet": "示範來源", "title": t, "url": None,
             "event_type": ev, "severity": sev, "stance": st,
             "is_after_cutoff": d >= CUTOFF}
            for d, ev, sev, st, t in [
                ("2026-04-11", "不當管教", 5, "家長指控",
                 "〔示範資料〕家長投訴不當管教，非真實報導"),
                ("2026-01-22", "食安衛生", 3, "官方回應",
                 "〔示範資料〕教育局回應午餐衛生查核，非真實報導"),
                ("2024-08-27", "超收", 2, "媒體報導",
                 "〔示範資料〕招生人數查核，非真實報導"),
            ] if (has_l1_media or d >= CUTOFF)]
            if (has_l1_media or has_after_media) else []),
        "timeline": [
            {"date": r["日期"], "category": "超收" if "第8條" in r["條文"] else "師生比",
             "law": r["條文"][:12],
             "fine": 60000 if "60,000" in r.get("處分", "") else 6000,
             "penalty_raw": r.get("處分", ""), "is_after_cutoff": r["日期"] >= CUTOFF}
            for r in f.get("裁罰紀錄", [])],
        "has_fee": pid in fee_ids,
    })

# 名次與分級：全市合併排序（僅 is_active）；分數為同儕群內百分位
active = sorted([r for r in records if r["is_active"] == 1], key=lambda r: -r["_raw"])
for i, r in enumerate(active, 1):
    r["rank"] = i
    r["tier"] = "高" if i <= 50 else ("中" if i <= 200 else "低")
by_pg = collections.defaultdict(list)
for r in active:
    by_pg[r["peer_group"]].append(r)
for rs in by_pg.values():
    rs.sort(key=lambda r: r["_raw"])
    n = len(rs)
    for i, r in enumerate(rs):
        r["score"] = round(100 * i / (n - 1), 1) if n > 1 else 50.0
for r in records:
    if r["is_active"] != 1:
        # 停辦園所的分數是 null，不是 0。score 0 在介面上讀起來是「風險最低」，
        # 但實情是「根本沒參與排名」。SPEC §2：37 園不進排名不進分級。
        r["rank"], r["tier"], r["score"] = None, None, None


def strip(r):
    o = {k: v for k, v in r.items() if not k.startswith("_") and k not in ("score", "rank", "tier")}
    o["risk"] = {"score": r["score"], "score_basis": "同儕群內百分位", "rank": r["rank"],
                 "rank_basis": "全市合併", "tier": r["tier"], "raw": round(r["_raw"], 4),
                 "coverage": r["_coverage"], "model_version": "risk-v2"}
    return o


full = [strip(r) for r in records]
lst = sorted([r for r in full if r["is_active"] == 1], key=lambda r: r["risk"]["rank"])


def write(name, obj):
    path = os.path.join(OUT, name)
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  {name:22s} {os.path.getsize(path):>9,d} bytes")


print("寫出 mock：")
write("meta.json", {
    "version": "1.0.0-mock", "generated_at": "2026-09-12T06:00:00Z", "cutoff": CUTOFF,
    "population": len(active), "weights": WEIGHTS,
    "peer_groups": {k: {"n": len(v)} for k, v in sorted(by_pg.items())},
    "score_basis": "同儕群內百分位（ECDF by peer_group）",
    "rank_basis": "全市合併排序（R_raw）",
    "unvalidated_dimensions": ["operation"],
    "tiers": {"high": [1, 50], "medium": [51, 200], "low": [201, len(active)]},
    "data_freshness": {"punishments": "2026-08-21", "media": "2026-08-21",
                       "evaluation": "2025-11-28", "fees": "115學年度"},
    "model": {"name": "risk-v2", "precision_at_50": 0.28, "baseline": 0.106, "lift": 2.64},
})
write("parks.json", {"total": len(lst), "page": 1, "size": 50, "items": [
    {"park_id": r["park_id"], "name": r["name"], "institution_type": r["institution_type"],
     "type": r["institution_type"],
     "town": r["town"], "lon": r["lon"], "lat": r["lat"], "is_active": r["is_active"],
     "risk": r["risk"], "pun_count": len(r["timeline"]),
     "has_finance_flag": bool(r["finance_flags"]),
     "has_media_signal": r["media"]["has_signal"],
     "reasons": r["reasons"]}
    for r in lst[:50]]})
write("scores.json", {"generated_at": "2026-09-12T06:00:00Z", "items": full})
write("risk-top.json", {"k": 50, "items": lst[:50]})
write("park-detail.json", {r["park_id"]: r for r in
                           [lst[0], lst[120], next(x for x in full if x["is_active"] == 0)]})
write("map.json", {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
     "properties": {"park_id": r["park_id"], "name": r["name"], "tier": r["risk"]["tier"],
                    "risk_score": r["risk"]["score"], "pun_count": len(r["timeline"]),
                    "has_abuse": any(t["category"] == "不當管教" for t in r["timeline"])}}
    for r in lst if r["lon"]]})

towns = collections.defaultdict(lambda: {"park_count": 0, "high": 0, "medium": 0, "pun": 0})
for r in lst:
    t = towns[r["town"]]
    t["park_count"] += 1
    t["pun"] += len(r["timeline"])
    if r["risk"]["tier"] == "高":
        t["high"] += 1
    if r["risk"]["tier"] == "中":
        t["medium"] += 1
write("districts.json", {"as_of": "2026-09-12", "items": [
    {"town": k, "park_count": v["park_count"], "high_risk_count": v["high"],
     "medium_risk_count": v["medium"], "high_risk_ratio": round(v["high"] / v["park_count"], 4),
     "media_heat": round((abs(hash(k)) % 500) / 100, 2),
     "media_heat_per_park": round((abs(hash(k)) % 500) / 100 / v["park_count"], 4),
     "media_rank": (abs(hash(k)) % 29) + 1, "pun_count_before_cutoff": v["pun"]}
    for k, v in sorted(towns.items(), key=lambda x: -x[1]["high"] / x[1]["park_count"])]})

write("curve.json", {
    "population": len(active), "positives": 128, "baseline": 0.106,
    "points": [{"k": k,
                "model": round(k * 0.28) if k <= 50 else round(k * 0.16),
                "eval": round(k * 0.24) if k <= 50 else round(k * 0.14),
                "punish": round(k * 0.24) if k <= 50 else round(k * 0.14),
                "random": round(k * 0.106, 2), "perfect": min(k, 128)}
               for k in [10, 20, 30, 50, 75, 100, 150, 200, 250, 300]],
    "summary": {"precision_at_50": {"model": 0.28, "eval": 0.24, "punish": 0.24, "random": 0.106},
                "stratified": {
                    "私立": {"n": 868, "baseline": 0.120, "p_at_20": 0.450,
                             "p_at_50": 0.280, "lift_50": 2.34},
                    "非營利": {"n": 50, "baseline": 0.140, "p_at_10": 0.200, "lift_10": 1.43},
                    "公立": {"n": 294, "baseline": 0.058, "p_at_20": 0.050, "lift_20": 0.86}}}})

def worklist_reasons(row):
    """Complete the mock worklist from existing signals; do not invent findings."""
    labels = [x["label"] for x in row["reasons"]][:3]
    if len(labels) < 3:
        labels.append(f"所在行政區近 90 天輿情熱度全市第 {row['media']['town_heat_rank']}")
    assert len(labels) == 3
    return labels


write("worklist.json", {
    "week": "2026-W37", "generated_at": "2026-09-12T06:00:00Z",
    "model": {"name": "risk-v2", "precision_at_50": 0.28, "baseline": 0.106},
    "items": [{"seq": i, "park_id": r["park_id"], "name": r["name"], "town": r["town"],
               "institution_type": r["institution_type"], "type": r["institution_type"],
               "count_approved": r["count_approved"], "address": r["address"], "tel": r["tel"],
               "risk": r["risk"], "reasons": worklist_reasons(r),
               "actions": [{"focus": "師生比", "why": "歷史違規集中於第 16 條第 4 項"},
                           {"focus": f"實際招收人數 vs 核定 {r['count_approved']} 人",
                            "why": "歷史有超收紀錄"}],
               "attachments": {"punishment_count": len(r["timeline"]), "evaluation_count": 4}}
              for i, r in enumerate(lst[:50], 1)]})

write("briefs.json", {r["park_id"]: {
    "park_id": r["park_id"], "source": "template", "summary": "",
    "reasons": [x["label"] for x in r["reasons"]],
    "actions": ([{"focus": "師生比", "why": "歷史違規集中於第 16 條第 4 項"},
                 {"focus": f"實際招收人數 vs 核定 {r['count_approved']} 人",
                  "why": "歷史有超收紀錄"}] if r in lst[:50] else []),
    "generated_at": "2026-09-12T06:00:00Z"
} for r in full})

print(f"\n母體 {len(active)}｜高風險 50｜同儕群 "
      + "、".join(f"{k} {len(v)}" for k, v in sorted(by_pg.items())))
print("邊界案例："
      f"無座標 {sum(1 for r in full if not r['lon'])}"
      f"｜停辦 {sum(1 for r in full if r['is_active'] == 0)}"
      f"｜無評鑑 {sum(1 for r in full if not r['dimensions']['evaluation']['applicable'])}"
      f"｜無營運 {sum(1 for r in full if not r['dimensions']['operation']['applicable'])}"
      f"｜裁罰>8筆 {sum(1 for r in full if len(r['timeline']) > 8)}")
