"""非營利園財報抽表。SPEC §3.8、§5.6.5，ASSIGNMENTS B。

    python -m etl.ocr_extract --out ./out/curated

46 份 PDF（12 園 × 110–113 學年度），每份抽四張表：

| 表 | 給誰 | OCR 品質 |
|---|---|---|
| 附表一 收支餘絀表 | F 短絀率、**E 招生率**（表上直接有「招收比率」） | 乾淨 |
| 附表二 經費流用及勻支檢查表 | H 人事執行率 | 乾淨（已驗證 46/46） |
| 附表三 各學年收支預決算比較表 | F 總收入／總支出執行率 | **很髒**，靠四欄核對擋 |
| 附表五 會計師查核附表 | 查核旗標與 §5.6.7 的 80／90 下限 | 需用座標判欄位 |

## 三個非做不可的處理

1. **園所身分不能只靠名稱 join**（`營運係數.md`「資料介面與處理」）。
   12 個代號裡有 4 個（北大／安興／新林／昌福）在母體裡是**兩家同名園**，
   差在辦理單位。PDF 第一頁就印著園名、辦理單位與地址，三者一起比對才對得準。

2. **附表三的四欄核對是防 OCR 亂碼的唯一防線**（SPEC §3.10 第 8 步）。
   實例：安興 113 的總收入決算數被辨識成 `$]5,297,334`。
   驗算 `預算 + 差異 = 決算`、`決算 / 預算 = 執行率` 兩式，
   對不上就標 `needs_review`，**不進模型**。

3. **查核表的「是／否／不適用」是靠打勾的 x 座標判的**，不是文字。
   `extract_text()` 會把三欄壓成一行，勾在哪欄就看不出來了。
"""
import argparse
import collections
import glob
import json
import os
import re
import unicodedata
from pathlib import Path

import pdfplumber

DATA = Path(__file__).resolve().parent.parent / "data"
OCR_DIR = DATA / "ocr"
NUM = r"\$?\s*\(?([\d,]+)\)?"

# 附表二的 OCR 錯字對照。財報常見辨識錯誤，沿用已驗證 46/46 的那份
ALIAS = {
    "人事責": "人事費", "人事賡": "人事費", "人事費": "人事費",
    "加班費": "加班費", "加班責": "加班費", "加班賡": "加班費",
    "代課費及代班費": "代課代班費", "代課代班費": "代課代班費", "代課費": "代課代班費",
    "園長及教保服務人員薪資": "教保薪資", "圍長及教保服務人員薪資": "教保薪資",
    # 表格常把這個標籤斷成兩行，「薪資」掉到下一列——它是 H 權重最高的子指標
    # （35%，SPEC §4.4 說人事是財報唯一能接上教保風險的橋），漏抽等於 H 少掉三分之一
    "園長及教保服務人員": "教保薪資", "圍長及教保服務人員": "教保薪資",
    "園長及教保人員": "教保薪資",
    "園長及教保人員薪資": "教保薪資", "教保服務人員薪資": "教保薪資",
    "勞退金提撥": "勞退提撥", "勞退提撥": "勞退提撥",
    "資遣費": "資遣費", "資遺費": "資遣費",
}

# 附表一的欄位。OCR 常把「園」打成「圍」、「絀」打成「紬」，一併收
SUMMARY_FIELDS = {
    "教保費收入淨額": "tuition_income",
    "營運成本": "operating_cost",
    "本期稅前餘絀": "surplus_before_tax", "本期稅前餘紬": "surplus_before_tax",
    "本期稅後餘絀": "surplus_after_tax", "本期稅後餘紬": "surplus_after_tax",
    "核准招收人數": "approved_count",
    "全期核准招生人數": "approved_total", "全期招生人數": "enrolled_total",
}

# §5.6.7 嚴重度 3 的查核項目關鍵字（收入漏列、違法支出、薪資不符、加班超支、關係人、前期未改善）
# 查核項目全寫成「是否符合…」，所以答「否」＝不符合。「已完成改善」答否
# 就是 §5.6.7 的「前期缺失未改善」，關鍵字要抓「改善」而不是「未改善」。
SEVERITY_3 = ("薪資", "加班", "退休金", "勞健保", "借", "關係人",
              "改善", "漏列", "超支", "未授權")
