"""§6.2 時間切分回測。主指標 Precision@50。

    python -m model.backtest --in ./out/curated --out ./out/model

回測的定義：用 `date < 2025-01-01` 的特徵排序，看排在前 K 名的園裡，
有幾家在 `date >= 2025-01-01` 真的被裁罰。母體是 1,178 家 is_active 園，
基準率 10.6%。

## 門檻

**Precision@50 >= 26.0%**，見 `docs/adr/0001`。

SPEC §6.3 寫的是 28.0%，但那是第 4 列那條**用原始次數直接相加**的手算排序
的成績（權重 1:2:3 手挑），屬 v1 方法。§6.3 自己的註腳就寫著同一條排序
改用 v2 的零膨脹百分位後是 26.0%——**拿 A 方法的成績要求 B 方法達標**。

兩個數字都印出來，不藏。
"""
import argparse
import collections
import json
from pathlib import Path

from etl.constants import TIERS, WEIGHTS
from .scoring import assign_tiers, score_all

KS = [10, 20, 30, 50, 100, 150, 200, 250, 300]
GATE = 0.26        # ADR-0001。§6.3 的 28.0% 是 v1 方法量的，見上方 docstring


def load(indir):
    with open(Path(indir) / "features.json", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [r for r in rows if r["is_active"] == 1]


def load_finance(indir):
    """營運維度（B 軌）。**回測必須帶上它**，否則報出來的數字不是實際出貨的模型。

    它只影響公立 290 + 非營利 12 園，而那正是監督式模型失效的區段
    （公立組 lift 0.86x）。對全母體 P@50 幾乎沒有影響是預期中的——
    高風險名單由私幼主導，私幼沒有營運資料。
    """
    path = Path(indir) / "finance.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {r["park_id"]: r for r in json.load(fh)}


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
    scored = assign_tiers(score_all(rows, weights or WEIGHTS, finance or {}), TIERS)
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

    finance = load_finance(args.indir)
    order, scored = model_ordering(rows, finance=finance)
    print(f"營運維度：{len(finance)} 園有資料"
          f"（{sum(1 for r in finance.values() if r['operation_score'] is not None)} 園算得出分數）\n")
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
    gate = "✅ 通過" if p50 >= GATE else "❌ 未達門檻"
    print(f"\n門檻 Precision@50 >= {GATE:.1%}（v2 方法，ADR-0001）："
          f"實測 {p50:.1%} → {gate}")
    print(f"參考　§6.3 原訂 28.0% 是 v1 原始值加權的成績，方法不同不可直接相比")

    with open(out / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump({
            "population": len(rows), "positives": positives,
            "baseline": round(baseline, 4),
            "gate_p_at_50": GATE, "gate_basis": "ADR-0001：v2 零膨脹百分位方法的門檻",
            "spec_gate_p_at_50": 0.28, "spec_gate_basis": "SPEC §6.3：v1 原始值加權的手算基準線",
            "passed": p50 >= GATE,
            "orderings": summary, "stratified": strat,
        }, fh, ensure_ascii=False, indent=1)

    with open(out / "curve.json", "w", encoding="utf-8") as fh:
        json.dump({
            "population": len(rows), "positives": positives,
            "baseline": round(baseline, 4),
            "points": curve(rows, orderings, positives),
            "summary": {
                # random 不在 orderings 裡（它不是一種排序），但成效驗證頁要拿它
                # 當基準線。隨機抽查的 Precision@K 就是母體被罰率，跟 K 無關。
                "precision_at_50": {
                    **{n: summary[n]["p_at_50"] for n in orderings},
                    "random": round(baseline, 4),
                },
                "stratified": strat,
            },
        }, fh, ensure_ascii=False, indent=1)
    print(f"→ {out}/metrics.json、{out}/curve.json")


if __name__ == "__main__":
    main()
