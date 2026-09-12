# 小小守護員 Smart Watchdog — 系統規格書

| | |
|---|---|
| 版本 | v1.0（2026-09-12） |
| 狀態 | 待團隊 review，§13 待決事項需先拍板 |
| 適用範圍 | 新北市教保機構風險預警系統，2026 新北生成式 AI 黑客松 |

---

## 0. TL;DR — 工作切分

| 軌道 | 負責範圍 | 產出物 | 對外介面 |
|---|---|---|---|
| **DATA/ML** | ETL、特徵工程、訓練、回測 | `curated/*.json`、`model.tar.gz`、`serving/*.json` | §3 資料契約 |
| **BACKEND** | Lambda handlers、API Gateway | 8 支 API | §8 API 契約 |
| **FRONTEND** | React SPA、6 個頁面 | S3 靜態站 | §8 API 契約 + §9 |
| **CLOUD** | IaC、S3/CloudFront/OAC、IAM、CI | SAM/CDK template | §7 架構 |

三軌的唯一耦合點是 **§8 API 契約**。契約定案後，前端可用 `mock/` 下的假資料獨立開發，不必等模型。

**關鍵前提**：本系統**不做線上推論**。母體固定 1,178 園、資料日更一次，分數在離線批次算好後寫入 S3，Lambda 只做讀取／篩選／聚合。SageMaker 只用在訓練與 Batch Transform，**不部署 Endpoint**。這省掉最大的成本與部署風險。

---

## 1. 名詞與範圍定義

先定死這四個，之後所有數字才能對得起來。

### 1.1 母體（population）

| 定義 | 園數 | 用途 |
|---|---|---|
| `preschools.json` 中 `city == "新北市"` | 1,215 | 原始母體 |
| 其中 `is_active == 1` | 1,178 | **本系統母體**，所有分數、排名、分級的分母 |
| `園所裁罰特徵.json` 涵蓋 | 1,212 | 缺 3 園，ETL 需以 left join 補 0 |

> `is_active == 0` 的 37 園（已停辦）仍保留在資料庫中供查詢，但**不進排名、不進分級、不進效益曲線**。API 回傳時帶 `is_active` 欄位，前端灰階顯示。

### 1.2 切點（cutoff）

`CUTOFF = 2025-01-01`

- **特徵**只能用 `date < CUTOFF` 的資料
- **標籤**是 `date >= CUTOFF` 是否被裁罰
- 這是題目「從事後被動稽查提前為事前主動示警」的技術落實，也是評審最容易問的點

| | 筆數 | 園數 |
|---|---|---|
| 切點前裁罰 | 1,185 | 413 |
| 切點後裁罰 | 238 | 123 |
| 標籤正樣本（`園所裁罰特徵.json`） | — | **128 / 1,212 = 10.6%** |

> 123 與 128 的差異來自兩邊資料抓取時間不同（`watchdog.db` 抓到 2026-08-21，特徵檔 cutoff 版本較早）。ETL 以 `watchdog.db` 的 `punishments` 表為裁罰紀錄的**單一事實來源**，特徵檔僅用其衍生欄位。

### 1.3 分數（score）

四個分數，全部 0–100，**全部是母體內的百分位排名**，不是機率。

| 代號 | 名稱 | 輸入 | 是否進風險總分 |
|---|---|---|---|
| **A** | 教保風險分 | 基本資料 + 評鑑 + 輿情 | ✅ 權重 0.43 |
| **B+C** | 財務旗標 | 財報 + 收費明細 | ❌ 僅顯示 |
| **D** | 裁罰風險分 | 切點前裁罰紀錄 | ✅ 權重 0.57 |
| **RISK** | 風險總分 | `0.43·A + 0.57·D` | — |

用百分位而非機率的理由：基準率只有 10.6%，校準後的機率最高約 0.45，「風險 45 分」對稽查員沒有意義；百分位是「全市排第幾」，直接對應稽查排程。原始機率仍保留在 API 中（`risk.probability`）供技術驗證。

### 1.4 分級（tier）

依 `RISK` 由高至低排序，**按名次切**，不按分數切：

| 級別 | 名次 | 園數 | 對應稽查量能 |
|---|---|---|---|
| 高 | 1 – 50 | 50 | 優先實地稽查 |
| 中 | 51 – 200 | 150 | 書面查核 / 抽查 |
| 低 | 201 – 1,178 | 978 | 例行 |

> 按名次切而非按分數切，是因為稽查人力是固定的。分數門檻會隨資料更新漂移，名次不會。

---

## 2. 資料盤點

### 2.1 現有資料

| # | 資料 | 位置 | 覆蓋 | 狀態 |
|---|---|---|---|---|
| 1 | 基本資料 | `data/preschools.json` | 1,215 園 × 25 欄，座標 100% | ✅ |
| 2 | 裁罰紀錄 | `sentinel/data/watchdog.db` `punishments` | 1,423 筆 / 475 園 / 2017-05-11 ~ 2026-08-21 | ✅ |
| 3 | 裁罰衍生特徵 | `data/園所裁罰特徵_cutoff20250101.json` | 1,212 園 | ✅ |
| 4 | 累犯負責人 | `data/累犯負責人_cutoff20250101.json` | 179 人，38 人跨園，最高 15 次 | ✅ |
| 5 | 輿情文件 | `watchdog.db` `docs` | 2,900 篇（gnews 2,329 / ptt 571） | ✅ |
| 6 | 輿情實體連結 | `watchdog.db` `doc_links` / `doc_resolution` | A 161 / B 352 / C 137 / X 2,250 | ⚠ 見 §2.3 |
| 7 | 輿情 NLP 標註 | `watchdog.db` `doc_analysis` | **580 / 2,900 = 20%** | ⚠ 需補跑 |
| 8 | 收費明細 | `data/新北市...收費明細.json` | **280 園（僅公立+非營利）**，115 學年度 | ✅ |
| 9 | 非營利園財報 | `data/ocr/*.pdf` | 46 份 / 12 園 / 110–113 學年度 | ✅ 已 OCR |
| 10 | 公校決算 | `E_教育局-資料集/資料集/公校/` | 112–114 年度 | ⚠ 未進 repo |
| 11 | 評鑑結果 | `docs/評鑒抓取.xlsx` | 明細 3,353 列 / 彙總 1,101 園 | ✅ 已驗證，見 §4.2 |

