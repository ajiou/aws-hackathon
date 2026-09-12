# 小小守護員 Smart Watchdog

新北市教保機構風險預警系統。2026 新北生成式 AI 黑客松。

把六個公開資料源串起來，算出新北 1,178 家幼兒園的風險排序，產出每週稽查派工單，
並且用時間切分證明它比隨機抽查準 2.65 倍。

---

## 先讀哪一份

| 你是 | 讀 |
|---|---|
| **分到任務的人** | **[`docs/ASSIGNMENTS.md`](docs/ASSIGNMENTS.md)** — 找到你的角色，整段貼給你的 AI |
| 任何人（第一次） | 本檔 + [`docs/NARRATIVE.md`](docs/NARRATIVE.md) §3.0 系統說明 |
| DATA / ML | [`docs/SPEC.md`](docs/SPEC.md) §1–§6 |
| 後端 | [`docs/SPEC.md`](docs/SPEC.md) §8 API 契約（**已凍結**） |
| 前端 | [`docs/FRONTEND.md`](docs/FRONTEND.md) 全部 |
| 雲端 | [`docs/SPEC.md`](docs/SPEC.md) §7、§10 合規限制 + [`infra/README.md`](infra/README.md) |
| 簡報要放架構圖 | [`docs/architecture.html`](docs/architecture.html) 瀏覽器開啟；投影片直接用 `docs/architecture.png`（2560×1519 透明底）或 `.svg` |
| 簡報 | [`docs/NARRATIVE.md`](docs/NARRATIVE.md) |

---

## 三分鐘跑起來

四軌互不阻塞。你只需要跑自己那一軌。

### 前端（不需要後端、不需要 AWS）

```bash
cd frontend
npm install
VITE_API_BASE=mock npm run dev        # → http://localhost:5173
```

`frontend/mock/` 已有 9 份符合 §8 契約的假資料，用真實園名與座標產生，
涵蓋邊界案例：停辦 37 園、無評鑑 140 園、無營運 905 園、裁罰超過 8 筆 25 園。

### 後端（不需要 AWS）

```bash
pip install -r requirements.txt
SERVING_DIR=./frontend/mock PORT=8000 python backend/local_server.py
curl http://localhost:8000/api/v1/meta
```

前端改接： `VITE_API_BASE=http://localhost:8000/api/v1`

### 資料與模型（不需要 AWS）

```bash
export WATCHDOG_SALT="自訂字串，不進 git"     # 個資雜湊用，見 SPEC §10.1
python etl/build_curated.py  --out ./out/curated
python model/train.py        --in ./out/curated --out ./out/model
python model/backtest.py     --in ./out/curated --model ./out/model
python model/score.py        --in ./out/curated --model ./out/model --out ./out/serving
```

財報抽表（已驗證可跑，46/46 成功）：

```bash
python etl/ocr_extract.py
```

### 雲端

```powershell
. $HOME\aws-env.ps1          # 競賽憑證，不在 repo 裡
.\infra\deploy.ps1           # 建立/更新 stack
.\infra\upload.ps1 -UseMock  # 用 mock 跑通整條路徑
.\infra\verify.ps1           # 驗收 SPEC §14.4，失敗回非零
```

不需要 SAM CLI。細節見 [`infra/README.md`](infra/README.md)。

---

## 重新產生 mock

改了 §8 契約之後要重跑，否則前端會對到舊 schema：

```bash
python frontend/mock/generate.py
```

---

## 三條不可違反的規則

這三條是系統層級的承諾，不是風格偏好。違反會出事。

1. **不上傳任何自然人姓名到 AWS。** 競賽規範第 2 條禁止匯入個人資料。
   裁罰紀錄的行為人與 `preschools.owner` 都是真名，ETL 一律以
   `HMAC-SHA256(name, SALT)` 雜湊。`etl/pii.py` 已實作，`SALT` 從環境變數讀。

2. **特徵只能用切點（2025-01-01）之前的資料。** `etl/quality.py` 的
   `assert_no_leakage` 會擋。`preschools.json` 的 `penalty` 欄位已證實是
   標籤洩漏（切點前零裁罰且標「有」的 75 園，切點後 82.7% 被罰；標「無」的
   727 園，切點後 0% 被罰），必須整欄刪除——見 [`docs/SPEC.md`](docs/SPEC.md) §2.4。

3. **S3 bucket 一律 private。** 競賽規範禁止公開 bucket，前端走
   CloudFront + OAC，不可用 S3 Website Hosting。

---

## 目錄

```
data/        原始資料（已在 repo）
docs/        SPEC / FRONTEND / NARRATIVE / 營運係數
etl/         constants · pii · quality · ocr_extract · build_curated
model/       train · backtest · score
backend/     app.py（Lambda handler）· local_server.py
frontend/    src/ · mock/
infra/       template.yaml
out/         本機執行產物（gitignore）
```

---

## 現況

| 項目 | 狀態 |
|---|---|
| 規格 | ✅ SPEC / FRONTEND / NARRATIVE 三份，交叉引用已驗證 |
| API 契約 | ✅ 已凍結（9 支） |
| Mock 資料 | ✅ 9 份，前端可直接開工 |
| 後端骨架 | ✅ 9 支路由全通，已對 mock 煙霧測試 |
| ETL 基礎 | ✅ constants / pii / quality |
| 財報抽表 | ✅ 46/46 份成功 |
| 財報抽表（公立決算 21 園） | ⬜ 待實作（表格結構已確認可抽） |
| 實際招生數 | ✅ `docs/總說明/*.md` 已是文字檔，含班級數 |
| `build_curated.py` | ⬜ 待實作 |
| 模型與回測 | ⬜ 待實作 |
| 前端 | ⬜ 待實作 |
| IaC | ✅ `infra/template.yaml` + deploy / upload / verify 腳本 |
| **已部署環境** | ✅ https://d2p0ksy36o4foe.cloudfront.net — SPEC §14.4 驗收 **11/11 通過** |
| 架構圖 | ✅ `docs/architecture.html` + `.svg` + `.png`（2× 與 1×） |
