"""個資雜湊。SPEC §10.1。

SALT 從環境變數讀，不進 git、不上 AWS。雜湊後仍可 groupby，
所以 chain_size / owner_prior_count 功能零損失。
"""
import hashlib
import hmac
import os

_SALT = None


def _salt() -> bytes:
    global _SALT
    if _SALT is None:
        v = os.environ.get("WATCHDOG_SALT", "").strip()
        assert v, (
            "環境變數 WATCHDOG_SALT 未設定。個資雜湊需要它，"
            "且它不得進 git 或上傳 AWS（SPEC §10.1、§15.3）。"
        )
        _SALT = v.encode()
    return _SALT


def hash_person(name: str | None) -> str | None:
    """自然人姓名 -> 12 碼雜湊。None / 空白回傳 None（不可視為同一人）。"""
    if not name or not str(name).strip():
        return None
    digest = hmac.new(_salt(), str(name).strip().encode(), hashlib.sha256)
    return digest.hexdigest()[:12]
