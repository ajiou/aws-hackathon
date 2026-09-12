"""raw → curated。SPEC §3.10 的八個步驟，每步結束跑對應的 assert。

    export WATCHDOG_SALT="本機自訂字串，不進 git"
    python etl/build_curated.py --out ./out/curated

失敗即中止是刻意的：洩漏與個資都屬於「跑得出結果但結果不能用」的失敗，
靠人記得檢查不可靠（SPEC §3.10 洩漏防護段）。

## 與 SPEC 的兩處實測落差（已驗證，不是筆誤）

1. **`features.json` 是 1,215 筆，不是 §14.1 寫的 1,212。**
   1,212 是 `園所裁罰特徵.json` 的涵蓋數，比母體少 3 園——實測那 3 園是
   **仍在營運的非營利園**（碧城、安興、北大），其中安興與北大正是 B 軌
   12 家有財報園中的 2 家，安興更是 NARRATIVE §4.4 的主敘事案例。
   把母體砍成 1,212 等於為了讓一個 checkbox 過關而丟掉主敘事。
   §1.1 本來就寫「缺 3 園，ETL 需以 left join 補 0」，本檔照做。
   **正樣本仍為 128**（實測兩種母體皆同，且與特徵檔的標籤欄逐筆相符）。

2. **新北裁罰是 1,464 筆，不是 §2.1 寫的 1,423。**
   `punish.json` 抓取時間較新（到 2026-08-21）。切點前 1,216 筆進特徵，
   切點後 248 筆 / 128 園當標籤。
"""
import argparse
import collections
import json
from datetime import date
from pathlib import Path

from . import features as features_mod
from .categories import assert_all_classified, classify
from .constants import CUTOFF, TIERS
from .pii import hash_person
from .quality import assert_no_banned, assert_no_leakage, assert_no_pii, assert_population
from .sources import (DATA, load_evaluations, load_fees, load_media, load_parks,
                      load_punishments, normalize_public_name, public_standalone_names)

NTPC_TOWNS = 29          # 新北市行政區數，§3.10 第 6 步的出口檢查


def step(n, title):
    print(f"[{n}/8] {title}", end="  ")


def ok(msg=""):
    print(f"✅ {msg}")


def assign_peer_groups(parks, finance_park_ids):
    """§5.6.0 營運維度的四個同儕群。**依可取得的資料切，不只依設立別。**

    273 家附設園沒有獨立決算不是資料缺漏，是制度使然——教育局本身就沒有
    「板橋國小附幼」這個預算單位。名冊唯一可靠的來源是決算書第五冊的
    預算單位清單，也就是 `docs/總說明/*.md` 的標題。
    """
    standalone = public_standalone_names()
    counts = collections.Counter()
    for park in parks:
        if park["type"] == "私立":
            group = "私立"
        elif park["type"] == "非營利":
            group = "非營利-有財報" if park["park_id"] in finance_park_ids else "非營利-無財報"
        elif normalize_public_name(park["name"]) in standalone:
            group = "公立-獨立"
        else:
            group = "公立-附設"
        park["peer_group"] = group
        if park["is_active"] == 1:
            counts[group] += 1
    return counts


def build_owner_priors(parks):
    """累犯負責人.json（已是切點前版本）→ owner_key 索引。

    姓名在來源檔裡是明文，這裡雜湊後才留下，與 parks 的 owner_key 對得起來。
    """
    with open(DATA / "累犯負責人_cutoff20250101.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        hash_person(r["姓名"]): {"count": r["處分次數"], "cross_park": r["是否跨園"]}
        for r in raw if hash_person(r["姓名"])
    }


