"""四維度分數的數學核心。SPEC §5.1、§5.2。

train / backtest / score 三支都用這裡的函式，避免同一個公式寫三遍後漂移。

## 兩個容易寫錯的地方

1. **零膨脹百分位只套在有自然零點的指標**（§5.1）。裁罰次數的 0 是
   「沒被罰過」，執行率的 0 不是——後者用一般 ECDF。每個子指標在
   `INDICATORS` 裡標明用哪一種，不是在呼叫端臨時決定。

2. **缺資料不填 0，改用覆蓋率加權**（§5.1）。`a_ij = 0` 代表該指標不參與
   計算，同時如實回報 Coverage。v1 用中位數填補等於假設「沒資料的園跟
   中位數一樣」，那是在憑空造資料。
"""
import collections
from bisect import bisect_left, bisect_right

# 子指標：(欄位, 維度內權重, 轉換方式)
# 轉換 "zero" = 零膨脹百分位（有自然零點且零值占比 > 20%）、"ecdf" = 一般 ECDF
INDICATORS = {
    "violation": [
        ("vio_pun_weighted", 0.40, "zero"),
        ("vio_pun_count", 0.20, "zero"),
        ("vio_owner_prior_count", 0.20, "zero"),
        ("vio_sibling_pun_count", 0.10, "zero"),
        ("vio_abuse_count", 0.10, "zero"),
    ],
    "evaluation": [
        ("eval_base_fail_count", 0.40, "zero"),
        ("eval_admin_count", 0.35, "zero"),
        ("eval_followup_count", 0.25, "zero"),
    ],
    "sentiment": [
        ("media_sri", 0.60, "zero"),
        ("media_town_heat_per_park", 0.40, "zero"),
    ],
    "operation": [],      # B 軌交付後由 finance.json 的 sub_scores 提供
}


def pct_zero_inflated(values):
    """0 值給 0 分；非 0 值在非 0 子集內排名，映射到 (0, 100]。SPEC §5.1。

    為什麼需要：違規維度有 53.7% 的私立園原始值為 0，原樣 ECDF 會讓它們
    全部並列在 26.8 分，而且尾端被壓縮（12 次 vs 3 次只差 8.1 分）。
    """
    nonzero = sorted(v for v in values if v is not None and v > 0)
    m = len(nonzero)
    out = []
    for v in values:
        if v is None:
            out.append(None)
        elif v <= 0:
            out.append(0.0)
        else:
            lo, hi = bisect_left(nonzero, v), bisect_right(nonzero, v)
            out.append(100 * (((lo + hi - 1) / 2) + 1) / m)
    return out


def pct_ecdf(values):
    """一般 ECDF 百分位，用於無自然零點的連續量（執行率、負債比）。"""
    known = sorted(v for v in values if v is not None)
    n = len(known)
    out = []
    for v in values:
        if v is None:
            out.append(None)
        else:
            lo, hi = bisect_left(known, v), bisect_right(known, v)
            out.append(100 * (((lo + hi - 1) / 2) + 1) / n)
    return out


def _availability(row, field):
    """a_ij：該指標是否存在、可用。

    兩個特例值得寫死在這裡而不是靠呼叫端記得：
    - 評鑑缺失（137 園無切點前紀錄）→ 整個維度 a = 0，**不是 0 分**。
      0 分的語意是「評鑑全數通過」，兩者被罰率 9.2% vs 5.8%，方向相反。
    - 園級輿情缺席 → L1 的 a = 0，由 L2 撐起（§4.3）。`sri = 0` 是
      「沒被報導」不是「安全」。
    """
    if field.startswith("eval_") and row.get("eval_missing"):
        return 0
    if field == "media_sri" and not row.get("media_has_signal"):
        return 0
    return 0 if row.get(field) is None else 1


def percentile_table(rows, peer_key="institution_type"):
    """每個子指標在**同儕群內**轉百分位。回傳 {park_id: {field: P_ij}}。"""
    table = collections.defaultdict(dict)
    peers = collections.defaultdict(list)
    for row in rows:
        peers[row[peer_key]].append(row)

    for _, members in peers.items():
        for dim, indicators in INDICATORS.items():
            for field, _weight, mode in indicators:
                usable = [m for m in members if _availability(m, field)]
                values = [m.get(field) for m in usable]
                pcts = pct_zero_inflated(values) if mode == "zero" else pct_ecdf(values)
                for m, p in zip(usable, pcts):
                    table[m["park_id"]][field] = p
    return table