SEVERITY_2 = ("憑證", "帳務", "流用", "預算")


def money(text):
    text = str(text).replace(",", "").replace("$", "").replace(" ", "").strip()
    negative = text.startswith("(") or text.endswith(")")
    text = text.strip("()")
    if not text.lstrip("-").isdigit():
        return None
    return -int(text) if negative else int(text)


def normalize(text):
    """全形括號、空白與常見 OCR 錯字統一，才比得動。"""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"\s+", "", text)
    for wrong, right in (("圍", "園"), ("紬", "絀"), ("蕢", "費"), ("賡", "費"), ("責", "費")):
        text = text.replace(wrong, right)
    return text


def read_identity(page):
    """第一頁：園名、辦理單位、地址。三者一起比對才能分開同名園。"""
    lines = [l.strip() for l in (page.extract_text() or "").split("\n") if l.strip()]
    name = org = address = None
    for line in lines[:8]:
        flat = normalize(line)
        if not name and flat.endswith("幼兒園"):
            name = flat
        elif not org and "辦理" in flat:
            org = flat.strip("()（）")
        elif not address and flat.startswith("地址"):
            address = flat.split("：", 1)[-1]
    return {"name": name, "org": org, "address": address}


def read_summary(pdf):
    """附表一 收支餘絀表。**E 招生率直接印在這張表上**，不必另尋來源。"""
    out = {}
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "收支餘" not in text or "核准招收人數" not in text:
            continue
        for line in text.split("\n"):
            flat = normalize(line)
            for label, key in SUMMARY_FIELDS.items():
                if flat.startswith(label) and key not in out:
                    value = money(flat[len(label):])
                    if value is not None:
                        out[key] = value
        m = re.search(r"招收比率\s*(\d+)\s*%", normalize(text))
        if m:
            out["enroll_ratio_reported"] = int(m.group(1)) / 100
        break
    return out


def read_personnel(pdf):
    """附表二 經費流用及勻支檢查表 → H 人事執行率。已驗證 46/46 可抽。"""
    out = {}
    for page in pdf.pages:
        text = page.extract_text() or ""
        # 人事費細項不只在附表二。「園長及教保服務人員薪資」多半印在財務報表附註的
        # 人事費說明裡（安興 113 是第 17 頁），那頁沒有「流用／勻支」字樣，
        # 只有「預算數 決算數 差異 執行率％」表頭——不一起掃就永遠抽不到 H 的主指標。
        flat = normalize(text)
        if not any(k in flat for k in ("流用", "勻支", "預決算檢查")) and \
                not ("預算數" in flat and "決算數" in flat and "執行率" in flat):
            continue
        for line in text.split("\n"):
            m = re.match(r"^\s*([一-鿿（）()A-Za-z、 ]{2,20}?)\s+" + NUM + r"\s+" + NUM, line)
            if not m:
                continue
            key = ALIAS.get(m.group(1).strip().replace(" ", ""))
            budget, actual = money(m.group(2)), money(m.group(3))
            if key and budget and budget > 0 and actual is not None and key not in out:
                out[key] = {"budget": budget, "actual": actual,
                            "rate": round(actual / budget, 4)}
    return out


