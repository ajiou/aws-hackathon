"""營運維度。SPEC §5.6，ASSIGNMENTS B。

    python -m etl.operation --out ./out/curated

四個同儕群各用各的公式、各自做 ECDF：

| 同儕群 | 園數 | 公式 | 來源 |
|---|---:|---|---|
| 公立-獨立 | 21 | `O = 60%F + 25%E + 15%C` | 總說明 md ＋ 收費明細 |
| 公立-附設 | 269 | `O = 100%C` | 收費明細 |
| 非營利-有財報 | 12 | `O = 40%F + 45%H + 15%E` | OCR 財報 |
| 非營利-無財報 | 41 | `applicable = false` | — |
| 私立 | 835 | `applicable = false` | — |

## 三條不能違反的（ASSIGNMENTS B）

1. **私立與非營利-無財報不是 0 分**，是 `applicable = false`、`score = null`。
   私幼依法不需公告財報，當成 0 分等於懲罰守法者。
2. **查核表「否」不進任何維度分數**，只進 `finance_flags`（§5.6.6）。
   2,259 個判定只有 9 個「否」，而且與裁罰反向。保留的是 §5.6.7 的 80／90 下限。
3. **`validated` 永遠 `false`**。有財務資料的 33 園中被裁罰過的只有個位數，
   無法訓練也無法驗證。權重是領域判斷手訂的，不是從資料學出來的。

## 風險方向

`上尾` 越高越危險（負債比、加班費執行率）、`下尾` 越低越危險（招生率、教保薪資執行率）、
`雙尾` 離同儕中位數越遠越危險（總預算執行率）。方向錯了分數會整個顛倒，
所以每個指標都在 `INDICATORS` 裡標死，不在計算時臨時判斷。
"""
import argparse
import collections
import json
import statistics
from pathlib import Path

from .constants import PEER_GROUPS

# (欄位, 子維度, 維度內權重, 方向)
INDICATORS = {
    "公立-獨立": [
        ("expense_deviation", "F", None, "雙尾"),
        ("tuition_exec_rate", "F", None, "下尾"),
        ("deficit_ratio", "F", None, "上尾"),
        ("cash_decrease_ratio", "F", None, "上尾"),
        ("debt_ratio", "F", None, "上尾"),
        ("networth_decline", "F", None, "上尾"),
        ("enroll_ratio", "E", 0.50, "下尾"),
        ("enroll_decline", "E", 0.30, "上尾"),
        ("over_enroll", "E", 0.20, "上尾"),
        ("fee_deviation", "C", 0.60, "雙尾"),
        ("fee_consistency", "C", 0.25, "上尾"),
        ("fee_completeness", "C", 0.15, "上尾"),
    ],
    "公立-附設": [
        ("fee_deviation", "C", 0.60, "雙尾"),
        ("fee_consistency", "C", 0.25, "上尾"),
        ("fee_completeness", "C", 0.15, "上尾"),
    ],
    "非營利-有財報": [
        ("income_exec_deviation", "F", None, "雙尾"),
        ("expense_exec_deviation", "F", None, "雙尾"),
        ("deficit_ratio", "F", None, "上尾"),
        ("personnel_exec_rate", "H", 0.25, "下尾"),
        ("teacher_salary_exec_rate", "H", 0.35, "下尾"),
        ("overtime_exec_rate", "H", 0.20, "上尾"),
        ("substitute_exec_rate", "H", 0.20, "上尾"),
        ("enroll_ratio", "E", 1.00, "下尾"),
    ],
}
SUB_WEIGHTS = {g: PEER_GROUPS[g]["operation"] for g in INDICATORS}
SHRINK_PRIOR = 8          # §5.6.4 收縮中位數的先驗樣本數


def _ratio(num, den):
    if num is None or not den:
        return None
    return num / den