> **`評鑒抓取.xlsx` 的兩個工作表**：`評鑑明細`（園名/縣市/鄉鎮/設立別/電話/核定人數/幼童專用車/評鑑學年度/評鑑完成日/評鑑結果，3,353 列）與 `園所彙總`（已預聚合的 1,101 園）。
> **本系統只用 `評鑑明細` 重算特徵，不用 `園所彙總`** —— 因為彙總欄位（`評鑑次數` / `曾非通過` / `基礎未全通過次數`）是用**全部**評鑑列算的，含切點後資料，直接拿來用就是洩漏。必須自行以 `評鑑完成日 < CUTOFF` 過濾後重算。

### 2.2 資料品質問題（ETL 必須處理）

| # | 問題 | 處置 |
|---|---|---|
| 1 | `is_free5` 可用率 **0%** | 丟棄 |
| 2 | `shuttle` 全是 tab 字元（`\t\t` × 322、空白 × 893） | 丟棄 |
| 3 | `reg_date` 有 23 園是 `1970/01/01` 佔位值 | 轉 null，另開 `reg_date_missing` 指示欄 |
| 4 | `owner` 68 園空白 | 轉 null。**不可視為同一人**，`chain_size` 計算時排除 |
| 5 | `size` / `size_in` / `size_out` 是 `"254.88平方公尺"` 字串 | regex 取數值 |
| 6 | `floor` 是 `"1樓、2樓"` 字串 | 以頓號切分後計數 |
| 7 | `is_after` 是 `"有，人數：60"` | 拆成 `has_afterschool` (bool) + `afterschool_count` (int) |
| 8 | `size_out` 缺 43%、`url` 缺 55% | 保留缺失指示欄 |
| 9 | `penalty` 欄標「有」488 園，與實際裁罰 413 園（切點前）對不上 | **兩者定義不同，不可混用**。`penalty` 僅當弱特徵，裁罰事實一律以 `punishments` 表為準 |
| 10 | `punishments.fine` 有 40 筆為 NULL（停止招生、減招） | **不可用金額當權重**，這類實質嚴重度高於多數罰鍰。用 `category` 對應嚴重度 |
| 11 | `law_detail` 約 1/3 只有條號無述文 | 已由 `backfill_categories()` 用同條號他筆回填，救回 496 筆 |

### 2.3 已知缺口與風險

| 缺口 | 影響 | 建議處置 |
|---|---|---|
| ~~評鑑資料不在本機~~ | — | ✅ **2026-09-12 結案**，見 §4.2。名稱 join 1,101/1,101 完全相符，洩漏檢查通過 |
| `doc_analysis` 只標了 20% | SRI 只算得出 40 園 | 用 Bedrock 批次補標剩下 2,320 篇（1 RPS × 2,320 ≈ 39 分鐘） |
| 輿情 A 級只綁到 40 園（3.3%） | 園級輿情特徵覆蓋率極低 | 見 §5.3 三層輿情設計——**不是用 A 級硬撐，而是用區級熱度覆蓋全母體** |
| 137 園無任何切點前評鑑紀錄 | 評鑑特徵缺失 | 這 137 園被罰率僅 5.8%（lift 0.55x），多為新立案園。加 `eval_missing` 指示欄，**不可填 0** —— 填 0 會讓新園看起來像「評鑑全通過」 |
| 私幼無財報（868 園、95.3% 的裁罰） | B+C 永遠只覆蓋 280 園 | 這是題目本身的縫，直接在簡報指出，不要假裝補得起來 |

---

## 3. 資料契約

### 3.1 S3 目錄結構

```
s3://ntpc-watchdog-<suffix>/          （private，Block Public Access 全開）
├── raw/                              原始檔備份，唯讀
│   ├── preschools.json
│   ├── watchdog.db
│   └── pdf/{park_id}/{year}.pdf      財報原檔，供前端檢視
├── curated/                          ETL 產出，模型與 API 的共同輸入
│   ├── parks.json                    1,215 筆園所主檔
│   ├── features.json                 1,212 筆 × 全特徵（含切點）
│   ├── punishments.json              1,423 筆裁罰
│   ├── media.json                    輿情彙總（園級 + 區級）
│   ├── fees.json                     280 園收費
│   └── finance.json                  12 園財務指標
├── model/
│   ├── model.tar.gz                  SageMaker XGBoost 產出
│   └── metrics.json                  回測結果
└── serving/                          ← Lambda 只讀這層
    ├── scores.json                   1,178 筆分數 + 原因 + 分級
    ├── districts.json                29 區彙總
    ├── curve.json                    稽查效益曲線資料點
    └── meta.json                     版本、資料時間、母體數
```

### 3.2 `curated/parks.json`

```json
{
  "park_id": "00ac631e-b98e-428f-9d79-d10a4ed4ed9a",
  "name": "新北市私立嘉府幼兒園",
  "type": "私立",
  "town": "土城區",
  "address": "新北市土城區...",
  "tel": "02-22xxxxxx",
  "lon": 121.4432, "lat": 25.0231,
  "count_approved": 90,
  "reg_date": "1996-08-17",
  "reg_date_missing": false,
  "is_active": 1,
  "is_public_ish": false,
  "pre_public_period": "113-115",
  "owner_key": "b3f1a9c2e8d7",
  "chain_size": 1
}
```

