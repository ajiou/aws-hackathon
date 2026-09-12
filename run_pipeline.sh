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

echo "── A1 建 curated（營運維度尚未接上）"
python3 -m etl.build_curated --out "$OUT/curated" >/dev/null

echo "── B1 非營利財報抽表（46 份 PDF，約需 2 分鐘）"
python3 -m etl.ocr_extract --out "$OUT/curated" | tail -5
echo "── B2 公立-獨立 總說明抽表"
python3 -m etl.public_finance --out "$OUT/curated" | tail -3
echo "── B3 營運維度四個同儕群"
python3 -m etl.operation --out "$OUT/curated"

echo "── A2 重建 curated（營運維度接回特徵）"
python3 -m etl.build_curated --out "$OUT/curated"
echo "── A3 回測"
python3 -m model.backtest --in "$OUT/curated" --out "$OUT/model"
echo "── A4 產 serving"
python3 -m model.score --in "$OUT/curated" --model "$OUT/model" --out "$OUT/serving"