def nonprofit_metrics(rows):
    """非營利-有財報：取每園**最新學年度**。前年度比較欄只作趨勢，不另建觀測值。"""
    latest = {}
    for row in rows:
        key = row["park_id"]
        if key not in latest or row["school_year"] > latest[key]["school_year"]:
            latest[key] = row
    out = {}
    for pid, row in latest.items():
        p, s, ex = row["personnel"], row["summary"], row["execution"]
        rate = lambda k: (p[k]["rate"] if k in p else None)
        income = ex.get("income") or {}
        expense = ex.get("expense") or {}
        enroll = s.get("enroll_ratio_reported")
        if enroll is None:
            enroll = _ratio(s.get("enrolled_total"), s.get("approved_total"))
        out[pid] = {
            "school_year": row["school_year"],
            # 四欄核對沒過的執行率不進模型（§3.10 第 8 步）
            "income_exec_deviation": (abs(income["rate"] - 1)
                                      if income.get("rate") and not income["needs_review"] else None),
            "expense_exec_deviation": (abs(expense["rate"] - 1)
                                       if expense.get("rate") and not expense["needs_review"] else None),
            "deficit_ratio": (max(0.0, -_ratio(s.get("surplus_before_tax"), s.get("tuition_income")))
                              if s.get("surplus_before_tax") is not None and s.get("tuition_income") else None),
            "personnel_exec_rate": rate("人事費"),
            "teacher_salary_exec_rate": rate("教保薪資"),
            "overtime_exec_rate": rate("加班費"),
            "substitute_exec_rate": rate("代課代班費"),
            "enroll_ratio": enroll,
            "flags": row["flags"],
            "source_pdf": row["source_pdf"],
        }
    return out


def public_metrics(rows):
    """公立-獨立：總說明 md。取最新年度，招生年減率要兩個年度才算得出來。"""
    by_park = collections.defaultdict(list)
    for row in rows:
        if row["park_id"]:
            by_park[row["park_id"]].append(row)

    out = {}
    for pid, years in by_park.items():
        years.sort(key=lambda r: r["fiscal_year"])
        cur = years[-1]
        prev = years[-2] if len(years) > 1 else None
        students = max((e["students"] for e in cur["enrolment"]), default=None)
        prev_students = max((e["students"] for e in prev["enrolment"]), default=None) if prev else None
        approved = cur["count_approved"]
        cash_start = (cur["cash_end"] - cur["cash_change"]
                      if cur["cash_end"] is not None and cur["cash_change"] is not None else None)
        out[pid] = {
            "fiscal_year": cur["fiscal_year"],
            "expense_deviation": (abs(_ratio(cur["use_actual"], cur["use_budget"]) - 1)
                                  if _ratio(cur["use_actual"], cur["use_budget"]) else None),
            "tuition_exec_rate": _ratio(cur["tuition_actual"], cur["tuition_budget"]),
            "deficit_ratio": (max(0.0, -_ratio(cur["net_surplus"], cur["source_actual"]))
                              if cur["net_surplus"] is not None and cur["source_actual"] else None),
            "cash_decrease_ratio": (max(0.0, -_ratio(cur["cash_change"], cash_start))
                                    if cash_start else None),
            "debt_ratio": _ratio(cur["liabilities"], cur["assets"]),
            "networth_decline": (max(0.0, -cur["equity_change_pct"])
                                 if cur["equity_change_pct"] is not None else None),
            "enroll_ratio": _ratio(students, approved),
            "enroll_decline": (max(0.0, 1 - students / prev_students)
                               if students and prev_students else None),
            # 同年度確認超收時該項直接 100 分（§5.6.2）
            "over_enroll": (100.0 if students and approved and students > approved else 0.0)
                           if students and approved else None,
            "students": students, "count_approved": approved,
        }
    return out


