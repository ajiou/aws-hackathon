"""curated → serving。SPEC §3.3、§8 契約。

    python -m model.score --in ./out/curated --model ./out/model --out ./out/serving

產出後端會讀的六份：scores / districts / map / curve / worklist / meta。
`parks`、`risk/top`、`park-detail` 由 backend 從 scores 現算，不另存檔。

**欄位名以 `frontend/mock/*.json` 為準**——前端已照它開發，契約凍結（§8）。
"""
import argparse
import collections
import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from etl.constants import CUTOFF, TIERS, WEIGHTS
from .reasons import build_reasons
from .scoring import assign_tiers, score_all

MODEL_VERSION = "risk-v2"
DIM_NOTE = {
    ("sentiment", None): "區級輿情熱度實測無鑑別力（Precision@50 8.0%，低於隨機抽查的 10.9%），"
                         "依 ADR-0001 不計入風險分數；輿情資料仍供本頁與行政區熱力圖檢視",
    ("operation", "私立"): "私立幼兒園依法不需公告財務報告",
    ("operation", "非營利-無財報"): "本園未公告財務報告，營運維度不計分",
    ("operation", "公立-附設"): "本園為附設幼兒園，財務併入所屬學校，營運分數僅依收費明細計算",
}


def load(indir, name, default=None):
    path = Path(indir) / f"{name}.json"
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dimension_block(dim, score, coverage, weight, peer_group, itype):
    """§3.3 的 dimensions 規則。

    `applicable = false` 時 `score` **必須是 null，不得是 0**——0 分等於懲罰守法者。
    營運維度的 `validated` 永遠 false（§5.6.8，有財務資料的 33 園中被罰者僅個位數）。
    """
    # 「不適用」指這類園所本來就不該有這個維度（私立沒有財報）。
    # 輿情是另一回事——資料有、也照常展示，只是實測無鑑別力所以不計分，
    # 因此 applicable 維持 true，由 note 說明為什麼沒有分數（ADR-0001）。
    applicable = weight is not None
    return {
        "applicable": applicable,
        "score": round(score, 1) if (applicable and score is not None) else None,
        "coverage": round(coverage, 2),
        "weight": weight if applicable else None,
        "validated": dim != "operation",
        "note": (DIM_NOTE.get((dim, peer_group)) or DIM_NOTE.get((dim, itype))
                 or DIM_NOTE.get((dim, None))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="./out/curated")
    ap.add_argument("--model", dest="modeldir", default="./out/model")
    ap.add_argument("--out", dest="outdir", default="./out/serving")
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    features = load(args.indir, "features")
    parks = {p["park_id"]: p for p in load(args.indir, "parks")}
    punishments = load(args.indir, "punishments")
    media = load(args.indir, "media")
    fees = {r["park_id"] for r in load(args.indir, "fees", [])}
    finance = {r["park_id"]: r for r in load(args.indir, "finance", [])}
    metrics = load(args.modeldir, "metrics", {})
    meta_in = load(args.indir, "meta", {})

    scored = assign_tiers(score_all(features, WEIGHTS, finance), TIERS)
    by_id = {s["park_id"]: s for s in scored}
    feat_by_id = {f["park_id"]: f for f in features}

    timeline = collections.defaultdict(list)
    for row in sorted(punishments, key=lambda r: r["date"]):
        timeline[row["park_id"]].append({
            "date": row["date"], "category": row["category"], "law": row["law"],
            "penalty_raw": row["penalty_raw"], "is_after_cutoff": row["is_after_cutoff"],
        })

    items = []
    for f in features:
        pid = f["park_id"]
        s, park = by_id[pid], parks[pid]
        weights = WEIGHTS[f["institution_type"]]
        fin = finance.get(pid, {})
        items.append({
            "park_id": pid, "name": park["name"],
            "institution_type": f["institution_type"], "peer_group": f["peer_group"],
            "town": park["town"], "address": park["address"], "tel": park["tel"],
            "lon": park["lon"], "lat": park["lat"], "is_active": park["is_active"],
            "count_approved": park["count_approved"], "owner_key": park["owner_key"],
            "dimensions": {
                dim: dimension_block(dim, *s["dimensions"][dim], weights.get(dim),
                                     f["peer_group"], f["institution_type"])
                for dim in s["dimensions"]
            },
            "reasons": build_reasons(f, s["pcts"], weights, finance),
            "finance_flags": fin.get("flags", []),
            "media": {
                "sri": f.get("media_sri") or 0.0,
                "has_signal": f.get("media_has_signal", False),
                "town_heat_per_park": f.get("media_town_heat_per_park"),
                "town_heat_rank": f.get("media_town_heat_rank"),
                "last_negative_at": f.get("media_last_negative_at"),
            },
            "timeline": timeline.get(pid, []),
            "has_fee": pid in fees,
            "risk": {
                "score": s["risk_score"], "score_basis": "同儕群內百分位",
                "rank": s["rank"], "rank_basis": "全市合併", "tier": s["tier"],
                "raw": round(s["raw"], 4), "coverage": s["coverage"],
                "model_version": MODEL_VERSION,
            },
        })

    def dump(name, payload):
        with open(out / f"{name}.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)

    # ---- 驗收：§14.1 的 reasons 規則，在寫檔前擋下來
    for it in items:
        assert len(it["reasons"]) <= 3, f"{it['park_id']} reasons 超過 3 條"
        per_dim = collections.Counter(r["dimension"] for r in it["reasons"])
        assert max(per_dim.values(), default=0) <= 2, f"{it['park_id']} 同一維度超過 2 條"
        op = it["dimensions"]["operation"]
        assert not (op["applicable"] is False and op["score"] is not None), \
            "applicable=false 時 score 必須是 null"
        assert op["validated"] is False, "營運維度的 validated 必須永遠是 false"
        assert it["dimensions"]["sentiment"]["score"] is None, \
            "輿情不計分（ADR-0001），score 必須是 null"
        assert not [r for r in it["reasons"] if r["dimension"] == "sentiment"], \
            "輿情不計分時不得產生輿情原因碼"
    dump("scores", {"generated_at": now, "items": items})

    # ---- districts
    active = [it for it in items if it["is_active"] == 1]
    heat = {d["town"]: d for d in media["district_level"]}
    pun_pre = collections.Counter(r["park_id"] for r in punishments if not r["is_after_cutoff"])
    districts = []
    for town, group in itertools.groupby(
            sorted(active, key=lambda i: i["town"]), key=lambda i: i["town"]):
        group = list(group)
        h = heat.get(town, {})
        high = sum(1 for i in group if i["risk"]["tier"] == "高")
        districts.append({
            "town": town, "park_count": len(group), "high_risk_count": high,
            "medium_risk_count": sum(1 for i in group if i["risk"]["tier"] == "中"),
            "high_risk_ratio": round(high / len(group), 4),
            "media_heat": round(h.get("heat", 0.0), 4),
            "media_heat_per_park": round(h.get("heat_per_park", 0.0), 6),
            "media_rank": h.get("rank"),
            "media_has_signal": h.get("has_signal", False),
            "pun_count_before_cutoff": sum(pun_pre.get(i["park_id"], 0) for i in group),
            "pun_park_count": sum(1 for i in group if pun_pre.get(i["park_id"])),
        })
    assert len(districts) == 29, f"行政區 {len(districts)} != 29"
    dump("districts", {"as_of": now[:10], "items": districts})

    # ---- map（GeoJSON，前端 MapLibre 直接吃）
    dump("map", {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [i["lon"], i["lat"]]},
         "properties": {"park_id": i["park_id"], "name": i["name"], "town": i["town"],
                        "tier": i["risk"]["tier"], "risk_score": i["risk"]["score"],
                        "pun_count": feat_by_id[i["park_id"]]["vio_pun_count"],
                        "has_abuse": bool(feat_by_id[i["park_id"]]["vio_abuse_count"])}}
        for i in active]})

    # ---- curve（backtest 已算好，原樣搬過來）
    curve = load(args.modeldir, "curve")
    if curve:
        shutil.copyfile(Path(args.modeldir) / "curve.json", out / "curve.json")

    # ---- worklist：本週 50 個稽查名額，主線產出（§8.9）
    top = sorted(active, key=lambda i: i["risk"]["rank"])[:50]
    iso = datetime.now(timezone.utc).isocalendar()
    dump("worklist", {
        "week": f"{iso[0]}-W{iso[1]:02d}", "generated_at": now, "model": MODEL_VERSION,
        "items": [{
            "seq": n, "park_id": i["park_id"], "name": i["name"], "town": i["town"],
            "institution_type": i["institution_type"],
            "count_approved": i["count_approved"], "address": i["address"], "tel": i["tel"],
            "risk": i["risk"], "reasons": [r["label"] for r in i["reasons"]],
            "check_items": _check_items(feat_by_id[i["park_id"]]),
        } for n, i in enumerate(top, 1)],
    })
    # 派工單不得出現自然人姓名（§14.2）
    blob = json.dumps(load(args.outdir, "worklist"), ensure_ascii=False)
    for banned in ("負責人：", "行為人：", "姓名"):
        assert banned not in blob, f"派工單含個資欄位 {banned}"

    dump("meta", {
        "version": f"1.0.0-{datetime.now(timezone.utc):%Y%m%d}",
        "generated_at": now, "cutoff": CUTOFF.isoformat(),
        "population": len(active), "weights": WEIGHTS,
        "peer_groups": {k: {"n": v} for k, v in meta_in.get("peer_groups", {}).items()},
        "score_basis": "同儕群內百分位（ECDF by peer_group）",
        "rank_basis": "全市合併排序（R_raw）",
        "unvalidated_dimensions": ["operation"],
        "tiers": {"high": [1, 50], "medium": [51, 200], "low": [201, len(active)]},
        "data_freshness": {
            "punishments": max(r["date"] for r in punishments),
            "media": media.get("as_of"), "fees": "115學年度",
        },
        "model": {
            "name": MODEL_VERSION,
            "precision_at_50": metrics.get("orderings", {}).get("model", {}).get("p_at_50"),
            "baseline": metrics.get("baseline"),
            "lift": metrics.get("orderings", {}).get("model", {}).get("lift_at_50"),
            "gate_passed": metrics.get("passed"),
        },
    })
    print(f"→ {out}　scores {len(items)} 筆（{len(active)} 在營運）、"
          f"districts 29、worklist 50")


def _check_items(f):
    """派工單的查核建議：依該園歷史違規類別給，不是通用清單。"""
    cats = sorted(((k[len("vio_cat_"):], v) for k, v in f.items()
                   if k.startswith("vio_cat_") and v), key=lambda kv: -kv[1])
    items = [f"{name}（歷史 {n} 次）" for name, n in cats[:3]]
    if f.get("eval_base_fail_count"):
        items.append("基礎評鑑未通過項目之改善情形")
    if f.get("eval_missing"):
        items.append("新立案園所首次訪視")
    return items or ["例行查核"]


if __name__ == "__main__":
    main()
