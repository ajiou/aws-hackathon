"""切點有兩個用途，這裡守住它們不會再被混成一個。

原本只有一個 `CUTOFF = 2025-01-01`，驗證與上線共用。結果上線的分數也看不到
切點之後的事實：吉尼爾 14 筆裁罰只有 2 筆在切點前（8 筆不當管教全在 2026），
違規維度因此算出 37.1 分、排第 210 名、標成低風險。全市 44 家在切點後被罰
不當管教的園，36 家標成低風險。

分開之後：
  VALIDATION_CUTOFF  永遠 2025-01-01。時間切分回測靠它才成立。
  CUTOFF             實際跑的切點，上線時由 WATCHDOG_CUTOFF 指定為資料日。
"""

import importlib
import subprocess
import sys
from datetime import date

import pytest


def reload_constants(monkeypatch, value):
    """在指定的 WATCHDOG_CUTOFF 下重新載入 etl.constants。

    CUTOFF 是模組層級常數，讀的是載入當下的環境變數，所以只能整個重載。
    """
    if value is None:
        monkeypatch.delenv("WATCHDOG_CUTOFF", raising=False)
    else:
        monkeypatch.setenv("WATCHDOG_CUTOFF", value)
    import etl.constants

    return importlib.reload(etl.constants)


def test_default_run_is_the_validation_split(monkeypatch):
    """不帶環境變數＝跟以前一模一樣。這條讓「改了切點機制」不會悄悄改了預設。"""
    constants = reload_constants(monkeypatch, None)
    assert constants.CUTOFF == date(2025, 1, 1)
    assert constants.CUTOFF == constants.VALIDATION_CUTOFF
    assert constants.IS_VALIDATION_RUN is True


def test_serving_cutoff_moves_only_the_running_cutoff(monkeypatch):
    """上線切點只動 CUTOFF，驗證切點是釘死的。

    VALIDATION_CUTOFF 若跟著動，Precision@50 就會變成拿「已經被罰」當特徵去
    預測「有沒有被罰」——數字會很漂亮而完全沒有意義。
    """
    constants = reload_constants(monkeypatch, "2026-08-22")
    assert constants.CUTOFF == date(2026, 8, 22)
    assert constants.VALIDATION_CUTOFF == date(2025, 1, 1)
    assert constants.IS_VALIDATION_RUN is False
    reload_constants(monkeypatch, None)


@pytest.mark.parametrize("cutoff", ["2026-08-22", "2025-06-01"])
def test_backtest_refuses_to_run_outside_the_validation_split(cutoff, tmp_path):
    """回測用非驗證切點跑，必須直接拒絕而不是產出一個會被當真的假成績。

    子行程執行：CUTOFF 在匯入時就定好了，同一個行程內改環境變數已經來不及。
    """
    env = {
        **dict(__import__("os").environ),
        "WATCHDOG_CUTOFF": cutoff,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-m", "model.backtest", "--in", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert result.returncode != 0
    assert "回測必須用驗證切點" in (result.stdout + result.stderr)
    # 拒絕要發生在讀資料之前，否則空目錄會先炸出別的錯，訊息就對不上原因。
    assert "FileNotFoundError" not in (result.stdout + result.stderr)


def test_meta_keeps_the_two_cutoffs_apart(client):
    """契約上兩個切點是分開的欄位，前端才講得清楚 26% 是怎麼量到的。"""
    meta = client.get("/api/v1/meta").json()
    assert "cutoff" in meta
    # 舊的 serving 檔沒有這兩個欄位（optional），但只要有就不能自相矛盾。
    if meta.get("validation_cutoff"):
        assert meta["validation_cutoff"] == "2025-01-01"
    if meta.get("model_basis"):
        assert "時間切分" in meta["model_basis"]