> **`owner_key` 是 `HMAC-SHA256(owner_name, SALT)` 的前 12 碼，不是姓名。** 見 §10.1。

### 3.3 `serving/scores.json`

這是前端最重要的一份檔案，**契約凍結後不得改欄位名**。

```json
{
  "park_id": "00ac631e-...",
  "risk": {
    "score": 87.4,
    "rank": 23,
    "tier": "高",
    "probability": 0.312,
    "a_score": 61.2,
    "d_score": 96.8,
    "model": "logistic_v1"
  },
  "reasons": [
    {"code": "D_PUNISH_COUNT", "label": "切點前已被裁罰 5 次，全市前 3%", "weight": 0.41, "block": "D"},
    {"code": "D_OWNER_PRIOR",  "label": "現任負責人名下他園亦有裁罰紀錄", "weight": 0.22, "block": "D"},
    {"code": "A_TOWN_HEAT",    "label": "所在行政區近 90 天輿情熱度全市第 4", "weight": 0.11, "block": "A"}
  ],
  "finance_flags": [
    {"code": "F_PERSONNEL_EXEC", "label": "人事費執行率 51%，為樣本最低", "severity": 3, "year": 113}
  ],
  "media": {"sri": 0.0, "has_signal": false, "town_heat_per_park": 0.42, "last_negative_at": null},
  "timeline": [
    {"date": "2023-07-03", "category": "超收", "law": "第8條第6項", "fine": 60000,
     "penalty_raw": "罰鍰：60,000元", "is_after_cutoff": false}
  ]
}
```

**`reasons` 規則**：固定回傳**至多 3 筆**，依 `weight` 由大至小。`label` 是白話句子，由後端組好，前端直接顯示，不做字串拼接。`code` 供前端決定圖示與顏色。

---

## 4. 特徵字典

所有特徵一律以 `CUTOFF = 2025-01-01` 為界計算。

### 4.1 A 區塊 — 基本資料（11 項）

| 欄位 | 型別 | 來源 | 實測 lift | 備註 |
|---|---|---|---|---|
| `type` | cat | `type` | — | 私立 12.0% / 公立 5.8% / 非營利 14.0%。**高共線性風險，見 §6.4 分層** |
| `count_approved` | int | `count_approved` | 1.15x (≥150) | |
| `area_per_child` | float | `size_in / count_approved` | 1.19x (<2 m²) | 擁擠度，師生比的代理變數 |
| `floor_count` | int | `floor` 切分計數 | 1.03x | 弱 |
| `years_since_reg` | float | `reg_date` → CUTOFF | 1.37x (5–15 年) | 非單調，建議分箱 |
| `reg_date_missing` | bool | — | — | 23 園 |
| `chain_size` | int | `owner` groupby | 1.31x (≥3) | `owner` 為 null 時設 1 |
| `is_pre_public` | bool | `pre_public != "無"` | 0.96x | 無訊號，保留供敘事 |
| `has_afterschool` | bool | `is_after` | — | |
| `monthly_fee` | int | `monthly` | 1.19x (10k–20k) | |
| `town_park_density` | int | 同區園數 | — | 稽查負荷代理變數 |

> **誠實說明**：除 `chain_size` 與 `area_per_child` 外，基本資料欄位的 lift 都在 0.85–1.2x 之間，接近雜訊。基本資料的價值在於**分層與敘事**，不在於預測力。A 線的預測力來自評鑑與輿情。

### 4.2 A 區塊 — 評鑑（6 項）✅ 已驗證

來源 `docs/評鑒抓取.xlsx` 的 `評鑑明細` 表，**僅取 `評鑑完成日 < CUTOFF` 的列**（丟棄 280 列：258 列日期在切點後、22 列「尚未接受評鑑」無日期）。

| 欄位 | 型別 | 定義 | 實測 lift |
|---|---|---|---|
| `eval_base_fail_count` | int | 「基礎評鑑－非全數指標通過」次數 | **0/1/2/3 次 → 9.2% / 12.8% / 16.7% / 28.6%，單調，最高 2.71x** |
| `eval_followup_count` | int | 「追蹤評鑑」列數 | **0/1/2 次 → 9.2% / 13.7% / 16.8%，單調，1.59x** |
| `eval_admin_penalty` | bool | 曾出現「行政處分」列（幼照法第 51 條） | **22.9% vs 10.8%，2.16x**（35 園） |
| `eval_admin_count` | int | 行政處分列數（同園可多次，反映違反次數） | 78 列 / 35 園 |
| `eval_years_since` | float | 距最近一次評鑑年數 | 待測 |
| `eval_missing` | bool | 無任何切點前評鑑紀錄 | 137 園，被罰率 5.8%（0.55x） |

**這是 A 區塊唯一的強訊號來源，也是全案第二強的特徵群（僅次於裁罰史）。**

#### 洩漏檢查結果（2026-09-12 實測）

| 檢查項 | 結果 | 判定 |
|---|---|---|
| 名稱 join（彙總 1,101 園 → `preschools.json`） | **1,101 / 1,101 完全相符** | ✅ 不需模糊比對。`系統架構.md` #10「26 園對不上名字」在此檔已不存在 |
| 「行政處分」列的日期範圍 | 2015-06-22 ~ **2024-11-20**，切點後 **0 列** | ✅ **無洩漏**。原先擔心的「行政處分欄位與裁罰同源」不成立，可安心當特徵 |
| 評鑑完成日最大值 | **2025-11-28** | ⚠ 有 258 列在切點後，**ETL 必須過濾** |
| `園所彙總` 表的預聚合欄位 | 以全部列計算，含切點後 | ❌ **不可直接使用**，必須自行重算 |