def build_fees(parks_by_id):
    """§3.7。實測 280 筆 100% 為公立——檔名的「與非營利」與內容不符。"""
    rows = []
    for name, items in load_fees().items():
        if not items:
            continue
        park_id = items[0]["id"]
        if park_id not in parks_by_id:
            continue
        total = sum(i.get("上學期全日班小計") or 0 for i in items) + \
                sum(i.get("下學期全日班小計") or 0 for i in items)
        rows.append({
            "park_id": park_id,
            "name": name,
            "school_year": items[0]["學年度"],
            "type": items[0]["類別"],
            "town": items[0]["行政區"],
            "items": items,
            "total_full_year": total,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./out/curated")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def dump(name, payload):
        with open(out / name, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)

    # ---- 1 載入母體
    step(1, "載入母體")
    parks = load_parks()
    assert_population(parks, 1215, "新北母體")
    assert len({p["park_id"] for p in parks}) == len(parks), "park_id 不唯一"
    active = [p for p in parks if p["is_active"] == 1]
    ok(f"1,215 園（is_active=1 者 {len(active)}）")

    # ---- 2 個資雜湊（已於 load_* 內完成，這裡驗收）
    step(2, "個資雜湊")
    assert_no_pii(parks)
    punishments = [p for p in load_punishments()
                   if p["park_id"] in {q["park_id"] for q in parks}]
    assert_no_pii(punishments)
    ok(f"owner→owner_key、裁罰行為人→target_key，共 {len(punishments)} 筆裁罰")

    # ---- 3 欄位清洗
    step(3, "欄位清洗")
    assert_no_banned(parks)
    assert all(isinstance(p["size_in"], (float, type(None))) for p in parks)
    assert all(isinstance(p["floor_count"], (int, type(None))) for p in parks)
    ok("penalty / is_free5 / shuttle 已移除，型別檢查通過")

    # ---- 4 裁罰整併
    step(4, "裁罰整併")
    assert_all_classified(punishments)
    for row in punishments:
        row["category"] = classify(row["law"])
        row["is_after_cutoff"] = bool(row["date"] and row["date"] >= CUTOFF.isoformat())
    assert not [r for r in punishments if not r["category"]], "category 有 null"
    assert not [r for r in punishments if not r["date"]], "date 有 null"
    dump("punishments.json", punishments)
    pre = [r for r in punishments if not r["is_after_cutoff"]]
    ok(f"{len(punishments)} 筆（切點前 {len(pre)}、切點後 {len(punishments) - len(pre)}）")

    # ---- 5 評鑑整併
    step(5, "評鑑整併")
    evaluations = load_evaluations()
    names = {p["name"] for p in parks}
    hit = {r["園名"] for r in evaluations} & names
    assert len(hit) == len({r["園名"] for r in evaluations}), "評鑑園名 join 未達 100%"
    pre_eval = [r for r in evaluations
                if r.get("評鑑完成日") and r["評鑑完成日"] < CUTOFF.isoformat()]
    dropped = len(evaluations) - len(pre_eval)
    assert_no_leakage(pre_eval, ["評鑑完成日"])
    assert dropped == 280, f"應丟棄 280 列（258 切點後 + 22 無日期），實際 {dropped}"
    dump("evaluations.json", pre_eval)
    ok(f"join {len(hit)}/{len({r['園名'] for r in evaluations})}，丟棄 {dropped} 列")

    # ---- 6 輿情整併（全部先過切點）
    step(6, "輿情整併")
    media_tables = load_media()
    ok("待特徵組裝時一併計算")

    # ---- 7 特徵組裝
    step(7, "特徵組裝")
    finance_path = out / "finance.json"
    finance_rows = json.loads(finance_path.read_text(encoding="utf-8")) if finance_path.exists() else []
    finance_ids = {r["park_id"] for r in finance_rows}
    groups = assign_peer_groups(parks, finance_ids)
    assert groups["公立-獨立"] + groups["公立-附設"] == 290, \
        f"公立同儕群相加 {groups['公立-獨立'] + groups['公立-附設']} != 290"

    owner_priors = build_owner_priors(parks)
    rows, park_level, district = features_mod.build_features(
        parks, punishments, evaluations, media_tables, owner_priors,
        finance={r["park_id"]: {f"oper_{k}": v for k, v in r["metrics"].items()
                                if k not in ("school_year", "fiscal_year")}
                 for r in finance_rows},
    )
    assert_population(rows, 1215, "features")
    assert_no_pii(rows)
    assert_no_banned(rows)
    positives = sum(1 for r in rows if r["label"])
    assert positives == 128, f"正樣本 {positives} != 128"
    assert_no_leakage(rows, ["media_last_negative_at"])
    assert len(district) == NTPC_TOWNS, f"行政區 {len(district)} != {NTPC_TOWNS}"
    dump("features.json", rows)
    dump("media.json", {
        "as_of": CUTOFF.isoformat(),
        "note": "全部以 published_at < CUTOFF 過濾，不可與 data/media/park_risk.json 混用",
        "park_level": [dict(park_id=k, **v) for k, v in sorted(park_level.items())],
        "district_level": district,
    })
    ok(f"1,215 筆，正樣本 {positives}，輿情 L1 {len(park_level)} 園 / "
       f"L2 {sum(1 for d in district if d['has_signal'])} 區有訊號")

    # ---- 8 財務與收費
    step(8, "財務與收費")
    parks_by_id = {p["park_id"]: p for p in parks}
    fees = build_fees(parks_by_id)
    assert_population(fees, 280, "fees")
    assert all(r["park_id"] in parks_by_id for r in fees)
    assert {r["type"] for r in fees} == {"公立"}, "收費明細應 100% 為公立"
    dump("fees.json", fees)
    if not finance_path.exists():
        dump("finance.json", [])
    dump("parks.json", parks)
    dump("meta.json", {
        "as_of_date": date.today().isoformat(),
        "cutoff": CUTOFF.isoformat(),
        "population": len(active),
        "population_all": len(parks),
        "positives": positives,
        "baseline": round(positives / len(rows), 4),
        "peer_groups": dict(groups),
        "tiers": [{"tier": t, "from": lo, "to": hi} for t, lo, hi in TIERS],
        "media_note": "輿情特徵以切點前資料重算；data/media/park_risk.json 為切點後快照，僅供展示",
    })
    ok(f"fees 280 園、finance {len(finance_rows)} 筆"
       + ("（B 軌尚未交付，coverage=0）" if not finance_rows
          else "（" + "、".join(f"{k} {v}" for k, v in
                               sorted(collections.Counter(
                                   r["peer_group"] for r in finance_rows).items())) + "）"))

    print(f"\n完成 → {out}")
    print("同儕群：" + "、".join(f"{k} {v}" for k, v in sorted(groups.items())))


if __name__ == "__main__":
    main()
