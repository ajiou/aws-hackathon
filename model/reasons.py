"""§4.6 原因碼。後端依 code 產 label、前端依 code 決定圖示，兩邊都不得自行新增。

四條規則（§4.6）：
1. 取 weight 前 3 名，**同一維度最多 2 條**——避免三條全是違規
2. weight = 特徵的維度內權重 × 維度權重 × 標準化後分數
3. `OPER_*` 必須附 `validated: false`
4. label 的 `{}` 佔位符必須全部填實值，**不得輸出帶佔位符的字串**
"""
from .scoring import INDICATORS

# code → (維度, 觸發條件, label 產生器)。條件與模板逐字對應 §4.6 的表。
def _rules(f, pct, scored_dimensions=None):
    """pct 是該園在同儕群內的子指標百分位，用來填「同類型前 N%」。"""
    top_pct = lambda field: max(1, round(100 - (pct.get(field) or 0)))
    out = []

    def add(code, dim, field, label, weight_field=None):
        out.append({"code": code, "dimension": dim, "label": label,
                    "_field": weight_field or field})

    # ---- 違規
    n = f.get("vio_pun_count") or 0
    if n >= 3 or (pct.get("vio_pun_count") or 0) >= 90:
        add("VIO_PUNISH_COUNT", "violation", "vio_pun_count",
            f"切點前已被裁罰 {n} 次，同類型前 {top_pct('vio_pun_count')}%")
    days = f.get("vio_days_since_last")
    if days is not None and days <= 365:
        add("VIO_RECENT", "violation", "vio_pun_weighted",
            f"最近一次裁罰距切點僅 {days} 天")
    if (f.get("vio_abuse_count") or 0) >= 1:
        add("VIO_ABUSE", "violation", "vio_abuse_count",
            f"曾有 {f['vio_abuse_count']} 次幼兒不當對待裁罰紀錄")
    if (f.get("vio_owner_prior_count") or 0) >= 1 and f.get("vio_sibling_count"):
        add("VIO_OWNER_PRIOR", "violation", "vio_owner_prior_count",
            f"同一負責人名下另有 {f['vio_sibling_count']} 園，"
            f"其中 {f.get('vio_sibling_pun_park_count', 0)} 園亦有裁罰紀錄")
    if f.get("vio_archetype") == "連鎖累犯":
        add("VIO_CHAIN_REPEAT", "violation", "vio_sibling_pun_count",
            f"屬連鎖累犯樣態：負責人跨 {f.get('vio_chain_size', 1)} 園"
            f"累計 {n + (f.get('vio_sibling_pun_count') or 0)} 次處分")
    if (f.get("vio_sibling_pun_count") or 0) >= 2:
        add("VIO_SIBLING", "violation", "vio_sibling_pun_count",
            f"同負責人之兄弟園累計 {f['vio_sibling_pun_count']} 次裁罰")
    cats = {k[len("vio_cat_"):]: v for k, v in f.items()
            if k.startswith("vio_cat_") and v}
    if cats and n:
        top_cat, top_n = max(cats.items(), key=lambda kv: kv[1])
        if top_n >= 2 and top_n / n >= 0.5:
            add("VIO_CAT_CONCENTRATED", "violation", "vio_pun_weighted",
                f"歷史違規集中於{top_cat}（{top_n} 次）")
    if (f.get("vio_chain_size") or 1) >= 3:
        add("VIO_CHAIN_SIZE", "violation", "vio_sibling_pun_count",
            f"同一負責人名下共 {f['vio_chain_size']} 園")

    # ---- 評鑑
    if (f.get("eval_base_fail_count") or 0) >= 1:
        add("EVAL_FAIL", "evaluation", "eval_base_fail_count",
            f"基礎評鑑 {f['eval_base_fail_count']} 次未全數指標通過")
    if f.get("eval_admin_penalty"):
        add("EVAL_ADMIN", "evaluation", "eval_admin_count",
            f"曾受幼照法第 51 條行政處分 {f['eval_admin_count']} 次")
    if (f.get("eval_followup_count") or 0) >= 1:
        add("EVAL_FOLLOWUP", "evaluation", "eval_followup_count",
            f"曾接受追蹤評鑑 {f['eval_followup_count']} 次")
    if f.get("eval_missing"):
        add("EVAL_MISSING", "evaluation", "eval_base_fail_count",
            "查無切點前評鑑紀錄，可能為新立案園所")

    # ---- 輿情
    # ADR-0001 後輿情不進分數，這三個 code 只在該維度重新被納入時才會出現。
    # 保留實作是因為 §4.6 的碼表沒有廢除，前端的圖示對應也還在。
    if not scored_dimensions or "sentiment" in scored_dimensions:
        _media_rules(f, add)
    return out


def _media_rules(f, add):
    if (f.get("media_sri") or 0) >= 15:
        add("MEDIA_PARK", "sentiment", "media_sri",
            f"近期有 {f.get('media_event_count', 1)} 起負面報導，"
            f"最高嚴重度 {f.get('media_top_severity')}")
    if f.get("media_is_burst"):
        add("MEDIA_BURST", "sentiment", "media_sri",
            "輿情近 30 天出現爆發，此前 90 天無事件")
    rank = f.get("media_town_heat_rank")
    if rank is not None and rank <= 5 and f.get("media_town_has_signal"):
        add("MEDIA_TOWN_HEAT", "sentiment", "media_town_heat_per_park",
            f"所在行政區近 90 天輿情熱度全市第 {rank}")
    return out


def build_reasons(feature_row, pcts, weights, finance=None):  # noqa: D401
    """回傳至多 3 條，依 weight 由大至小，同一維度至多 2 條。"""
    dim_weight = {d: (weights.get(d) or 0) for d in INDICATORS}
    sub_weight = {f: w for dim in INDICATORS for f, w, _ in INDICATORS[dim]}

    # 只有進得了分數的維度才產生原因碼——輿情在 ADR-0001 後不計分，
    # 讓它繼續出現在 reasons 等於在解釋一個沒有進入分數的東西。
    scored_dims = {d for d, w in weights.items() if w}
    scored = []
    for r in _rules(feature_row, pcts, scored_dims):
        field = r.pop("_field")
        score = pcts.get(field)
        if score is None:
            score = 100.0 if r["code"] == "EVAL_MISSING" else 50.0
        r["weight"] = round(sub_weight.get(field, 0.2) * dim_weight[r["dimension"]]
                            * score / 100, 4)
        r["validated"] = r["dimension"] != "operation"
        scored.append(r)

    scored.sort(key=lambda r: -r["weight"])
    out, per_dim = [], {}
    for r in scored:
        if per_dim.get(r["dimension"], 0) >= 2:
            continue
        per_dim[r["dimension"]] = per_dim.get(r["dimension"], 0) + 1
        out.append(r)
        if len(out) == 3:
            break
    assert all("{" not in r["label"] for r in out), "label 有未填的佔位符"
    return out