> 「行政處分」的述文本身就寫著罰鍰金額與第幾次違反（40 列含「新臺幣」字樣），例如「該園未通過基礎評鑑，且經追蹤評鑑仍未改善，第一次違反幼照法第 51 條規定，處新臺幣 6 萬元」。這是**評鑑體系內的處分**（第 51 條，未通過評鑑不改善），與裁罰紀錄的第 8/16/26/33 條（超收、師生比、不當對待）是**不同法條、不同事件**，因此不是重複計算。

### 4.3 A 區塊 — 輿情（6 項）

見 §5.3 的三層設計。

| 欄位 | 型別 | 層級 | 覆蓋率 |
|---|---|---|---|
| `sri` | float 0–100 | 園級（A 連結） | 3.3% |
| `sri_has_signal` | bool | 園級 | 100%（缺失指示） |
| `sri_top_severity` | int 1–5 | 園級 | 3.3% |
| `sri_is_burst` | bool | 園級 | 3.3% |
| `town_heat_per_park` | float | 區級（B 連結） | **100%** |
| `town_heat_rank` | int 1–29 | 區級 | **100%** |

### 4.4 D 區塊 — 裁罰（9 項）

| 欄位 | 型別 | 定義 | 實測 |
|---|---|---|---|
| `pun_count` | int | 切點前裁罰筆數 | 0 次 8.4% → 3 次 21.9% |
| `pun_weighted` | float | `Σ severity(category) × 0.5^(days/540)` | §5.2 |
| `pun_days_since_last` | int | 最近一次裁罰距切點天數 | |
| `pun_abuse_count` | int | 不當管教次數 | 0 次 10.3% → 1 次 23.1% |
| `pun_cat_*` | int × 9 | 各類別次數（師資/超收/不當管教/師生比/收費爭議/食安衛生/交通車/設施安全/其他行政） | |
| `owner_prior_count` | int | 現任負責人名下他園切點前裁罰數 | **無 8.6% → 有 14.5%（1.69x）** |
| `owner_cross_park` | bool | 負責人跨園被罰 | 38 人 |
| `sibling_pun_count` | int | 兄弟園裁罰總數 | 無 10.1% → 有 13.6% |
| `sibling_count` | int | 兄弟園數 | |
| `risk_archetype` | cat | 未被罰 730 / 單園被罰 320 / 負責人他園有前科 66 / 連鎖累犯 96 | |

### 4.5 B+C 區塊 — 財務（待補公式）

**介面已定，公式待「千」與團隊提供。** 無論公式為何，輸出格式固定：

```json
{"code": "F_XXX", "label": "白話說明", "severity": 1, "year": 113, "evidence": {}}
```

已知可算（來自 `系統架構.md` 的實測）：

| 指標 | 定義 | 已驗證 |
|---|---|---|
| 人事費執行率 | 人事費決算數 / 預算數 | N09 安興 113 = 51%（46 份最低），該年因不當對待被罰 6 萬。**n=1 正樣本，僅作旗標不進分數** |
| 代課代班費執行率 | 同上 | 用來區分「員額出缺未補」與「刻意省錢」 |
| 加班費執行率 | 同上 | |
| 收費偏離度 | 該園總收費 vs 同區同類型中位數 | 280 園可算 |

**B+C 不進 RISK 分數**，理由：有財報的 280 園中被裁罰過的僅 6 間，6 個正樣本無法訓練任何模型。它作為**旗標**顯示（💰），並在簡報中作為「題目的縫」的論據。

---

## 5. 分數計算

### 5.1 A 分數

```
p_A = sigmoid( b0 + Σ bi · xi )        xi ∈ {基本資料 11 + 評鑑 5 + 輿情 6}
A   = 100 × percentile_rank(p_A)       在 is_active==1 的 1,178 園內
```

`b` 由**切點前特徵 → 切點後標籤**的 logistic regression 擬合，L2 正則化，5-fold CV 選 C。類別變數 one-hot，連續變數標準化，缺失值以中位數填補並加缺失指示欄。

### 5.2 D 分數

```
pun_weighted = Σ_events  severity(category) × 0.5^(days_before_cutoff / 540)
p_D          = sigmoid( g0 + Σ gi · xi )     xi ∈ {裁罰 9 項}
D            = 100 × percentile_rank(p_D)
```

嚴重度對照表（**沿用 `sentinel/score_risk.py`，不用罰鍰金額**）：

| 類別 | severity |
|---|---|
| 性平事件 / 不當管教 | 5 |
| 食安衛生 / 設施安全 | 4 |
| 交通車 / 超收 / 師生比 / 師資 | 3 |
| 收費爭議 | 2 |
| 其他行政 | 1 |

半衰期 540 天（裁罰紀錄比輿情持久）。

> 為何不用金額：40 筆「停止招生」「減少招收人數」的 `fine` 是 NULL / 0，但實質嚴重度高於多數罰鍰。用金額當權重會把最嚴重的案子算成 0 分。

### 5.3 輿情量化 — 三層設計

這是本案最容易做錯的一塊。**A 級（明文點名園所）只佔 2.6%（2,900 篇中 161 篇），若只用 A 級，1,178 園中只有 40 園有輿情分數。** 正確做法是分三層，各有各的用途：

```
L1 園級（A 級連結，40 園）
    SRI = 100 × (1 − exp(−Σ w_event / 3.0))
    w_event = severity × credibility × entity_conf × source_weight × resonance × decay
    · 同園 × 同事件類型 × 同 ISO 週 = 同一起事件（去重，避免 70 篇轉載灌爆分數）
    · resonance = 1.3 if 3 家以上不同媒體都報
    · 半衰期：性平/不當管教 180d，食安/設施/交通車 120d，超收/收費/行政 60d，師資/欠薪 30d
    → 進 A 特徵：sri, sri_top_severity, sri_is_burst

L2 區級（B 級，29 區，覆蓋 100% 園所）      ★ 這層才是主力
    heat          = Σ severity × credibility × decay   （該區所有 B 級文件）
    heat_per_park = heat / 該區 is_active 園數
    → 進 A 特徵：town_heat_per_park, town_heat_rank
    → 前端：行政區熱力圖

L3 市級（C 級，137 篇）
    只算全市溫度的時間序列，不落到任何園所
    → 不進特徵，僅作前端的「全市輿情趨勢」折線
```