def read_execution(pdf):
    """附表三 的總收入／總支出列 → F 執行率。

    這張表的 OCR 最髒（`$]5,297,334`、`15,05 I`），所以每一列都做四欄核對：
    `預算 + 差異 == 決算` 且 `round(決算 / 預算 × 100) == 執行率`。
    對不上就 `needs_review = True`，依 SPEC §3.10 第 8 步不進模型。
    """
    out = {}
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "預決算比較" not in normalize(text) and "決算數" not in text:
            continue
        for line in text.split("\n"):
            flat = normalize(line)
            label = "income" if flat.startswith("收入") else ("expense" if flat.startswith("支出") else None)
            if not label or label in out:
                continue
            nums = re.findall(r"\(?\$?\]?[\d, I]+\)?", line)
            values = [money(n.replace("]", "1").replace("I", "1")) for n in nums]
            values = [v for v in values if v is not None]
            if len(values) < 4:
                continue
            budget, actual, diff, rate = values[:4]
            consistent = (budget + diff == actual
                          and rate and abs(round(actual / budget * 100) - rate) <= 1)
            out[label] = {"budget": budget, "actual": actual, "diff": diff,
                          "rate_reported": rate,
                          "rate": round(actual / budget, 4) if budget else None,
                          "needs_review": not consistent}
        if out:
            break
    return out


def read_checklist(pdf):
    """附表五 會計師查核附表。**靠打勾的 x 座標判欄位**，文字抽取會把三欄壓扁。

    項目文字常常換行（第 21、26、30、32 項都是），打勾只落在第一行。
    只取打勾那一行會得到「65」「70」這種光禿禿的編號——旗標送到前端給
    稽查員看的時候等於沒寫。所以往下續接沒有打勾的行，直到下一個編號為止。
    """
    results = []
    for page in pdf.pages:
        words = page.extract_words()
        header = {w["text"].strip(): w["x0"] for w in words
                  if w["text"].strip() in ("是", "否", "不適用")}
        if len(header) < 3:
            continue
        left_edge = min(header.values()) - 5
        marks = [w for w in words if w["text"].strip() in ("V", "v", "✓", "∨", "Ｖ")]

        rows = collections.defaultdict(list)
        for w in words:
            rows[round(w["top"] / 6)].append(w)
        ordered = sorted(rows)
        marked = {round(m["top"] / 6) for m in marks}

        def line_text(key):
            return normalize("".join(w["text"] for w in
                                     sorted(rows[key], key=lambda w: w["x0"])
                                     if w["x0"] < left_edge))

        for mark in marks:
            key = round(mark["top"] / 6)
            column = min(header, key=lambda k: abs(header[k] - mark["x0"]))
            label = line_text(key)
            # 續行：往下接沒有打勾、也沒有自己的編號的行
            for nxt in ordered[ordered.index(key) + 1:]:
                if nxt in marked:
                    break
                tail = line_text(nxt)
                if not tail or re.match(r"^\d", tail):
                    break
                label += tail
            item = re.match(r"^(\d+)", label)
            results.append({"no": int(item.group(1)) if item else None,
                            "label": label, "answer": column})
    return results


def audit_flags(checklist):
    """查核表的「否」→ 旗標，不進分數（§5.6.6）。

    3,202 個判定只有 11 個「否」，而且與裁罰反向（安興 0 個否卻被罰、
    大觀 7 個否卻沒被罰）。11 個正樣本依經驗法則最多撐 1 個特徵，
    給 25% 權重會把雜訊放大。保留的是 §5.6.7 的下限規則。
    """
    flags = []
    for row in checklist:
        if row["answer"] != "否":
            continue
        text = row["label"]
        severity = 3 if any(k in text for k in SEVERITY_3) else (
            2 if any(k in text for k in SEVERITY_2) else 1)
        flags.append({"code": "OPER_AUDIT_ITEM", "no": row["no"],
                      "label": text[:60], "severity": severity})
    return flags


