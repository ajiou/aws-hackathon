"""curated → serving。SPEC §3.3、§8 契約。

    python -m model.score --in ./out/curated --model ./out/model --out ./out/serving

產出後端會讀的十份：scores / districts / map / curve / worklist / meta，
加上園所明細四份 evaluations / fees / finance / media_coverage。
`parks`、`risk/top`、`park-detail` 由 backend 從 scores 現算，不另存檔；
明細四份由 store.related() 依 park_id 查，沒有檔案就是空陣列。

明細四份原本只寫到 curated 就停住，serving 沒有，於是前端三個分頁對
**全部 1,178 園**都顯示「（無明細）」——包括「基礎評鑑 2 次未全數指標通過」
這種已經寫在風險原因裡、卻在頁面上查無佐證的宣稱。

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
    # 權重表的 key 是設立別（公立／非營利／私立），但營運維度的適用性取決於
    # 同儕群：非營利-有財報 與 非營利-無財報 共用「非營利」的 30% 權重，
    # 只看權重會把無財報那 41 園判成 applicable=true、score=null，
    # 落進 FRONTEND §4.2 沒有定義的狀態。SPEC §5.6.0 明訂它是不適用。
    if dim == "operation" and peer_group in ("私立", "非營利-無財報"):
        applicable = False
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
    fee_rows = load(args.indir, "fees", [])
    fees = {r["park_id"] for r in fee_rows}
    finance = {r["park_id"]: r for r in load(args.indir, "finance", [])}
    evaluations = load(args.indir, "evaluations", [])
    media_coverage = load(args.indir, "media_coverage", [])
    metrics = load(args.modeldir, "metrics", {})
    meta_in = load(args.indir, "meta", {})

    # 派工單跟 meta 共用同一個 model 區塊，兩邊分開寫就會漂移。
    model_block = {
        "name": MODEL_VERSION,
        "precision_at_50": metrics.get("orderings", {}).get("model", {}).get("p_at_50"),
        "baseline": metrics.get("baseline"),
        "lift": metrics.get("orderings", {}).get("model", {}).get("lift_at_50"),
        "gate_passed": metrics.get("passed"),
    }

    scored = assign_tiers(score_all(features, WEIGHTS, finance), TIERS)
    by_id = {s["park_id"]: s for s in scored}
    feat_by_id = {f["park_id"]: f for f in features}

    timeline = collections.defaultdict(list)
    for row in sorted(punishments, key=lambda r: r["date"]):
        timeline[row["park_id"]].append({
            "date": row["date"], "category": row["category"], "law": row["law"],
            "penalty_raw": row["penalty_raw"], "is_after_cutoff": row["is_after_cutoff"],
            # fine 可以是 None（停止招生、減招、停辦沒有金額）。
            # 不可以被寫成 0，見 etl/sources.py parse_fine。
            "fine": row.get("fine"),
        })

    items = []
    for f in features:
        pid = f["park_id"]
        s, park = by_id[pid], parks[pid]
        weights = WEIGHTS[f["institution_type"]]
        fin = finance.get(pid, {})
        items.append({
            "park_id": pid, "name": park["name"],
            "institution_type": f["institution_type"],
            # SPEC §8.2 兩個名字都在契約上：列表用 type，詳情用 institution_type。
            # 兩者必須一致，backend Park.check_park 會擋。
            "type": f["institution_type"],
            "peer_group": f["peer_group"],
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
                # score 就是四維度加權總分（= raw 取一位小數），不再是百分位。
                # raw 仍照送，供需要完整精度的下游使用。
                "score": s["risk_score"], "score_basis": "四維度加權總分",
                "rank": s["rank"], "rank_basis": "全市合併",
                "tier": s["tier"], "tier_basis": "設立別內分佈",
                "peer_rank": s["peer_rank"], "peer_n": s["peer_n"],
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

    # ---- 園所明細三份：評鑑 / 收費 / 財報
    # 這三份原本只寫到 curated 就停住，serving 沒有，backend 的
    # store.related() 因此對每一園都回 []，前端三個分頁全部空白——
    # 包括「基礎評鑑 2 次未全數指標通過」這種**已經寫在風險原因裡**、
    # 卻在頁面上查無佐證的宣稱。欄位名以 frontend/src/api/types.ts 的
    # parkSchema 為準（year / kind / result；school_year + items）。
    dump("evaluations", {"items": [
        {"park_id": r["park_id"], "year": r["評鑑學年度"], "kind": r["類型"],
         "result": r["評鑑結果"], "date": r["評鑑完成日"]}
        # 同一園內由新到舊，讓處分升級鏈由近而遠讀下來
        for r in sorted(sorted(evaluations, key=lambda r: r["評鑑完成日"], reverse=True),
                        key=lambda r: r["park_id"])
    ]})

    # 收費的外層（school_year + items）已符合契約，只有 items 內的欄位名是中文。
    # 「小計」才是該學期實付總額，「單價」是月費，兩者差一個月數倍率。
    fee_terms = {"term1_full": "上學期全日班小計", "term2_full": "下學期全日班小計",
                 "term1_half": "上學期半日班小計", "term2_half": "下學期半日班小計"}
    dump("fees", {"items": [
        {"park_id": r["park_id"], "school_year": r["school_year"],
         "items": [{"age": i["適用年齡（歲）"], "item": i["收費項目"],
                    "period": i["收費期間"],
                    **{k: i.get(v) for k, v in fee_terms.items()}}
                   for i in r["items"]]}
        for r in fee_rows
    ]})

    # 財報：school_year 可能是 null（公立-附設併入學校決算，沒有自己的年度），
    # 照實送 null，不省略欄位——省略會讓前端分不出「沒有年度」與「忘了給」，
    # 而且曾因此讓 269 園的詳情頁整頁變成「資料載入失敗」。
    # validated 必須永遠 false（§5.6.8），backend store.finance() 會再擋一次。
    dump("finance", {"items": list(finance.values())})

    # 輿情明細。**刻意含切點之後的報導**，而且只有這一份是這樣——
    # 特徵那條路仍由 assert_no_leakage 守著切點，兩者不共用資料。
    dump("media_coverage", {"items": media_coverage})

    # ---- districts
    active = [it for it in items if it["is_active"] == 1]
    # 分級改成各設立別各自切之後，全市「高風險」總數不再剛好等於 50，
    # 把實際切出來的數量寫進 meta，免得有人拿舊的 50 去對帳。
    tier_counts = {
        itype: dict(collections.Counter(
            it["risk"]["tier"] for it in active if it["institution_type"] == itype))
        for itype in sorted({it["institution_type"] for it in active})
    }
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

    # 該園每一類違規最常被引的法條，給 actions 的 why 引用用。
    law_counts = collections.Counter(
        (r["park_id"], r["category"], r["law"]) for r in punishments
        if not r["is_after_cutoff"] and r["law"]
    )
    law_by_cat = {}
    for (pid, cat, law), n in law_counts.most_common():
        law_by_cat.setdefault((pid, cat), law)

    # 評鑑檔沒有 park_id，是用園名 join 的（build_curated 實測 1,101/1,101 全中）。
    by_name = {p["name"]: pid for pid, p in parks.items()}
    eval_counts = collections.Counter(
        by_name[r["園名"]] for r in evaluations if r.get("園名") in by_name)
    pun_counts = collections.Counter(r["park_id"] for r in punishments)

    dump("worklist", {
        "week": f"{iso[0]}-W{iso[1]:02d}", "generated_at": now,
        # SPEC §8.9 的 model 是整個 ModelMetrics，不是版本字串。
        # 派工單要能自己交代「這份名單的命中率是多少」，列印出來時不能
        # 另外再呼一次 /meta。
        "model": model_block,
        "items": [{
            "seq": n, "park_id": i["park_id"], "name": i["name"], "town": i["town"],
            "institution_type": i["institution_type"], "type": i["institution_type"],
            "count_approved": i["count_approved"], "address": i["address"], "tel": i["tel"],
            "risk": i["risk"], "reasons": [r["label"] for r in i["reasons"]],
            "actions": _actions(feat_by_id[i["park_id"]], i, law_by_cat),
            "attachments": {
                "punishment_count": pun_counts.get(i["park_id"], 0),
                "evaluation_count": eval_counts.get(i["park_id"]) or None,
            },
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
        "score_basis": "四維度加權總分（R_raw）",
        "rank_basis": "全市合併排序（R_raw）",
        "tier_basis": "設立別內 R_raw 分佈，切點比例沿用全市 50 / 200 名",
        "unvalidated_dimensions": ["operation"],
        # 名次仍是全市合併，所以這裡照舊記全市切點；實際標籤是各設立別
        # 按同樣比例各自切（見 model.scoring.assign_tiers）。
        "tiers": {"high": [1, 50], "medium": [51, 200], "low": [201, len(active)]},
        "tiers_by_type": tier_counts,
        "data_freshness": {
            "punishments": max(r["date"] for r in punishments),
            "media": media.get("as_of"), "fees": "115學年度",
        },
        "model": model_block,
    })
    print(f"→ {out}　scores {len(items)} 筆（{len(active)} 在營運）、"
          f"districts 29、worklist 50")


def _actions(f, park, law_by_cat):
    """派工單的查核重點。SPEC §8.9 硬規則 3：

    每一條必須指向具體法條或核定數字，不能是「加強查核」這種空話。
    稽查人員拿著這張單子走進園所，要知道第一眼要看哪裡；「例行查核」
    等於沒講，也把模型排這園第几名的理由藏起來了。
    """
    actions = []
    cats = sorted(((k[len("vio_cat_"):], v) for k, v in f.items()
                   if k.startswith("vio_cat_") and v), key=lambda kv: -kv[1])
    for name, n in cats[:2]:
        law = law_by_cat.get((park["park_id"], name))
        why = (f"歷史違規集中於{law}（{n} 次）" if law
               else f"歷史有 {name} 裁罰 {n} 次")
        actions.append({"focus": name, "why": why})
    if f.get("vio_cat_超收") and park.get("count_approved"):
        actions.append({
            "focus": f"實際招收人數 vs 核定 {park['count_approved']} 人",
            "why": f"歷史有超收裁罰 {f['vio_cat_超收']} 次",
        })
    if len(actions) < 3 and f.get("eval_base_fail_count"):
        actions.append({
            "focus": "基礎評鑑未通過項目之改善情形",
            "why": f"基礎評鑑 {f['eval_base_fail_count']} 次未全數通過",
        })
    if len(actions) < 3 and f.get("eval_missing"):
        actions.append({
            "focus": "新立案園所首次訪視",
            "why": "查無評鑑紀錄，尚未納入評鑑循環",
        })
    return actions[:3]


if __name__ == "__main__":
    main()