**B 級刻意不落到個別園所。**「板橋某私立幼兒園」不該讓板橋 162 家各背一筆嫌疑——誤標一家幼兒園，是拿政府公信力賠一家業者的商譽。B 級的作用是**縮小稽查範圍**，不是指認。

**缺失處理**：`sri == 0` 不代表該園安全，只代表沒被報導。因此一律附帶 `sri_has_signal` 缺失指示欄，讓模型自己學「沒有輿情」該給多少權重，而不是把 0 當成「低風險」。

**待補**：`doc_analysis` 只標了 580/2,900。需用 Bedrock 補標剩餘 2,320 篇，欄位為 `event_type / severity(1-5) / stance / credibility(0-1) / targets_institution / is_ad`。1 RPS 限制下約 39 分鐘，**離線批次跑，不在 API 路徑上**。

### 5.4 風險總分與權重來源

```
RISK = 0.43 × A + 0.57 × D
```

權重來源：以 `A` 與 `D` 兩個分數當唯二輸入，在**切點前資料**上跑 logistic regression，取係數正規化後得到比例。0.43 : 0.57 是由原設計 A : D = 0.3 : 0.4 移除 B+C 後重新分配而來的**初始值**，正式數字以回測結果為準，寫入 `serving/meta.json` 的 `weights` 欄位，前端從 API 讀取顯示，不寫死。

---

## 6. 模型與驗證

### 6.1 兩條模型線並行

| | v1 可解釋線 | v2 挑戰者 |
|---|---|---|
| 方法 | Logistic Regression（A、D 各一 + 合併一） | SageMaker 內建 XGBoost，全特徵單一模型 |
| 輸出 | A / D / RISK，係數即權重 | `p(被罰)` → 百分位 |
| 解釋 | 係數 × 標準化特徵值 | SHAP |
| 角色 | **主線**。可上台講、可寫進公文、失敗風險低 | 效益曲線上多一條線；若顯著較優則換主線 |

v1 先做完並且能端到端跑通，v2 才動。黑客松時間內，**一個能解釋的 2.3x 勝過一個講不清楚的 2.8x**。

### 6.2 驗證設計

```
訓練：date <  2025-01-01 的特徵  →  預測 date >= 2025-01-01 是否被裁罰
母體：1,178 園（is_active == 1）
基準率：10.6%
主指標：Precision@50   （對應「高風險」級的 50 個稽查名額）
次指標：Precision@200、Recall@200、AUC、稽查效益曲線
對照組：① 隨機抽查  ② 只看評鑑排序  ③ 只看裁罰次數排序
```

### 6.3 已實測的基準線（本次盤查產出）

| # | 排序方式 | Precision@50 | lift |
|---|---|---|---|
| 1 | 隨機抽查（期望值） | 10.6% | 1.00x |
| 2 | 只看切點前裁罰次數（純 D） | 24.0% | 2.27x |
| 3 | 只看評鑑（未通過×2 + 行政處分×3，純 A） | 24.0% | 2.27x |
| 4 | **裁罰 + 評鑑** | **28.0%** | **2.65x** |
| 5 | 裁罰 + 不當對待 + 負責人 + 評鑑（手調權重） | 26.0% | 2.46x |

**這是模型必須超過的門檻：Precision@50 ≥ 28%。** 目標 ≥ 34%（3.2x）。

三個從這張表讀出來的結論，都值得寫進簡報：

1. **第 2 列與第 3 列同分（24.0%），第 4 列卻漲到 28.0%** —— 評鑑與裁罰帶的是**不同的資訊**，不是彼此的代理變數。這從實證上證明 A / D 兩塊分開算再加權是對的設計，不是為了好講而硬拆。
2. **第 5 列比第 4 列更差。** 多加了「不當對待」與「負責人前科」兩個各自有訊號的特徵，總分反而掉 2 個百分點——手調權重會稀釋主訊號。這正是需要 logistic regression 學係數的理由。
3. 這四條線同時就是 §6.5 效益曲線的四條對照組，不必另外算。

### 6.4 兩個必須處理的建模風險

**風險 1：模型退化成「私幼就是高風險」。** 私立 868 園被罰率 12.0%，公立 294 園 5.8%。`type` 一個欄位就能解釋大半變異。

處置：分層評估。除全母體 Precision@50 外，一律同時報各設立別**組內**的 Precision@K。已實測（排序函式 = §6.3 第 4 列）：

| 分層 | 園數 | 組內基準 | Precision@K | lift | 判定 |
|---|---|---|---|---|---|
| 全母體 | 1,212 | 10.6% | P@50 = 28.0% | 2.65x | ✅ |
| **私立組內** | 868 | 12.0% | P@20 = 45.0% / P@50 = 28.0% / P@100 = 21.0% | **3.76x / 2.34x / 1.75x** | ✅ **未退化** |
| 非營利組內 | 50 | 14.0% | P@10 = 20.0% | 1.43x | ⚠ 樣本過小（7 正樣本） |
| 公立組內 | 294 | 5.8% | P@20 = 5.0% | **0.86x** | ❌ **無效** |

**結論**：模型在私幼組內依然有效（2.34x），未退化為設立別的代理。但**在公立園組內無效**（294 園僅 17 正樣本、基準 5.8%，訊號太稀薄）。

**因此排程策略必須分層**：私幼用模型排序，公立園維持例行普查。不要對外聲稱模型對所有子群都有效 —— 這是最容易被問破的地方。

> 非營利組 n=50，取 K=50 等於取全部，lift 必然為 1.00x。小樣本組必須改用較小的 K，否則指標無意義。

