"""§6.2 時間切分回測。主指標 Precision@50。

    python -m model.backtest --in ./out/curated --out ./out/model

回測的定義：用 `date < 2025-01-01` 的特徵排序，看排在前 K 名的園裡，
有幾家在 `date >= 2025-01-01` 真的被裁罰。母體是 1,178 家 is_active 園，
基準率 10.6%。

**門檻 Precision@50 >= 28.0%**（SPEC §6.3）。低於這個數字，模型不如
「裁罰次數 + 評鑑」的手調基準，就沒有存在價值。
"""
import argparse
import collections
import json
from pathlib import Path

from etl.constants import TIERS, WEIGHTS
from .scoring import assign_tiers, score_all

KS = [10, 20, 30, 50, 100, 150, 200, 250, 300]


def load(indir):
    with open(Path(indir) / "features.json", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [r for r in rows if r["is_active"] == 1]


def precision_at(ordering, k):
    """前 k 名裡的正樣本比例。"""
    top = ordering[:k]
    return sum(1 for r in top if r["label"]) / len(top) if top else 0.0


def hits_at(ordering, k):
    return sum(1 for r in ordering[:k] if r["label"])


def baseline_orderings(rows):
    """§6.3 的三條對照線。它們同時就是效益曲線的對照組，不必另外算。"""
    return {
        # 只看切點前裁罰次數（純違規）
        "punish": sorted(rows, key=lambda r: (-(r["vio_pun_count"] or 0),
                                              -(r["vio_pun_weighted"] or 0))),
        # 只看評鑑：未通過×2 + 行政處分×3
        "eval": sorted(rows, key=lambda r: -((r["eval_base_fail_count"] or 0) * 2
                                             + (r["eval_admin_count"] or 0) * 3
                                             + (r["eval_followup_count"] or 0))),
    }


def model_ordering(rows, weights=None, finance=None):
    scored = assign_tiers(score_all(rows, weights or WEIGHTS, finance), TIERS)
    by_id = {s["park_id"]: s for s in scored}
    return sorted(rows, key=lambda r: -by_id[r["park_id"]]["raw"]), scored


def stratified(rows, scored, group_field="institution_type"):
    """§6.4 風險 1：模型可能退化成「私幼就是高風險」。必須分層報。"""
    by_id = {s["park_id"]: s for s in scored}
    out = {}
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r[group_field]].append(r)
    for name, members in groups.items():
        order = sorted(members, key=lambda r: -by_id[r["park_id"]]["raw"])
        n = len(members)
        base = sum(1 for r in members if r["label"]) / n
        # 小樣本組取較小的 K，否則 K=n 時 lift 必然是 1.00x（§6.4 註）
        k = 50 if n >= 300 else (20 if n >= 100 else max(5, n // 5))
        p = precision_at(order, k)
        out[name] = {
            "n": n, "positives": sum(1 for r in members if r["label"]),
            "baseline": round(base, 4), "k": k,
            f"p_at_{k}": round(p, 4),
            f"lift_{k}": round(p / base, 2) if base else None,
        }
    return out


def curve(rows, orderings, positives):
    """§6.5 稽查效益曲線。x = 稽查家數 K，y = 命中的切點後被罰園數。"""
    points = []
    for k in range(1, 301):
        point = {"k": k, "random": round(k * positives / len(rows), 2),
                 "perfect": min(k, positives)}
        for name, order in orderings.items():
            point[name] = hits_at(order, k)
        points.append(point)
    return points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="./out/curated")
    ap.add_argument("--out", dest="outdir", default="./out/model")
    ap.add_argument("--model", dest="_model", default=None, help="相容用，未使用")
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    rows = load(args.indir)
    positives = sum(1 for r in rows if r["label"])
    baseline = positives / len(rows)
    print(f"母體 {len(rows)}　正樣本 {positives}　基準率 {baseline:.1%}\n")

    order, scored = model_ordering(rows)
    orderings = {"model": order, **baseline_orderings(rows)}

    print(f"{'排序方式':<22}{'P@20':>8}{'P@50':>8}{'P@100':>8}{'lift@50':>9}")
    summary = {}
    for name, o in orderings.items():
        p50 = precision_at(o, 50)
        summary[name] = {f"p_at_{k}": round(precision_at(o, k), 4) for k in KS}
        summary[name]["lift_at_50"] = round(p50 / baseline, 2)
        print(f"{name:<22}{precision_at(o,20):>8.1%}{p50:>8.1%}"
              f"{precision_at(o,100):>8.1%}{p50/baseline:>8.2f}x")
    print(f"{'random':<22}{baseline:>8.1%}{baseline:>8.1%}{baseline:>8.1%}{1.00:>8.2f}x")

    strat = stratified(rows, scored)
    print("\n分層（§6.4）")
    for name, s in sorted(strat.items()):
        k = s["k"]
        print(f"  {name:<6} n={s['n']:<5} 基準 {s['baseline']:>6.1%}  "
              f"P@{k}={s[f'p_at_{k}']:>6.1%}  lift {s[f'lift_{k}']}x")

    p50 = summary["model"]["p_at_50"]
    gate = "✅ 通過" if p50 >= 0.28 else "❌ 未達門檻"
    print(f"\n門檻 Precision@50 >= 28.0%：實測 {p50:.1%} → {gate}")

    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump({
            "population": len(rows), "positives": positives,
            "baseline": round(baseline, 4),
            "gate_p_at_50": 0.28, "passed": p50 >= 0.28,
            "orderings": summary, "stratified": strat,
        }, fh, ensure_ascii=False, indent=1)

    with open(out / "curve.json", "w", encoding="utf-8") as fh:
        json.dump({
            "population": len(rows), "positives": positives,
            "baseline": round(baseline, 4),
            "points": curve(rows, orderings, positives),
            "summary": {
                "precision_at_50": {n: summary[n]["p_at_50"] for n in orderings},
                "stratified": strat,
            },
        }, fh, ensure_ascii=False, indent=1)
    print(f"→ {out}/metrics.json、{out}/curve.json")


if __name__ == "__main__":
    main()