def resolve_park(identity, parks):
    """園名 + 辦理單位 + 地址三者比對，取總分最高者。

    **只靠名稱會出兩種錯**：12 個代號裡有 4 個（北大／安興／新林／昌福）
    在母體裡是兩家同名園，差在辦理單位；而 OCR 還會把字打錯
    （大觀 111 的封面被辨識成「大覬」），前綴比對直接落空。
    辦理單位字串最長也最不容易撞，權重給最高。
    """
    name = normalize(identity["name"] or "")
    org = re.sub(r"^[（(]?委託|辦理[）)]?$", "", normalize(identity["org"] or ""))
    addr = re.sub(r"^地址[:：]?", "", normalize(identity["address"] or ""))

    def overlap(needle, haystack):
        """容得下 OCR 錯字的相似度。實例：北大 111 的辦理單位被辨識成
        「表演藝衙教育協會」，只差一個字，精確比對就整個落空。"""
        if not needle:
            return 0.0
        return sum(1 for ch in needle if ch in haystack) / len(needle)

    def score(park):
        park_name = normalize(park["name"])
        park_addr = normalize(park["address"] or "")
        points = 0
        points += 100 * overlap(org, park_name) if overlap(org, park_name) >= 0.9 else 0
        core = name.replace("新北市", "").replace("非營利幼兒園", "")
        if core and core in park_name:
            points += 20
        elif core and sum(1 for ch in core if ch in park_name) >= max(1, len(core) - 1):
            points += 10                      # 容一個 OCR 錯字（大覬 → 大觀）
        if addr and park_addr and (addr[-8:] in park_addr or park_addr[-8:] in addr):
            points += 30
        return points

    best = max(parks, key=score)
    return best if score(best) >= 30 else None


def extract(path, parks):
    code, year = re.match(r"(N\d+[^_]+)_(\d+)\.pdf", os.path.basename(path)).groups()
    with pdfplumber.open(path) as pdf:
        identity = read_identity(pdf.pages[0])
        record = {
            "park_code": code, "school_year": int(year),
            "identity": identity,
            "summary": read_summary(pdf),
            "personnel": read_personnel(pdf),
            "execution": read_execution(pdf),
            "checklist_count": 0, "flags": [],
            "source_pdf": f"raw/pdf/{code}_{year}.pdf",
        }
        checklist = read_checklist(pdf)
    record["checklist_count"] = len(checklist)
    record["flags"] = audit_flags(checklist)
    park = resolve_park(identity, parks)
    record["park_id"] = park["park_id"] if park else None
    record["park_name"] = park["name"] if park else None
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./out/curated")
    args = ap.parse_args()
    from .sources import load_parks
    parks = [p for p in load_parks() if p["type"] == "非營利"]

    rows = []
    for path in sorted(glob.glob(str(OCR_DIR / "*.pdf"))):
        row = extract(path, parks)
        rows.append(row)
        pers = "  ".join(f"{k}={v['rate']:.0%}" for k, v in sorted(row["personnel"].items()))
        print(f"{row['park_code']:10s} {row['school_year']}  "
              f"{'✅' if row['park_id'] else '❌ 對不到園所'}  "
              f"查核{row['checklist_count']:>3}項/否{len(row['flags'])}  {pers[:74]}")

    by_code = collections.defaultdict(set)
    for r in rows:
        by_code[r["park_code"]].add(r["park_id"])
    multi = {k: v for k, v in by_code.items() if len(v) > 1}
    assert not multi, (
        f"代號跨年度對到多個 park_id：{multi}。真的換辦理單位要明確處理，"
        f"不能靠 join 自己決定——多半是 OCR 錯字讓比對落到同名的另一家。")

    unresolved = [r for r in rows if not r["park_id"]]
    assert not unresolved, f"{len(unresolved)} 份對不到 park_id：" + \
        ", ".join(f"{r['park_code']}_{r['school_year']}" for r in unresolved)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "finance_raw.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    found = collections.Counter()
    for r in rows:
        for k in r["personnel"]:
            found[k] += 1
    review = sum(1 for r in rows for v in r["execution"].values() if v["needs_review"])
    print(f"\n{len(rows)} 份、{len({r['park_id'] for r in rows})} 園，"
          f"對應 park_id {sum(1 for r in rows if r['park_id'])}/{len(rows)}")
    print("附表二各欄位出現次數：", dict(found))
    print(f"附表三四欄核對未通過（標 needs_review、不進模型）：{review} 欄")
    print(f"查核表「否」合計 {sum(len(r['flags']) for r in rows)} 項 / "
          f"{sum(r['checklist_count'] for r in rows)} 個判定")
    print(f"→ {out}/finance_raw.json")


if __name__ == "__main__":
    main()