**風險 2：標籤洩漏。**

- ~~評鑑的「行政處分」欄位可能記的就是裁罰本身~~ → ✅ 已驗證無洩漏（切點後 0 列），且法條不同源，見 §4.2
- ⚠ **`評鑒抓取.xlsx` 的 `園所彙總` 表不可直接使用** —— 其 `曾非通過` / `基礎未全通過次數` / `追蹤評鑑次數` 是用全部 3,353 列算的，含 258 列切點後資料。必須從 `評鑑明細` 過濾後自行重算
- `preschools.json` 的 `penalty` 欄位無時間戳，可能含切點後資訊 → **只當弱特徵，且需確認其快照時間**
- 所有特徵在 ETL 階段加 assert：任何帶日期的來源，`max(date) < CUTOFF`

### 6.5 稽查效益曲線（前端「成效驗證」頁的資料）

x 軸 = 稽查家數 K（1…300），y 軸 = 該 K 之下命中的切點後被裁罰園數。四條線：

1. 完美排序（理論上限）
2. 本模型
3. 只看評鑑
4. 隨機抽查（對角線）

輸出到 `serving/curve.json`：`[{"k":50,"model":12,"eval":9,"random":5.3,"perfect":50}, ...]`

---

## 7. AWS 架構

### 7.1 全貌

```
【離線，本機或 SageMaker Notebook】            【線上，AWS us-west-2】

preschools.json ┐                             CloudFront ──(OAC)──> S3 (React build)
watchdog.db     ├─> etl.py ─> curated/*.json       │                 private bucket
裁罰特徵.json    │              │                   │
收費明細.json    │              ├─> train.py        └──/api/*──> API Gateway (HTTP API)
ocr/*.pdf       ┘              │    └─> SageMaker                     │
                               │         XGBoost Training             ▼
                               │         (ml.m5.large, ~2 min)   Lambda (Python 3.12)
                               │              │                  · 冷啟載入 serving/*.json
                               └─> score.py <─┘                  · 模組層 global cache
                                    │                            · 只做讀取/篩選/聚合
                                    └─> serving/*.json ───────────> 讀 S3
```

### 7.2 服務清單（全部已確認在 `Supported AWS Services List` 內）

| 用途 | 服務 | IAM namespace | 驗證 |
|---|---|---|---|
| 靜態站 | S3 | `s3` | ✅ |
| CDN | CloudFront + OAC | `cloudfront` | ✅ |
| API | API Gateway HTTP API | `execute-api`, `apigateway` | ✅ |
| 運算 | Lambda | `lambda` | ✅ |
| 模型訓練 | SageMaker Training Job | `sagemaker` | ✅ |
| LLM 摘要（離線） | Bedrock | `bedrock` | ✅ ≤1 RPS |
| 日誌 | CloudWatch Logs | `logs` | ✅ |
| IaC | CloudFormation / SAM | `cloudformation` | ✅ |
| 地圖底圖（備案） | Location Service | `geo`, `geo-maps` | ✅ |

**不使用**：SageMaker Endpoint（無線上推論需求）、RDS、EMR（清單內無 `emr`，僅 `emr-serverless` / `emr-containers`）、Cognito（本系統無登入需求；若日後要加，`cognito-idp` 在清單內）。

### 7.3 部署規格

| 項目 | 值 |
|---|---|
| Region | **us-west-2**（規範指定 us-east-1 或 us-west-2） |
| S3 bucket | Block Public Access **全開**，僅 CloudFront OAC 可讀 |
| CloudFront | Default root `index.html`；403/404 → `/index.html` 200（SPA routing）；`/api/*` behavior 指向 API Gateway |
| Lambda | Python 3.12、memory 512 MB、timeout 10 s、reserved concurrency 10 |
| Lambda 冷啟 | 模組層一次性 `get_object` 載入 `serving/*.json`（約 3 MB），存 module global |
| API Gateway | HTTP API（非 REST API，便宜且夠用）、CORS 限 CloudFront domain |
| 快取 | CloudFront 對 `/api/*` 設 TTL 60 s；資料日更一次，不需即時 |
| IaC | AWS SAM，單一 `template.yaml`，`sam deploy --guided` |

### 7.4 成本

批次架構下，主要成本是 SageMaker Training Job（ml.m5.large × 約 2 分鐘）與 CloudFront 流量。無 Endpoint、無 RDS、無常駐運算。黑客松額度內綽綽有餘。

---

## 8. API 契約

Base: `https://<cloudfront-domain>/api/v1`

全部 `GET`、無認證、回應 `application/json; charset=utf-8`。

**契約凍結原則**：欄位只增不改不刪。前端依此開發，`mock/` 下放同 schema 的假資料。

### 8.1 `GET /meta`

```json
{
  "version": "1.0.3",
  "generated_at": "2026-09-12T06:00:00Z",
  "cutoff": "2025-01-01",
  "population": 1178,
  "weights": {"a": 0.43, "d": 0.57},
  "tiers": {"high": [1, 50], "medium": [51, 200], "low": [201, 1178]},
  "data_freshness": {"punishments": "2026-08-21", "media": "2026-08-21", "fees": "115學年度"},
  "model": {"name": "logistic_v1", "precision_at_50": 0.28, "baseline": 0.106, "lift": 2.64}
}
```

### 8.2 `GET /parks`

全站搜尋與篩選。

| 參數 | 型別 | 說明 |
|---|---|---|
| `q` | string | 園名模糊比對 |
| `town` | string | 行政區，可重複 |
| `type` | string | `公立` / `私立` / `非營利`，可重複 |
| `tier` | string | `高` / `中` / `低`，可重複 |
| `has_finance_flag` | bool | 僅顯示有財務旗標者 |
| `sort` | string | `risk`(預設) / `name` / `pun_count` |
| `page` / `size` | int | 預設 1 / 50，size 上限 200 |

