"""公立-獨立園的財務與招生，來源 `docs/總說明/*.md`。SPEC §5.6.2。

    python -m etl.public_finance --out ./out/curated

## 為什麼不去解那包 1.5 GB 的決算書

`docs/總說明/*.md` 是決算書第五冊每個預算單位的「總說明」，**已經是純文字且已在 repo**，
而且 F 需要的五項與 E 需要的全部都寫在裡面：

| §5.6.2 要的 | 總說明寫在哪 |
|---|---|
| 總支出預決算偏離 | 二、(二)基金用途：決算數 X 元，較預算數 Y 元 |
| 學雜費收入執行率 | 二、(一)4. 學雜費收入：決算數 X，較預算數 Y |
| 本期短絀／基金來源 | 二、(三)本期賸餘／短絀 |
| 現金淨減少／期初現金 | 三、(四)現金及約當現金之淨增加／減少、期末現金 |
| 負債／資產、淨資產年減率 | 四、(一)(二)(三)資產／負債／淨資產總額與年增減率 |
| 實際招生數（E） | 一、(一)「113 學年度上學期，實際招收幼生 260 人」 |

解壓決算書只多買到更細的科目，對 1,178 園中的 21 園。

## 數字格式

決算書用中文計數單位：`1,606 萬 8,850 元` = 16,068,850、`113 萬 817 元` = 1,130,817。
**不能直接拿 regex 抓阿拉伯數字**——`萬` 後面那段是補零的低位數，位數不固定。
"""
import argparse
import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs" / "總說明"

_CJK_NUM = r"(?:[\d,]+\s*億\s*)?(?:[\d,]+\s*萬\s*)?[\d,]*"


def parse_amount(text):
    """`1,606 萬 8,850` → 16068850。`萬` 之後不足四位要補零。"""
    text = re.sub(r"\s+", "", str(text or "")).replace(",", "")
    if not text or not re.search(r"\d", text):
        return None
    total, rest = 0, text
    for unit, scale in (("億", 10 ** 8), ("萬", 10 ** 4)):
        if unit in rest:
            head, rest = rest.split(unit, 1)
            if not head.isdigit():
                return None
            total += int(head) * scale
    tail = re.match(r"\d+", rest)
    return total + (int(tail.group(0)) if tail else 0)


def _find(text, pattern, groups=1):
    m = re.search(pattern, text)
    if not m:
        return None if groups == 1 else (None,) * groups
    if groups == 1:
        return parse_amount(m.group(1))
    return tuple(parse_amount(m.group(i + 1)) for i in range(groups))


