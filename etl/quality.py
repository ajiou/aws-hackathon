"""ETL 出口檢查。SPEC §3.10。

這三個 assert 是整條管線最重要的程式碼：洩漏與個資都是「跑得出結果
但結果不能用」的失敗，靠人記得不可靠。
"""
from .constants import CUTOFF, DROP_COLUMNS

PII_FIELDS = {"owner", "負責人", "行為人", "姓名", "target",
              "現任負責人", "被罰負責人", "owner_name", "target_name"}


def assert_no_leakage(records, date_fields, cutoff=CUTOFF):
    """任何帶日期的特徵來源，最大日期必須早於切點。"""
    for field in date_fields:
        values = [r[field] for r in records if r.get(field)]
        if not values:
            continue
        mx = max(values)
        assert str(mx) < cutoff.isoformat(), (
            f"LEAK: {field} max={mx} >= cutoff={cutoff}. "
            f"特徵不得使用切點當日或之後的資料。"
        )


def assert_no_pii(records):
    """輸出中不得含自然人姓名。競賽規範第 2 條。"""
    for r in records:
        hit = PII_FIELDS & set(r.keys())
        assert not hit, (
            f"PII: 欄位 {hit} 含自然人姓名，不得上傳 AWS。"
            f"請改用 HMAC-SHA256 雜湊後的 owner_key / target_key（SPEC §10.1）。"
        )


def assert_no_banned(records):
    """已證實會洩漏答案的欄位，不得出現在特徵中。"""
    for r in records:
        hit = DROP_COLUMNS & set(r.keys())
        assert not hit, f"LEAK: 欄位 {hit} 已知洩漏或無效，必須刪除（SPEC §2.4）。"


def assert_population(records, expected, label=""):
    assert len(records) == expected, f"{label} 筆數 {len(records)} != 預期 {expected}"