```json
{
  "total": 1178, "page": 1, "size": 50,
  "items": [
    {"park_id": "...", "name": "...", "type": "私立", "town": "土城區",
     "lon": 121.44, "lat": 25.02, "is_active": 1,
     "risk": {"score": 87.4, "rank": 23, "tier": "高"},
     "pun_count": 5, "has_finance_flag": false, "has_media_signal": false}
  ]
}
```

### 8.3 `GET /parks/{park_id}`

回傳 §3.3 `scores.json` 單筆的完整內容 + `parks.json` 的基本欄位 + `fees` + `finance` + 財報 PDF 的 presigned URL（15 分鐘效期）。

### 8.4 `GET /risk/top?k=50`

風險列表頁。回傳前 K 名，每筆含 `reasons`（至多 3 筆白話原因）與 `finance_flags`。

### 8.5 `GET /districts`

```json
{"items": [
  {"town": "板橋區", "park_count": 162, "high_risk_count": 11,
   "high_risk_ratio": 0.068, "media_heat": 4.21, "media_heat_per_park": 0.026,
   "pun_count_before_cutoff": 89}
]}
```

> 熱力圖著色用 `high_risk_ratio`（高風險園占該區比例），**不是** `high_risk_count`。用絕對數量會讓板橋這種大區永遠最紅，那是園數多不是風險高。

### 8.6 `GET /map`

GeoJSON FeatureCollection，`properties` 含 `park_id / name / tier / risk_score / pun_count / has_abuse`。支援 `?tier=` 與 `?town=` 篩選。點位 1,178 個，單次回傳約 400 KB，前端自行做 clustering。

### 8.7 `GET /curve`

§6.5 的效益曲線資料點。

### 8.8 `GET /parks/{park_id}/brief`

決策建議。**回傳離線預先產生的內容，不即時呼叫 LLM**（Bedrock 1 RPS 限制）。

```json
{"park_id": "...", "source": "template",
 "summary": "本園切點前已累積 5 次裁罰...",
 "actions": ["優先安排實地稽查，重點查核師生比"],
 "generated_at": "2026-09-12T06:00:00Z"}
```

模板版先做且必須能單獨上線；LLM 版離線批次產生後覆寫同一份 JSON，`source` 欄位標示來源（`template` 或 `llm`）。**LLM 只寫摘要，不參與打分**；產生失敗則該園退回模板版。

---

## 9. 前端規格

React + Vite，部署為純靜態站。狀態管理用 URL query string（可分享、可回上一頁），不需 Redux。

| # | 頁面 | 路由 | 主要 API | 關鍵元件 |
|---|---|---|---|---|
| 1 | 總覽 / 搜尋 | `/` | `/parks`, `/meta` | 搜尋框、多選篩選、分頁表格 |
| 2 | 地圖 | `/map` | `/map`, `/districts` | 點陣地圖 + 叢集、tier 著色、側邊欄 |
| 3 | 單園詳情 | `/park/:id` | `/parks/{id}`, `/parks/{id}/brief` | 分數卡、原因前三、裁罰時間軸、財務旗標、財報 PDF 連結 |
| 4 | 風險列表 | `/risk` | `/risk/top?k=50` | 純列表、每筆白話原因 ×3、💰 標記 |
| 5 | 行政區熱力圖 | `/districts` | `/districts` | Choropleth，著色依 `high_risk_ratio` |
| 6 | 成效驗證 | `/validation` | `/curve`, `/meta` | 四線折線圖 + Precision@50 對照表 |

### 9.1 前端必須遵守的三條

1. **分級顏色只有三色**（高/中/低）。不做連續色階——連續色階會讓使用者誤以為分數有絕對意義，它只是排名。
2. **不顯示任何人名。** 顯示「同一負責人名下 3 園」，不顯示是誰。見 §10.1。
3. **每個分數旁必須有「為什麼」。** 沒有原因的分數在公部門場景不可用，這也是評審會問的第一個問題。

### 9.2 Mock 資料

`frontend/mock/` 下放與 §8 同 schema 的假資料，`VITE_API_BASE=mock` 時走本地檔案。前端 D0 即可開工，不等後端。

---

## 10. 合規限制（來自 `黑客松競賽環境規範與限制_20260722.pdf`）

### 10.1 ⚠ 個人資料 — 最需注意的一條

> 規範第 2 條：參賽隊伍同意不會在 AWS 帳戶中使用／匯入／輸入／引入任何包含以下內容的資料：**1/ 個人資料**…

我們的 `punishments.target`（`負責人：李茹禎` / `行為人：田書后`）與 `preschools.owner` 都是**真實自然人姓名**，屬個人資料。

**處置（ETL 階段，上雲前完成）**：

| 欄位 | 上雲前 | 上雲後 |
|---|---|---|
| `owner`（姓名） | `HMAC-SHA256(name, SALT)[:12]` | `owner_key: "b3f1a9c2e8d7"` |
| `punishments.target` | 同上，另存 `target_role`（負責人/行為人） | `target_key` + `target_role` |
| `累犯負責人.姓名` | 同上 | 只上傳 `處分次數` / `涉及園數` / `是否跨園` 等衍生統計 |

- `SALT` 存本機環境變數，**不上傳 AWS、不進 git**
- 雜湊後仍可做 groupby（算 `chain_size`、`owner_prior_count`），功能完全不損失
- 前端顯示「同一負責人名下 3 園」而非姓名——這在公部門場景本來就是正確做法

### 10.2 其他規範對照

