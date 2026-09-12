#!/usr/bin/env bash
# A 軌 + B 軌完整管線。SPEC §15.3。
#
# 為什麼跑兩次 build_curated：B 軌的 operation.py 需要 A 軌產出的
# parks.json 與 fees.json，而 A 軌的 features.json 又需要 B 軌產出的
# finance.json 來填 oper_* 欄位。先跑一次把 B 需要的東西生出來，
# B 跑完再跑第二次把營運維度接回特徵。
set -euo pipefail
: "${WATCHDOG_SALT:?請先 export WATCHDOG_SALT（個資雜湊用，不進 git）}"
OUT=${1:-./out}

# 直譯器由 $PY 決定，預設沿用可用的 python。
# Windows 的 Git Bash 下 python3 常指到 WindowsApps 的 stub 或另一版 Python，
# 與裝了 pdfplumber/openpyxl 的那一版不同，會在 B1 直接 ModuleNotFoundError。
PY=${PY:-$(command -v python || command -v python3)}
"$PY" -c "import pdfplumber, openpyxl" 2>/dev/null || {
  echo "缺相依。請執行： $PY -m pip install -r requirements.txt" >&2
  exit 1
}
echo "直譯器 $("$PY" -c 'import sys; print(sys.executable)')"

echo "── A1 建 curated（營運維度尚未接上）"
"$PY" -m etl.build_curated --out "$OUT/curated" >/dev/null

echo "── B1 非營利財報抽表（46 份 PDF，約需 2 分鐘）"
"$PY" -m etl.ocr_extract --out "$OUT/curated" | tail -5
echo "── B2 公立-獨立 總說明抽表"
"$PY" -m etl.public_finance --out "$OUT/curated" | tail -3
echo "── B3 營運維度四個同儕群"
"$PY" -m etl.operation --out "$OUT/curated"

echo "── A2 重建 curated（營運維度接回特徵）"
"$PY" -m etl.build_curated --out "$OUT/curated"
echo "── A3 回測"
"$PY" -m model.backtest --in "$OUT/curated" --out "$OUT/model"
echo "── A4 產 serving"
"$PY" -m model.score --in "$OUT/curated" --model "$OUT/model" --out "$OUT/serving"