def parse_section(name, body, year):
    """一個園所一個年度。抓不到的欄位留 None，由 §5.1 的覆蓋率加權如實回報。"""
    # 換行也要一起壓掉：決算書的排版會把「期末現金及約當現金」與金額拆成兩行，
    # 留著換行的話 `.{0,40}?` 跨不過去，那批欄位會整組抓不到。
    flat = re.sub(r"\s+", "", body)

    source_actual, source_budget = _find(
        flat, r"基金來源[：:].{0,40}?本年度決算數(" + _CJK_NUM + r")元[，,]較預算數("
        + _CJK_NUM + r")元", 2)
    use_actual, use_budget = _find(
        flat, r"基金用途[：:].{0,40}?本年度決算數(" + _CJK_NUM + r")元[，,]較預算數("
        + _CJK_NUM + r")元", 2)
    tuition_actual, tuition_budget = _find(
        flat, r"學雜費收入[：:]決算數(" + _CJK_NUM + r")元[，,]較預算數("
        + _CJK_NUM + r")元", 2)

    surplus = _find(flat, r"本期賸餘[：:].{0,40}?賸餘數(" + _CJK_NUM + r")元")
    deficit = _find(flat, r"本期短絀[：:].{0,40}?短絀數(" + _CJK_NUM + r")元")
    net_surplus = surplus if surplus is not None else (-deficit if deficit is not None else None)

    cash_increase = _find(flat, r"現金及約當現金之淨增加(" + _CJK_NUM + r")元")
    cash_decrease = _find(flat, r"現金及約當現金之淨減少(" + _CJK_NUM + r")元")
    cash_change = cash_increase if cash_increase is not None else (
        -cash_decrease if cash_decrease is not None else None)
    cash_end = _find(flat, r"期末現金及約當現金(" + _CJK_NUM + r")元")

    assets = _find(flat, r"資產總額(" + _CJK_NUM + r")元")
    liabilities = _find(flat, r"負債總額(" + _CJK_NUM + r")元")
    equity = _find(flat, r"淨資產(" + _CJK_NUM + r")元[，,]約占")
    equity_change = re.search(
        r"淨資產較上年度(增加|減少)(" + _CJK_NUM + r")元[，,]約([\d.]+)%", flat)

    # 招生：決算書沒有統一寫法，實測至少六種變體——
    #   實際招收幼生 260 人 ／ 實際招收 15 班，學生人數 249 人 ／
    #   實際招收普通班 24 班，學生人數 493 人 ／ 實際招收班級數 8 班，學生人數 184 人 ／
    #   實際招收普通班 11 班，幼生人數 284 人 ／ 實際招收 8 班，幼生人數 181 人
    # 班級數與「學生／幼生」的措辭各自獨立變動，所以兩段都要寫成可選。
    enrol = []
    for m in re.finditer(r"(\d+)學年度(上|下)學期[，,]實際招收"
                         r"(?:普通班|班級數|幼兒園)?(?:(\d+)班[，,])?"
                         r"(?:學生人數|幼生人數|幼生)?(\d+)人", flat):
        enrol.append({"school_year": int(m.group(1)), "term": m.group(2),
                      "classes": int(m.group(3)) if m.group(3) else None,
                      "students": int(m.group(4))})

    return {
        "name": name, "fiscal_year": year,
        "source_budget": source_budget, "source_actual": source_actual,
        "use_budget": use_budget, "use_actual": use_actual,
        "tuition_budget": tuition_budget, "tuition_actual": tuition_actual,
        "net_surplus": net_surplus,
        "cash_change": cash_change, "cash_end": cash_end,
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "equity_change_pct": (
            float(equity_change.group(3)) * (1 if equity_change.group(1) == "增加" else -1)
            if equity_change else None),
        "enrolment": enrol,
    }


def load_all():
    rows = []
    for path in sorted(DOCS.glob("*.md")):
        year = int(re.match(r"(\d+)", path.name).group(1))
        text = path.read_text(encoding="utf-8")
        chunks = re.split(r"^## ", text, flags=re.M)[1:]
        for chunk in chunks:
            name, _, body = chunk.partition("\n")
            rows.append(parse_section(name.strip(), body, year))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./out/curated")
    args = ap.parse_args()
    rows = load_all()

    from .sources import load_parks, normalize_public_name
    parks = {normalize_public_name(p["name"]): p for p in load_parks()
             if p["is_active"] == 1}
    for row in rows:
        park = parks.get(normalize_public_name(row["name"]))
        row["park_id"] = park["park_id"] if park else None
        row["count_approved"] = park["count_approved"] if park else None

    fields = ["source_actual", "use_actual", "tuition_actual", "net_surplus",
              "cash_change", "cash_end", "assets", "liabilities", "equity"]
    print(f"{len(rows)} 個園所年度、{len({r['name'] for r in rows})} 個園所")
    print(f"對應 park_id：{sum(1 for r in rows if r['park_id'])}/{len(rows)}"
          f"（對不到的是已停辦園，不在母體）")
    print("\n欄位覆蓋：")
    for f in fields:
        n = sum(1 for r in rows if r[f] is not None)
        print(f"  {f:<18} {n:>3}/{len(rows)}")
    print(f"  {'enrolment':<18} {sum(1 for r in rows if r['enrolment']):>3}/{len(rows)}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "public_finance.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f"→ {out}/public_finance.json")


if __name__ == "__main__":
    main()