def fee_metrics(fees, parks):
    """收費異常 C。**只有公立有收費明細**——280 筆實測 100% 為公立（§5.6.1）。

    同儕基準用收縮中位數（§5.6.4）：`(n_g·Median_g + 8·Median_city) / (n_g + 8)`。
    小行政區只有兩三家公立園，直接取區中位數等於拿自己當基準。

    > 收費表是**核准公告價格**，偏離只作弱訊號，不直接視為違規。
    """
    town_of = {p["park_id"]: p["town"] for p in parks}
    totals = {r["park_id"]: r["total_full_year"] for r in fees if r["total_full_year"]}
    city_median = statistics.median(totals.values())
    by_town = collections.defaultdict(list)
    for pid, total in totals.items():
        by_town[town_of.get(pid)].append(total)

    item_counts = {r["park_id"]: len(r["items"]) for r in fees}
    typical_items = statistics.median(item_counts.values())

    out = {}
    for row in fees:
        pid = row["park_id"]
        total = totals.get(pid)
        group = by_town.get(town_of.get(pid), [])
        if group and total:
            median = ((len(group) * statistics.median(group) + SHRINK_PRIOR * city_median)
                      / (len(group) + SHRINK_PRIOR))
            deviation = abs(total - median) / median * 100
        else:
            deviation = None

        # 一致性：同園內上下學期同項目單價應一致、半日班不應高於全日班
        inconsistent = 0
        for item in row["items"]:
            t1, t2 = item.get("上學期全日班單價"), item.get("下學期全日班單價")
            if t1 and t2 and t1 != t2:
                inconsistent += 1
            half, full = item.get("上學期半日班單價"), item.get("上學期全日班單價")
            if half and full and half > full:
                inconsistent += 1
        out[pid] = {
            "fee_deviation": deviation,
            "fee_consistency": float(inconsistent),
            "fee_completeness": abs(item_counts[pid] - typical_items),
            "total_full_year": total,
            "peer_median_full_year": round(median) if group and total else None,
            "deviation_pct": round((total - median) / median * 100, 1) if group and total else None,
        }
    return out


def percentile(values, direction):
    """同儕群內轉風險百分位。缺值回 None，由覆蓋率加權處理，不填 0。"""
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return [None if v is None else 50.0 for v in values]
    if direction == "雙尾":
        median = statistics.median(known)
        keyed = [None if v is None else abs(v - median) for v in values]
    elif direction == "下尾":
        keyed = [None if v is None else -v for v in values]
    else:
        keyed = list(values)
    ranked = sorted(v for v in keyed if v is not None)
    n = len(ranked)
    out = []
    for v in keyed:
        if v is None:
            out.append(None)
        else:
            lo = ranked.index(v)
            hi = n - 1 - ranked[::-1].index(v)
            out.append(100 * ((lo + hi) / 2 + 1) / n)
    return out


def audit_floor(flags):
    """§5.6.7。罕見但嚴重的情況不需要統計顯著性，所以下限規則保留。

    回傳 (下限值, 觸發的重大缺失數)。下限是**規則覆蓋計算結果**，
    必須記錄在 `audit_floor_applied`，讓稽查員追得到分數為什麼被拉高。
    """
    major = sum(1 for f in flags if f["severity"] == 3)
    if major >= 2:
        return 90, major
    if major == 1:
        return 80, major
    return None, 0