| 規範 | 對本專案的影響 | 處置 |
|---|---|---|
| 禁止公開 S3 Bucket | 前端不能用 S3 Website Hosting | CloudFront + **OAC**，bucket Block Public Access 全開 |
| Bedrock ≤ 1 RPS | 不能即時呼叫 LLM | 所有 LLM 產出離線批次預算，寫入 `serving/` |
| 僅限 us-east-1 / us-west-2 | — | 全部資源建在 **us-west-2** |
| 不建議大規模訓練 | — | 1,212 列 × ~35 特徵，XGBoost 訓練 <2 分鐘，符合 |
| 禁止上傳憑證到 GitHub | AWS 金鑰不得進 repo | `.gitignore` 已含 `.env` / `*credentials*` / `aws-env.ps1`；CI 用 OIDC 或 GitHub Secrets |
| 使用 Kiro 須保留 `/.kiro` | 若團隊有人用 Kiro | **不可**把 `/.kiro` 加進 `.gitignore` |
| 禁止匯入財務資訊 | 規範第 2 條列有「3/ 財務資訊」 | 我們處理的是**機構依法公告的決算書**，非自然人財務資料。判定為不適用，但建議向工作人員確認一次 |

---

## 11. 里程碑

估時以「一人一軌並行」為基準。

| 階段 | 內容 | DATA/ML | BACKEND | FRONTEND | CLOUD |
|---|---|---|---|---|---|
| **M0** 契約凍結 | §8 API schema 定案、mock 資料產出 | 1h | 1h | — | — |
| **M1** 資料層 | ETL → `curated/*.json`、雜湊個資、品質 assert | **4h** | — | 頁面骨架 3h | S3 + IaC 骨架 2h |
| **M2** 分數層 | A/D logistic、回測、`serving/*.json` | **5h** | Lambda 讀 S3 + 4 支 API 3h | 搜尋頁 + 列表頁 4h | CloudFront + OAC 2h |
| **M3** 完整功能 | XGBoost 挑戰者、效益曲線 | 3h | 剩餘 4 支 API 2h | 地圖 + 詳情 + 熱力圖 5h | 部署串接 2h |
| **M4** 收尾 | Bedrock 批次摘要、模板 fallback | 2h | 1h | 成效驗證頁 2h | 壓測 + 監控 1h |
| **M5** 簡報 | 敘事、Demo 腳本、Q&A 準備 | 共同 3h | | | |

**關鍵路徑**：M0 契約 → M1 ETL → M2 分數。前端在 M0 之後即可全速，不受模型進度影響。

### 11.1 降級方案（時間不足時依序砍）

1. 砍 XGBoost v2，只留 logistic v1
2. 砍 Bedrock 摘要，只留模板
3. 砍行政區熱力圖，改用地圖點位著色
4. **不可砍**：時間切分回測與效益曲線。那是本案唯一能證明「有效」的東西

---

## 12. 倉庫結構

```
aws-hackathon/
├── data/                    原始資料（已在 repo）
├── docs/                    文件（本檔在此）
├── etl/
│   ├── build_curated.py     raw → curated，含個資雜湊
│   ├── features.py          §4 特徵字典的實作
│   └── quality.py           §2.2 品質檢查 + 洩漏 assert
├── model/
│   ├── train.py             logistic v1 + XGBoost v2
│   ├── backtest.py          §6.2 驗證
│   └── score.py             curated → serving
├── backend/
│   ├── app.py               Lambda handler（單一函式，內部路由）
│   └── template.yaml        SAM
├── frontend/
│   ├── src/
│   └── mock/                §9.2 假資料
└── infra/
    └── template.yaml        S3 / CloudFront / OAC
```

---

## 13. 待決事項

需在 M0 前拍板。

| # | 問題 | 影響 | 建議 | 狀態 |
|---|---|---|---|---|
| 1 | ~~評鑑資料在誰手上~~ | — | — | ✅ 2026-09-12 到齊並驗證 |
| 2 | B+C 財務公式（「千」提供） | B+C 旗標無法實作 | 介面已定（§4.5），公式進來即可接 | ⏳ 等待 |
| 3 | 個資雜湊方案是否採用 | 不採用則違反競賽規範第 2 條 | **建議採用**，功能零損失 | 待拍板 |
| 4 | 主模型用 logistic 或 XGBoost | 決定敘事方式 | **建議 logistic 為主線**，XGBoost 當挑戰者 | 待拍板 |
| 5 | `penalty` 欄位快照時間 | 可能標籤洩漏 | 確認前先不納入特徵 | 待查 |
| 6 | ~~評鑑「行政處分」是否與裁罰同源~~ | — | 不同源（第 51 條 vs 第 8/16/26/33 條），切點後 0 列 | ✅ 已驗證 |
| 7 | 決策建議用模板或 LLM | 影響 M4 工時 | **模板先做且必須能單獨上線**，LLM 為加分項 | 待拍板 |
| 8 | 是否納入公校決算（+24 園） | B+C 覆蓋 280 → 304 園 | 時間允許再做，非關鍵路徑 | 待拍板 |
| 9 | `評鑒抓取.xlsx` 是否移入 `data/` | 目前放在 `docs/`，語意上它是資料不是文件 | 建議移到 `data/評鑒抓取.xlsx` | 待拍板 |

---

## 附錄 A — 本文件數字的來源

所有實測數字由 `data/` 與 `sentinel/data/watchdog.db` 於 2026-09-12 直接統計產出：

- 母體、欄位可用率：`preschools.json`，新北 1,215 園
- 標籤與劑量反應：`園所裁罰特徵_cutoff20250101.json`，1,212 園 / 正樣本 128
- 裁罰統計：`watchdog.db` `punishments`，1,423 筆 / 475 園
- 輿情統計：`watchdog.db` `docs` / `doc_resolution` / `doc_analysis`
- Precision@50 基準線：以切點前特徵排序，對切點後標籤計算
- AWS 服務可用性：`docs/Supported AWS Services List 20260722.xlsx` `Services List` 工作表，314 個 namespace
- 競賽限制：`docs/黑客松競賽環境規範與限制_20260722.pdf`