def dimension_score(row, dim, pcts, finance=None):
    """S_D 與 Coverage_D。SPEC §5.1。

        S_D        = Σ(u_j · a_ij · P_ij) / Σ(u_j · a_ij)
        Coverage_D = Σ(u_j · a_ij) / Σ(u_j)
    """
    if dim == "operation":
        fin = (finance or {}).get(row["park_id"])
        if not row.get("oper_applicable") or not fin:
            return None, 0.0
        return fin["operation_score"], fin.get("coverage", 1.0)

    num = den = total = 0.0
    for field, weight, _mode in INDICATORS[dim]:
        total += weight
        if _availability(row, field) and pcts.get(field) is not None:
            num += weight * pcts[field]
            den += weight
    if den == 0:
        return None, 0.0
    return num / den, den / total


def risk_raw(row, dim_scores, weights):
    """R_raw = Σ(w_k · Coverage_k · S_k) / Σ(w_k)，分母只算**適用**的維度。

    §5.1 原文是除以 `Σ(w_k · Coverage_k)`，也就是缺資料的維度整個退出分母、
    其餘維度自動重正規化。**那對「不適用」是對的，對「有缺口」是錯的**——
    見 ADR-0001。

    兩件事必須分開：

    | 情況 | 例子 | 處理 |
    |---|---|---|
    | **不適用** | 私立沒有營運維度（依法不需公告財報） | 退出分母。不然等於懲罰守法者 |
    | **有資料缺口** | 137 園查無切點前評鑑紀錄 | **留在分母**，貢獻按覆蓋率打折 |

    原文把兩者一視同仁，結果是：一家只有裁罰分數、查無評鑑紀錄的園，
    整份分數由違規維度單獨決定並被放大到滿分基準——「沒資料」被當成
    「這個維度不適用」。實測那 101 園被罰率 7.9%，**低於**母體的 10.9%，
    卻被這個機制推進 top-50 佔掉 11 個名額、只命中 1 家。

    改成分母固定後 Precision@50 從 24.0% 回到 26.0%，且不需要任何
    調出來的常數——固定給缺失維度 20 分也是 26.0%，兩者同分。
    """
    num = den = 0.0
    for dim, (score, coverage) in dim_scores.items():
        weight = weights.get(dim)
        if weight is None:                 # 該園所類型不適用此維度 → 退出分母
            continue
        den += weight                      # 適用就留在分母，不因缺資料而縮
        if score is None or coverage <= 0:
            continue
        num += weight * coverage * score
    return (num / den if den else 0.0), den


def score_all(rows, weights_by_type, finance=None,
              indicator_peer_key="institution_type", score_peer_key="peer_group"):
    """回傳每園的四維度分數、R_raw、組內百分位。tier 由呼叫端依全市名次決定。

    **兩層同儕群刻意不同**（§5.2）：子指標百分位比的是設立別（違規／評鑑／輿情
    三個維度的可得性不隨組織形態變化），最後的 `risk_score` ECDF 才用細分的
    peer_group——因為營運維度的資料可得性確實隨組織形態變化，附設幼兒園
    制度上就沒有獨立決算。
    """
    table = percentile_table(rows, indicator_peer_key)
    scored = []
    for row in rows:
        pcts = table[row["park_id"]]
        weights = weights_by_type[row["institution_type"]]
        dims = {d: dimension_score(row, d, pcts, finance) for d in INDICATORS}
        raw, weight_mass = risk_raw(row, dims, weights)
        scored.append({
            "park_id": row["park_id"],
            "pcts": pcts,
            "institution_type": row["institution_type"],
            "peer_group": row["peer_group"],
            "is_active": row["is_active"],
            "label": row["label"],
            "dimensions": dims,
            "raw": raw,
            "coverage": round(weight_mass and
                              sum(w * dims[d][1] for d, w in weights.items()
                                  if w and dims[d][0] is not None) / weight_mass, 4),
        })

    # 組內百分位，只用 is_active 的園當分母
    peers = collections.defaultdict(list)
    for s in scored:
        if s["is_active"] == 1:
            peers[s[score_peer_key]].append(s)
    for _, members in peers.items():
        pcts = pct_ecdf([m["raw"] for m in members])
        for m, p in zip(members, pcts):
            m["risk_score"] = round(p, 2)
    for s in scored:
        s.setdefault("risk_score", None)
    return scored


def assign_tiers(scored, tiers):
    """分級用**全市合併排序**，且排的是 R_raw 不是 risk_score（§5.2）。

    分數回答「同類中多危險」，分級回答「這週的 50 個名額給誰」——
    後者是全市共用的固定資源，用組內百分位切會選出 182 園。
    合併排序用未經 ECDF 壓縮的 R_raw，以保留尾端差距。
    """
    active = sorted([s for s in scored if s["is_active"] == 1],
                    key=lambda s: -s["raw"])
    for i, s in enumerate(active, 1):
        s["rank"] = i
        for name, lo, hi in tiers:
            if i >= lo and (hi is None or i <= hi):
                s["tier"] = name
                break
    for s in scored:
        s.setdefault("rank", None)
        s.setdefault("tier", None)
    return scored