def build(curated):
    parks = json.loads((curated / "parks.json").read_text(encoding="utf-8"))
    fees = json.loads((curated / "fees.json").read_text(encoding="utf-8"))
    nonprofit = nonprofit_metrics(
        json.loads((curated / "finance_raw.json").read_text(encoding="utf-8")))
    public = public_metrics(
        json.loads((curated / "public_finance.json").read_text(encoding="utf-8")))
    fee_rows = fee_metrics(fees, parks)

    groups = collections.defaultdict(list)
    for park in parks:
        if park["is_active"] != 1:
            continue
        pid = park["park_id"]
        group = ("非營利-有財報" if pid in nonprofit else
                 "公立-獨立" if pid in public else
                 "公立-附設" if park["type"] == "公立" else None)
        if group:
            groups[group].append(park)

    results = []
    for group, members in groups.items():
        metrics = {}
        for park in members:
            pid = park["park_id"]
            row = dict(nonprofit.get(pid) or public.get(pid) or {})
            row.update(fee_rows.get(pid, {}))
            metrics[pid] = row

        pcts = {}
        for field, _sub, _w, direction in INDICATORS[group]:
            values = [metrics[p["park_id"]].get(field) for p in members]
            for park, p in zip(members, percentile(values, direction)):
                pcts.setdefault(park["park_id"], {})[field] = p

        for park in members:
            pid = park["park_id"]
            subs, total_cov_num, total_cov_den = {}, 0.0, 0.0
            for sub, sub_weight in SUB_WEIGHTS[group].items():
                fields = [(f, w) for f, s, w, _ in INDICATORS[group] if s == sub]
                equal = 1 / len(fields)
                num = den = tot = 0.0
                for field, weight in fields:
                    weight = weight if weight is not None else equal
                    tot += weight
                    value = pcts[pid].get(field)
                    if value is not None:
                        num += weight * value
                        den += weight
                subs[sub] = {"score": round(num / den, 1) if den else None,
                             "coverage": round(den / tot, 2) if tot else 0.0,
                             "weight": sub_weight}
                total_cov_num += sub_weight * (den / tot if tot else 0)
                total_cov_den += sub_weight

            num = sum(s["weight"] * s["coverage"] * s["score"]
                      for s in subs.values() if s["score"] is not None)
            den = sum(s["weight"] * s["coverage"]
                      for s in subs.values() if s["score"] is not None)
            score = num / den if den else None

            flags = metrics[pid].get("flags", [])
            floor, major = audit_floor(flags)
            if floor and (score is None or score < floor):
                score = float(floor)

            results.append({
                "park_id": pid, "name": park["name"], "peer_group": group,
                "school_year": metrics[pid].get("school_year") or metrics[pid].get("fiscal_year"),
                "metrics": {k: (round(v, 4) if isinstance(v, float) else v)
                            for k, v in metrics[pid].items()
                            if k not in ("flags", "source_pdf")},
                "sub_scores": subs,
                "operation_score": round(score, 1) if score is not None else None,
                "coverage": round(total_cov_num / total_cov_den, 2) if total_cov_den else 0.0,
                "audit_floor_applied": floor,
                "audit_major_count": major,
                "validated": False,          # §5.6.8，永遠 false
                "flags": [{**f, "validated": False} for f in flags],
                "source_pdf": metrics[pid].get("source_pdf"),
            })
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./out/curated")
    args = ap.parse_args()
    curated = Path(args.out)
    results = build(curated)

    assert all(r["validated"] is False for r in results), "validated 必須永遠是 false"
    counts = collections.Counter(r["peer_group"] for r in results)
    assert counts["公立-獨立"] == 21, f"公立-獨立 {counts['公立-獨立']} != 21"
    assert counts["非營利-有財報"] == 12, f"非營利-有財報 {counts['非營利-有財報']} != 12"

    with open(curated / "finance.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)

    print(f"{'同儕群':<14}{'園數':>5}{'有分數':>7}{'平均覆蓋率':>10}")
    for group in ("公立-獨立", "公立-附設", "非營利-有財報"):
        rows = [r for r in results if r["peer_group"] == group]
        scored = [r for r in rows if r["operation_score"] is not None]
        cov = statistics.mean(r["coverage"] for r in rows) if rows else 0
        print(f"{group:<14}{len(rows):>5}{len(scored):>7}{cov:>10.0%}")
    floors = [r for r in results if r["audit_floor_applied"]]
    print(f"\n查核下限生效 {len(floors)} 園"
          + ("：" + "、".join(f"{r['name'][:10]}→{r['audit_floor_applied']}" for r in floors)
             if floors else ""))
    print(f"finance_flags 合計 {sum(len(r['flags']) for r in results)} 項"
          f"（不進任何維度分數，§5.6.6）")
    print(f"→ {curated}/finance.json")


if __name__ == "__main__":
    main()
