# 小小守護員 Smart Watchdog — 系統規格書

| | |
|---|---|
| 版本 | v1.0（2026-09-12） |
| 狀態 | 待團隊 review，§13 待決事項需先拍板 |
| 適用範圍 | 新北市教保機構風險預警系統，2026 新北生成式 AI 黑客松 |

---

## 0. TL;DR — 工作切分

| 軌道 | 負責範圍 | 產出物 | 規格章節 | 驗收 |
|---|---|---|---|---|
| **DATA/ML** | ETL、特徵工程、訓練、回測 | `curated/*.json`、`model.tar.gz`、`serving/*.json` | §3 資料契約、§4 特徵、§5 分數、§6 驗證 | §14.1 |
| **BACKEND** | Lambda handler、API Gateway | 9 支 API | §8 API 契約 | §14.2 |
| **FRONTEND** | React SPA、6 頁 + 派工單列印頁 | S3 靜態站 | [`FRONTEND.md`](FRONTEND.md) | §14.3 |
| **CLOUD** | IaC、S3/CloudFront/OAC、IAM | SAM template | §7 架構 | §14.4 |

四軌的唯一耦合點是 **§8 API 契約**。契約定案後，前端用 `mock/` 假資料獨立開發，不必等模型；後端用本機 `serving/` 目錄開發，不必等 AWS。各軌的本機啟動方式見 §15。

### 文件導覽

| 文件 | 給誰看 | 內容 |
|---|---|---|
| **`SPEC.md`**（本檔） | 全隊 | 定義、資料、模型、API、架構、合規、驗收 |
| [`FRONTEND.md`](FRONTEND.md) | 前端 | 設計 token、元件庫、七頁版面、狀態、無障礙、列印 |
| [`NARRATIVE.md`](NARRATIVE.md) | 簡報者 | 對外說明口徑、敘事結構、七個發現、Q&A 預備、Demo 腳本 |

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
| 11 | 評鑑結果 | `data/評鑑結果.json` | 3,353 列 / 1,101 園 | ✅ 已驗證，見 §4.2 |

> **格式決議（2026-09-12）**：原始檔為 `評鑒抓取.xlsx`（含 `評鑑明細` 與 `園所彙總` 兩個工作表），已轉為 `data/評鑑結果.json` 並移入 `data/`，原始 xlsx 保留為 `data/評鑑結果_原始.xlsx`。ETL 讀 JSON，不需 openpyxl。
> **轉檔只保留 `評鑑明細`，捨棄 `園所彙總`** —— 彙總欄位（`評鑑次數` / `曾非通過` / `基礎未全通過次數`）是用**全部**評鑑列算的，含 258 列切點後資料，直接使用就是洩漏。特徵一律從明細以 `評鑑完成日 < CUTOFF` 過濾後重算。
>
> JSON 每列欄位：`園名` `鄉鎮` `設立別` `核定人數` `評鑑學年度` `評鑑完成日`（已正規化為 `YYYY-MM-DD`，22 列為 null）`評鑑結果` `類型`（基礎評鑑 2,711 / 追蹤評鑑 542 / 行政處分 78 / 尚未接受評鑑 22）`是否全數通過` `含罰鍰`。

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
| 9 | `penalty` 欄位是**標籤洩漏**，見 §2.4 | **整欄刪除**，不得以任何形式進入特徵。裁罰事實一律以 `punishments` 表為準 |
| 10 | `punishments.fine` 有 40 筆為 NULL（停止招生、減招） | **不可用金額當權重**，這類實質嚴重度高於多數罰鍰。用 `category` 對應嚴重度 |
| 11 | `law_detail` 約 1/3 只有條號無述文 | 已由 `backfill_categories()` 用同條號他筆回填，救回 496 筆 |

### 2.4 ⚠ `penalty` 欄位：已證實的標籤洩漏

`preschools.json` 的 `penalty` 欄位（值為「有」/「無」）**不是特徵，是答案**。2026-09-12 實測：

| 檢定 | 結果 |
|---|---|
| 切點前**零**裁罰、且 `penalty = 有` 的 75 園 | 切點後被罰 **62 園 = 82.7%** |
| 切點前**零**裁罰、且 `penalty = 無` 的 727 園 | 切點後被罰 **0 園 = 0.0%** |
| `penalty` vs「全期（含切點後）是否曾被裁罰」 | recall **100.0%**、precision 97.3% |
| `penalty` vs「僅切點前是否曾被裁罰」 | recall 100.0%、precision 84.6% |

**727 園標「無」而切點後被罰 0 園** —— 完美的負向預測不可能自然發生。唯一解釋是：這個欄位是**資料抓取當下（2026 年）的「是否曾被裁罰」快照**，時間點落在標籤期之後。它把答案寫在題目上。

**處置**：

1. ETL 第 3 步直接刪除 `penalty` 欄位，不轉入 `curated/`
2. `etl/quality.py` 加一條 assert：`assert "penalty" not in features_df.columns`
3. 任何模型、任何分數、任何原因碼都不得引用它

> **若誤用會發生什麼**：Precision@50 會跳到 90% 以上。數字非常好看，而且**在自己的測試集上驗證不出問題**——因為洩漏同時汙染了訓練集與測試集。只有做時間切分並回頭檢查「這個欄位的值是什麼時候產生的」才能發現。

**這順帶解掉了 `系統架構.md` 未解問題 #1**：「488 園標有，但裁罰 xlsx 只有 190 個不重複園名」。兩邊對不上不是資料品質問題，是**兩者量測的時間點不同**——`penalty` 是 2026 年的累計狀態，xlsx 是某次匯出的紀錄。

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

### 3.4 `curated/features.json`

模型的直接輸入。一列一園，欄位即 §4 特徵字典。

```json
{
  "park_id": "00ac631e-...",
  "cutoff": "2025-01-01",
  "label": false,

  "a_type": "私立",
  "a_count_approved": 90,
  "a_area_per_child": 3.42,
  "a_area_missing": false,
  "a_floor_count": 2,
  "a_years_since_reg": 28.4,
  "a_reg_date_missing": false,
  "a_chain_size": 1,
  "a_is_pre_public": true,
  "a_has_afterschool": false,
  "a_monthly_fee": 12000,
  "a_town_park_density": 162,

  "a_eval_base_fail_count": 2,
  "a_eval_followup_count": 1,
  "a_eval_admin_penalty": true,
  "a_eval_admin_count": 2,
  "a_eval_years_since": 1.8,
  "a_eval_missing": false,

  "a_sri": 0.0,
  "a_sri_has_signal": false,
  "a_sri_top_severity": null,
  "a_sri_is_burst": false,
  "a_town_heat_per_park": 0.42,
  "a_town_heat_rank": 4,

  "d_pun_count": 5,
  "d_pun_weighted": 7.83,
  "d_pun_days_since_last": 178,
  "d_pun_abuse_count": 0,
  "d_pun_cat_師資": 1, "d_pun_cat_超收": 2, "d_pun_cat_不當管教": 0,
  "d_pun_cat_師生比": 2, "d_pun_cat_收費爭議": 0, "d_pun_cat_食安衛生": 0,
  "d_pun_cat_交通車": 0, "d_pun_cat_設施安全": 0, "d_pun_cat_其他行政": 0,
  "d_owner_prior_count": 3,
  "d_owner_cross_park": true,
  "d_sibling_pun_count": 4,
  "d_sibling_count": 7,
  "d_risk_archetype": "連鎖累犯"
}
```

**命名規則**：`a_` / `d_` 前綴對應 A / D 區塊。這讓「分別訓練 A 模型與 D 模型」變成一行欄位篩選，也讓 SHAP 結果能直接歸組。

**缺失值規則**：連續變數缺失填 `null`（不是 0），並一律附 `*_missing` 布林欄。訓練時才做中位數填補。

> ⚠ **不可用 0 代表缺失。** `a_eval_base_fail_count = 0` 的語意是「評鑑全數通過」，`null` 的語意是「沒有評鑑紀錄」。這兩者的被罰率是 9.2% 與 5.8%，方向相反。

### 3.5 `curated/punishments.json`

```json
{
  "punish_id": "sha1(...)",
  "park_id": "00ac631e-...",
  "date": "2023-07-03",
  "category": "超收",
  "severity": 3,
  "law": "第8條第6項",
  "law_detail": "第8條第6項-超收逾15人幼兒園超收人數逾15人。",
  "fine": 60000,
  "penalty_raw": "罰鍰：60,000元",
  "doc_no": "北教幼字第1120xxxxxx號",
  "target_key": "b3f1a9c2e8d7",
  "target_role": "負責人",
  "is_after_cutoff": false
}
```

**`target_key` 是雜湊，不是姓名**（§10.1）。`target_role` 保留「負責人 / 行為人」的區別，因為兩者的法律意義不同。

### 3.6 `curated/media.json`

輿情三層（§5.3）各存一段。

```json
{
  "as_of": "2026-08-21",
  "park_level": [
    {"park_id": "...", "sri": 62.3, "event_count": 2, "doc_count": 3,
     "last_event_date": "2026-07-14", "top_event_type": "不當管教",
     "top_severity": 5, "is_burst": true}
  ],
  "district_level": [
    {"town": "板橋區", "heat": 4.21, "doc_count": 38,
     "candidate_pool": 162, "heat_per_park": 0.026, "rank": 4}
  ],
  "city_level": [
    {"week": "2026-W33", "heat": 12.4, "doc_count": 21}
  ]
}
```

`park_level` 只含有 A 級連結的園（約 40 筆）。**其餘園所在 `features.json` 中 `a_sri_has_signal = false`，不是 `sri = 0` 的一筆紀錄** —— 兩者在建模時的意義不同。

### 3.7 `curated/fees.json`

```json
{
  "park_id": "03825d7c-...",
  "school_year": 115,
  "type": "公立",
  "town": "萬里區",
  "items": [
    {"age": 5, "item": "學費", "period": "學期",
     "term1_full": 7000, "term2_full": 7000,
     "term1_half": 4500, "term2_half": 4500}
  ],
  "total_full_year": 40640,
  "peer_median_full_year": 42100,
  "deviation_pct": -3.5
}
```

`peer_median` 的比較群是**同行政區 + 同設立別 + 同年齡**。群內樣本 < 5 時不計算偏離度，欄位為 `null`。

### 3.8 `curated/finance.json`

```json
{
  "park_id": "...",
  "park_code": "N09",
  "school_year": 113,
  "metrics": {
    "personnel_budget": 5268163,
    "personnel_actual": 3361395,
    "personnel_exec_rate": 0.638,
    "teacher_salary_exec_rate": 0.690,
    "substitute_exec_rate": 0.301,
    "overtime_exec_rate": 0.143
  },
  "peer_median_exec_rate": 0.90,
  "flags": [
    {"code": "F_PERSONNEL_EXEC", "label": "人事費執行率 51%，為樣本最低",
     "severity": 3, "year": 113,
     "evidence": {"rate": 0.51, "peer_median": 0.90, "rank": "46/46"}}
  ],
  "source_pdf": "raw/pdf/{park_id}/113.pdf"
}
```

**公式待補**（§13 第 2 項）。介面已凍結，公式進來只需實作 `flags` 的產生邏輯。

### 3.9 `serving/districts.json` 與 `serving/curve.json`

```json
// districts.json
{"as_of": "2026-09-12", "items": [
  {"town": "板橋區", "park_count": 162, "high_risk_count": 11,
   "medium_risk_count": 24, "high_risk_ratio": 0.068,
   "media_heat": 4.21, "media_heat_per_park": 0.026, "media_rank": 4,
   "pun_count_before_cutoff": 89, "pun_park_count": 41}
]}

// curve.json
{"population": 1178, "positives": 128, "baseline": 0.106,
 "points": [
   {"k": 10, "model": 4, "eval": 3, "punish": 3, "random": 1.06, "perfect": 10},
   {"k": 50, "model": 14, "eval": 12, "punish": 12, "random": 5.3, "perfect": 50}
 ],
 "summary": {
   "precision_at_50": {"model": 0.280, "eval": 0.240, "punish": 0.240, "random": 0.106},
   "stratified": {
     "私立": {"n": 868, "baseline": 0.120, "p_at_20": 0.450, "p_at_50": 0.280, "lift_50": 2.34},
     "非營利": {"n": 50, "baseline": 0.140, "p_at_10": 0.200, "lift_10": 1.43},
     "公立": {"n": 294, "baseline": 0.058, "p_at_20": 0.050, "lift_20": 0.86}
   }
 }}
```

### 3.10 ETL 管線

`etl/build_curated.py`，八個步驟，**每步結束後執行對應的 assert，失敗即中止**。

| # | 步驟 | 輸入 | 輸出 | 出口檢查 |
|---|---|---|---|---|
| 1 | 載入母體 | `preschools.json` | 1,215 園 | `city == 新北市` 筆數 == 1215；`park_id` 唯一 |
| 2 | **個資雜湊** | `owner`、`punishments.target` | `owner_key`、`target_key` | 輸出中無任何長度 2–4 的中文姓名欄位；`SALT` 來自環境變數且非空 |
| 3 | 欄位清洗 | §2.2 的 11 項 | 型別正確的欄位 | `size_in` 全為 float 或 null；`floor_count` 全為 int 或 null；**`is_free5`、`shuttle`、`penalty` 已移除**（`penalty` 是洩漏，見 §2.4） |
| 4 | 裁罰整併 | `watchdog.db` `punishments` | `punishments.json` | 筆數 == 1423；`category` 無 null；`date` 格式一致 |
| 5 | 評鑑整併 | `data/評鑑結果.json` | 評鑑特徵 | **`max(評鑑完成日) < CUTOFF`**；join 命中率 == 100%；丟棄列數 == 280 |
| 6 | 輿情整併 | `watchdog.db` | `media.json` | `district_level` 覆蓋 29 區；`park_level` 所有 `park_id` 存在於母體 |
| 7 | 特徵組裝 | 上述全部 | `features.json` | 筆數 == 1212；**所有帶日期來源的 `max(date) < CUTOFF`**；`label` 正樣本數 == 128 |
| 8 | 財務與收費 | OCR、收費 json | `finance.json`、`fees.json` | `fees` 園數 == 280；所有 `park_id` 存在於母體 |

#### 洩漏防護（`etl/quality.py`）

```python
def assert_no_leakage(df, date_cols, cutoff):
    """任何帶日期的特徵來源，最大日期必須早於切點。"""
    for col in date_cols:
        mx = df[col].max()
        assert mx < cutoff, f"LEAK: {col} max={mx} >= cutoff={cutoff}"

def assert_no_pii(records):
    """輸出中不得含自然人姓名。"""
    banned = {"owner", "負責人", "行為人", "姓名", "target", "現任負責人"}
    for r in records:
        assert not (banned & set(r.keys())), f"PII field present: {banned & set(r.keys())}"

BANNED_COLUMNS = {"penalty"}   # §2.4 已證實的洩漏欄位

def assert_no_banned(df):
    """已知會洩漏答案的欄位，不得出現在特徵中。"""
    hit = BANNED_COLUMNS & set(df.columns)
    assert not hit, f"LEAK: banned column present: {hit}"
```

**這三個 assert 是整條管線最重要的程式碼。** 洩漏會讓所有效能數字失效；個資會違反競賽規範第 2 條。兩者都是「跑得出結果但結果不能用」的失敗，必須靠 assert 而非靠人記得。

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

來源 `data/評鑑結果.json`，**僅取 `評鑑完成日 < CUTOFF` 的列**（丟棄 280 列：258 列日期在切點後、22 列「尚未接受評鑑」無日期）。

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

### 4.6 原因碼表（reason codes）

`serving/scores.json` 的 `reasons[].code` 只能取自下表。**後端依此產生 `label`，前端依此決定圖示與顏色**，兩邊不得自行新增。

| code | block | 觸發條件 | label 模板 |
|---|---|---|---|
| `D_PUNISH_COUNT` | D | `d_pun_count >= 3` 或全市前 10% | 切點前已被裁罰 {n} 次，全市前 {pct}% |
| `D_PUNISH_RECENT` | D | `d_pun_days_since_last <= 365` | 最近一次裁罰距切點僅 {days} 天 |
| `D_ABUSE` | D | `d_pun_abuse_count >= 1` | 曾有 {n} 次幼兒不當對待裁罰紀錄 |
| `D_OWNER_PRIOR` | D | `d_owner_prior_count >= 1` | 同一負責人名下另有 {n} 園，其中 {m} 園亦有裁罰紀錄 |
| `D_CHAIN_REPEAT` | D | `d_risk_archetype == "連鎖累犯"` | 屬連鎖累犯樣態：負責人跨 {n} 園累計 {m} 次處分 |
| `D_SIBLING` | D | `d_sibling_pun_count >= 2` | 同負責人之兄弟園累計 {n} 次裁罰 |
| `D_CAT_CONCENTRATED` | D | 單一類別占該園裁罰 ≥ 50% 且 ≥ 2 次 | 歷史違規集中於{category}（{n} 次） |
| `A_EVAL_FAIL` | A | `a_eval_base_fail_count >= 1` | 基礎評鑑 {n} 次未全數指標通過 |
| `A_EVAL_ADMIN` | A | `a_eval_admin_penalty == true` | 曾受幼照法第 51 條行政處分 {n} 次 |
| `A_EVAL_FOLLOWUP` | A | `a_eval_followup_count >= 1` | 曾接受追蹤評鑑 {n} 次 |
| `A_EVAL_MISSING` | A | `a_eval_missing == true` | 查無切點前評鑑紀錄，可能為新立案園所 |
| `A_MEDIA_PARK` | A | `a_sri >= 15` | 近期有 {n} 起負面報導，最高嚴重度 {sev} |
| `A_MEDIA_BURST` | A | `a_sri_is_burst == true` | 輿情近 30 天出現爆發，此前 90 天無事件 |
| `A_TOWN_HEAT` | A | `a_town_heat_rank <= 5` | 所在行政區近 90 天輿情熱度全市第 {rank} |
| `A_CROWDED` | A | `a_area_per_child < 2.0` | 每生室內面積 {v} m²，低於全市第 15 百分位 |
| `A_CHAIN_SIZE` | A | `a_chain_size >= 3` | 同一負責人名下共 {n} 園 |
| `F_PERSONNEL_EXEC` | F | 人事費執行率 < 同儕 P10 | 人事費執行率 {pct}%，同儕中位數 {med}% |
| `F_SUBSTITUTE_EXEC` | F | 代課代班費執行率 < 0.4 | 代課代班費執行率 {pct}% |
| `F_FEE_DEVIATION` | F | `abs(deviation_pct) > 20` | 收費較同區同類型中位數{高/低} {pct}% |

**規則**：

1. `reasons` 只取 `block` 為 `A` / `D` 的前 3 名；`F` 類別一律歸入 `finance_flags`，**不進 `reasons`、不影響分數**
2. `weight` = 該特徵的標準化值 × 迴歸係數，用於排序
3. 同一 block 內最多取 2 條，確保 A 與 D 都有代表（避免三條全是裁罰）
4. label 中的所有 `{}` 佔位符必須有實際數值，**不得輸出帶佔位符的字串**
5. **任何 label 不得出現自然人姓名**（§10.1）

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
- ⚠ **原始 xlsx 的 `園所彙總` 表不可使用** —— 其 `曾非通過` / `基礎未全通過次數` / `追蹤評鑑次數` 是用全部 3,353 列算的，含 258 列切點後資料。轉出的 `data/評鑑結果.json` 已刻意只保留明細，特徵須自行過濾後重算
- ~~`preschools.json` 的 `penalty` 欄位可能含切點後資訊~~ → ❌ **已證實為嚴重洩漏，整欄刪除**，見 §2.4
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

### 7.4 IaC 資源清單

`infra/template.yaml`（SAM），資源前綴統一為 `watchdog-`。

| 邏輯名稱 | 型別 | 關鍵設定 |
|---|---|---|
| `DataBucket` | `AWS::S3::Bucket` | `PublicAccessBlockConfiguration` 四項全 `true`；`BucketEncryption` SSE-S3 |
| `SiteBucket` | `AWS::S3::Bucket` | 同上。**不啟用 WebsiteConfiguration** |
| `SiteOAC` | `AWS::CloudFront::OriginAccessControl` | `SigningBehavior: always`，`OriginAccessControlOriginType: s3` |
| `SiteBucketPolicy` | `AWS::S3::BucketPolicy` | 僅允許該 CloudFront distribution 的 `s3:GetObject` |
| `Distribution` | `AWS::CloudFront::Distribution` | 見下方 behavior 設定 |
| `ApiFunction` | `AWS::Serverless::Function` | Python 3.12 / 512 MB / 10s / `ReservedConcurrentExecutions: 10` |
| `HttpApi` | `AWS::Serverless::HttpApi` | CORS `AllowOrigins` 限 CloudFront domain |
| `ApiFunctionRole` | `AWS::IAM::Role` | 見下方最小權限 |

#### CloudFront behaviors

| Path pattern | Origin | 設定 |
|---|---|---|
| `/api/*` | HttpApi | TTL 60s；轉發 query string；不轉發 cookie |
| `/*`（預設） | SiteBucket via OAC | TTL 3600s；`index.html` 為 root object |

**SPA 路由**：`CustomErrorResponses` 將 403 與 404 對應到 `/index.html` 並回傳 **200**。缺這段的話 `/park/xxx` 直接輸入網址會 404。

#### Lambda 最小權限

```yaml
Policies:
  - Statement:
      - Effect: Allow
        Action: s3:GetObject
        Resource: !Sub "${DataBucket.Arn}/serving/*"
      - Effect: Allow
        Action: s3:GetObject          # 財報 PDF 的 presigned URL
        Resource: !Sub "${DataBucket.Arn}/raw/pdf/*"
```

**只給 `serving/` 與 `raw/pdf/` 的讀取權，不給 `curated/`、不給 `model/`、不給任何寫入權。** API 是純讀取服務，不需要更多。

#### 部署順序

```bash
# 1. 基礎設施
sam deploy --template infra/template.yaml --stack-name watchdog-infra \
           --region us-west-2 --capabilities CAPABILITY_IAM

# 2. 資料（本機 ETL 產出後上傳）
aws s3 sync ./out/curated s3://<DataBucket>/curated/
aws s3 sync ./out/serving s3://<DataBucket>/serving/

# 3. 前端
cd frontend && npm run build
aws s3 sync dist/ s3://<SiteBucket>/ --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

### 7.5 成本

批次架構下，主要成本是 SageMaker Training Job（ml.m5.large × 約 2 分鐘）與 CloudFront 流量。無 Endpoint、無 RDS、無常駐運算。黑客松額度內綽綽有餘。

---

## 8. API 契約

Base: `https://<cloudfront-domain>/api/v1`

全部 `GET`、無認證、回應 `application/json; charset=utf-8`。

**契約凍結原則**：欄位只增不改不刪。前端依此開發，`mock/` 下放同 schema 的假資料。

### 8.0 通用規範

#### 回應標頭

| 標頭 | 值 | 用途 |
|---|---|---|
| `Content-Type` | `application/json; charset=utf-8` | |
| `x-request-id` | UUID | 前端錯誤畫面顯示此值，可對 CloudWatch Logs |
| `x-data-version` | 同 `meta.version` | 前端偵測資料更新 |
| `Cache-Control` | `public, max-age=60` | CloudFront 與瀏覽器皆快取 60 秒 |

#### 錯誤格式

所有非 2xx 回應統一格式：

```json
{"error": {"code": "PARK_NOT_FOUND", "message": "查無此園所", "request_id": "..."}}
```

| HTTP | code | 情境 |
|---|---|---|
| 400 | `INVALID_PARAM` | 參數格式錯誤（如 `k=abc`） |
| 404 | `PARK_NOT_FOUND` | `park_id` 不存在 |
| 500 | `INTERNAL_ERROR` | 未預期錯誤 |
| 503 | `DATA_NOT_READY` | `serving/` 尚未產生（首次部署） |

**錯誤訊息不得洩漏 AWS 資源名稱、bucket 名稱或 stack trace。**

#### 分頁

`page` 從 1 開始，`size` 預設 50、上限 200。回應一律含 `total` / `page` / `size`。

#### Lambda 實作要點

```python
# backend/app.py — 單一 Lambda 函式，內部路由
_CACHE = {}   # 模組層全域，跨 invocation 存活

def _load(key: str) -> dict:
    """冷啟時一次性載入 serving/*.json，之後走記憶體。"""
    if key not in _CACHE:
        obj = s3.get_object(Bucket=BUCKET, Key=f"serving/{key}.json")
        _CACHE[key] = json.loads(obj["Body"].read())
    return _CACHE[key]
```

| 要點 | 說明 |
|---|---|
| 單一函式 | 9 支 API 共用一個 Lambda，內部依 `rawPath` 路由。減少冷啟次數與部署複雜度 |
| 模組層快取 | `serving/*.json` 共約 3 MB，冷啟載入一次，後續 invocation 直接命中記憶體 |
| 快取失效 | 資料更新後手動 `aws lambda update-function-configuration` 改一個環境變數即可強制冷啟 |
| 不連資料庫 | 全程只讀 S3。無 RDS、無 DynamoDB（v1） |
| 逾時 | 10s。實際 p99 應 < 200ms（記憶體命中） |

> **為什麼不用 DynamoDB**：母體 1,178 筆、資料日更一次、查詢模式固定。把 3 MB JSON 讀進記憶體後用 Python 篩選，比維護一套 DynamoDB schema 與 GSI 更快也更少出錯。若 v2 需要即時寫入（稽查結果回填）再引入。

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

單園決策建議。**回傳離線預先產生的內容，不即時呼叫 LLM**（Bedrock 1 RPS 限制）。

```json
{"park_id": "...", "source": "template",
 "summary": "本園切點前已累積 5 次裁罰...",
 "reasons": ["切點前已被裁罰 5 次，全市前 3%"],
 "actions": [
   {"focus": "師生比", "why": "歷史違規集中於第 16 條第 4 項（3 次）"},
   {"focus": "實際招收人數 vs 核定 120 人", "why": "歷史有超收 2 次"}
 ],
 "generated_at": "2026-09-12T06:00:00Z"}
```

模板版先做且必須能單獨上線；LLM 版離線批次產生後覆寫同一份 JSON，`source` 欄位標示來源（`template` 或 `llm`）。**LLM 只寫白話文，不參與打分**；產生失敗則該園退回模板版。

### 8.9 `GET /worklist?week=2026-W37&k=50` ★ 主線產出

**稽查派工單。** 這是本系統對痛點 4（人力負擔重與決策支援不足）的正面回答，也是整個作品從「儀表板」變成「工作流程」的關鍵端點。

```json
{
  "week": "2026-W37",
  "generated_at": "2026-09-12T06:00:00Z",
  "model": {"name": "logistic_v1", "precision_at_50": 0.28, "baseline": 0.106},
  "items": [
    {
      "seq": 1,
      "park_id": "...",
      "name": "○○幼兒園",
      "town": "板橋區", "type": "私立", "count_approved": 120,
      "address": "...", "tel": "...",
      "risk": {"rank": 3, "tier": "高", "score": 91.2},
      "reasons": [
        "切點前已被裁罰 5 次，全市前 3%",
        "基礎評鑑 2 次未全數通過，並曾受幼照法第 51 條行政處分",
        "同一負責人名下另有 7 園，其中 3 園亦有裁罰紀錄"
      ],
      "actions": [
        {"focus": "師生比", "why": "歷史違規集中於第 16 條第 4 項（3 次）"},
        {"focus": "實際招收人數 vs 核定 120 人", "why": "歷史有超收 2 次"}
      ],
      "attachments": {"punishment_count": 6, "evaluation_count": 4}
    }
  ]
}
```

**三條硬規則**：

1. **`reasons` 恰好 3 條、`actions` 至多 3 條。** 派工單是要被人讀完的，不是資料傾印。
2. **任何欄位不得出現自然人姓名**（見 §10.1）。說「同一負責人名下另有 7 園」，不說是誰。
3. **`actions` 必須對應到具體法條或核定數字**，不能是「加強查核」這種空話。來源是該園歷史裁罰的 `category` 與 `law` 分布。

`week` 省略時回傳當週。`k` 預設 50（對應「高風險」級的稽查名額），上限 200。

---

## 9. 前端規格

**完整規格見 [`FRONTEND.md`](FRONTEND.md)** —— 設計 token、元件庫、七頁版面、狀態設計、無障礙、列印樣式。本節只保留與 API 契約直接相關的對應關係，避免兩份文件產生分歧。

### 9.1 頁面與 API 對應

| # | 頁面 | 路由 | 依賴的 API | FRONTEND.md |
|---|---|---|---|---|
| 1 | 總覽 / 搜尋 | `/` | `GET /meta`、`GET /parks` | FRONTEND §5.1 |
| 2 | 風險列表 | `/risk` | `GET /risk/top` | FRONTEND §5.2 |
| 3 | 地圖 | `/map` | `GET /map`、`GET /districts` | FRONTEND §5.3 |
| 4 | 單園詳情 | `/park/:id` | `GET /parks/{id}`、`GET /parks/{id}/brief` | FRONTEND §5.4 |
| 5 | 行政區熱力圖 | `/districts` | `GET /districts` | FRONTEND §5.5 |
| 6 | 成效驗證 | `/validation` | `GET /curve`、`GET /meta` | FRONTEND §5.6 |
| 7 | **稽查派工單** ★ | `/worklist` | `GET /worklist` | FRONTEND §5.7 |

### 9.2 三條不可違反的前端規則

這三條寫在 SPEC 而非只寫在 FRONTEND，因為它們是**系統層級的承諾**，不是設計偏好。

1. **分級只有三色，且不含綠色。** 低風險的語意是「本週不優先稽查」，不是「安全」或「合格」。系統無權發出合格證。同時不做連續色階——分數是百分位排名，不是絕對量值。
2. **不顯示任何自然人姓名。** API 回傳的是 `owner_key` 雜湊值，前端沒有姓名可顯示。見 §10.1。
3. **每個分數旁必須有「為什麼」。** 任何顯示風險分數的畫面，同一視野內必須可見 `reasons`。公部門依分數調度稽查人力，被稽查方有權知道理由。

### 9.3 稽查派工單的內容規則

版面設計見 [`FRONTEND.md`](FRONTEND.md) §5.7。以下三條是**後端產生內容時的契約**：

| 規則 | 說明 |
|---|---|
| `reasons` 恰好 3 條 | 超過 3 條沒有人會讀完。後端負責取前 3 名，前端不再篩選 |
| `actions` 必須指向法條或核定數字 | 「加強查核」是廢話。正確形式是「師生比 — 歷史違規集中於第 16 條第 4 項（3 次）」。來源是該園歷史裁罰的 `category` 與 `law` 分布 |
| 全文不得出現自然人姓名 | §10.1。後端輸出前須通過 `assert_no_pii` |

派工單頁首必須印出模型名稱與 Precision@50 —— 稽查員有權知道這份名單的準確度，這也是可稽核性的一部分。

### 9.4 Mock 資料

`frontend/mock/` 下放與 §8 同 schema 的假資料，`VITE_API_BASE=mock` 時走本地檔案。前端 D0 即可開工，不等後端與模型。必須涵蓋的邊界案例見 [`FRONTEND.md`](FRONTEND.md) §9.4。

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
| **M2** 分數層 | A/D logistic、回測、**派工單原因與建議產生器** | **6h** | Lambda 讀 S3 + 4 支 API 3h | 搜尋頁 + 列表頁 4h | CloudFront + OAC 2h |
| **M3** 完整功能 | XGBoost 挑戰者、效益曲線 | 3h | 剩餘 5 支 API（含 `/worklist`）3h | 地圖 + 詳情 + 熱力圖 5h + **派工單列印頁 2h** | 部署串接 2h |
| **M4** 收尾 | Bedrock 輿情補標 2,320 篇、白話文生成 | 3h | 1h | 成效驗證頁 2h | 壓測 + 監控 1h |
| **M5** 簡報 | 敘事、Demo 腳本、Q&A 準備 | 共同 3h | | | |

**關鍵路徑**：M0 契約 → M1 ETL → M2 分數。前端在 M0 之後即可全速，不受模型進度影響。

### 11.1 降級方案（時間不足時依序砍）

1. 砍 XGBoost v2，只留 logistic v1
2. 砍派工單的 LLM 白話文生成，只留模板（**派工單本身不可砍**）
3. 砍行政區熱力圖，改用地圖點位著色
4. **不可砍（三項）**：
   - **時間切分回測與效益曲線** —— 本案唯一能證明「有效」的東西
   - **稽查派工單** —— 痛點 4 的唯一對應功能，也是作品定位的關鍵
   - **輿情補標 2,320 篇** —— 不補標則 L1 園級輿情只覆蓋 40 園（3.3%），形同虛設

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
├── backend/
│   └── local_server.py      §15.2 本機開發用，讀本機 serving/
├── frontend/                詳見 FRONTEND.md §9.2
│   ├── src/
│   └── mock/                §9.2 假資料
├── infra/
│   └── template.yaml        §7.4 S3 / CloudFront / OAC / Lambda / HttpApi
└── out/                     本機執行產物（gitignore）
    ├── curated/
    ├── model/
    └── serving/
```

> `backend/` 底下同時有 `app.py`（Lambda handler）、`template.yaml`（SAM 函式定義）與 `local_server.py`。`infra/template.yaml` 只管基礎設施，兩者以 `!ImportValue` 串接。

---

## 13. 待決事項

**除第 2 項外全數結案（2026-09-12）。M0 契約可凍結，四軌同時開工。**

| # | 問題 | 影響 | 建議 | 狀態 |
|---|---|---|---|---|
| 1 | ~~評鑑資料在誰手上~~ | — | — | ✅ 2026-09-12 到齊並驗證 |
| 2 | B+C 財務公式（「千」提供） | B+C 旗標無法實作 | 介面已定（§4.5），公式進來即可接 | ⏳ **唯一未決項** |
| 3 | ~~個資雜湊方案~~ | — | **採用 HMAC-SHA256**，保留 `owner_key` 以維持跨園連結能力 | ✅ 2026-09-12 拍板 |
| 4 | ~~主模型選型~~ | — | **Logistic 為主線**，XGBoost 為挑戰者放進效益曲線 | ✅ 2026-09-12 拍板 |
| 5 | ~~`penalty` 欄位快照時間~~ | — | 已實證為嚴重洩漏（§2.4），**整欄刪除** | ✅ 2026-09-12 結案 |
| 6 | ~~評鑑「行政處分」是否與裁罰同源~~ | — | 不同源（第 51 條 vs 第 8/16/26/33 條），切點後 0 列 | ✅ 已驗證 |
| 7 | ~~決策建議用模板或 LLM~~ | — | 派工單已升為主線（§8.9、§9.3）。模板版必須能單獨上線，LLM 只潤飾白話文 | ✅ 2026-09-12 拍板 |
| 8 | ~~是否納入公校決算~~ | — | **不納入**。公立園僅 3 筆裁罰，對驗證無貢獻；時間投入派工單效益更高 | ✅ 2026-09-12 拍板 |
| 9 | ~~評鑑檔位置~~ | — | 已轉為 `data/評鑑結果.json`，原始檔留存為 `data/評鑑結果_原始.xlsx` | ✅ 2026-09-12 完成 |

---

## 14. 驗收標準

每一軌「完成」的定義。每項都要能被另一個人獨立驗證，不是自己說了算。

### 14.1 DATA/ML

- [ ] `etl/build_curated.py` 一次跑完無 assert 失敗，產出 8 個 `curated/*.json`
- [ ] **洩漏檢查通過**：所有帶日期來源 `max(date) < 2025-01-01`
- [ ] **個資檢查通過**：`curated/` 與 `serving/` 全文 grep 不到任何自然人姓名欄位
- [ ] `features.json` 1,212 筆，正樣本 128 筆
- [ ] 評鑑 join 命中率 100%（1,101 / 1,101）
- [ ] 回測 Precision@50 **≥ 28.0%**（否則不如 §6.3 的手調基準，模型沒有價值）
- [ ] 分層結果（私立 / 公立 / 非營利）已產出並寫入 `curve.json`
- [ ] `serving/scores.json` 每筆的 `reasons` 皆 1–3 條，`code` 全部在 §4.6 表內，無佔位符殘留

### 14.2 BACKEND

- [ ] 9 支 API 皆可回應，schema 與 §8 完全一致
- [ ] 冷啟 < 3s，熱請求 p99 < 200ms
- [ ] 錯誤格式統一，且不洩漏 bucket 名稱或 stack trace
- [ ] `x-request-id` 每個回應都有，且能在 CloudWatch Logs 查到對應紀錄
- [ ] `/parks/{id}` 傳入不存在的 id 回 404 而非 500
- [ ] `/worklist` 回傳內容不含任何自然人姓名
- [ ] IAM role 僅有 `serving/*` 與 `raw/pdf/*` 的 `s3:GetObject`

### 14.3 FRONTEND

見 [`FRONTEND.md`](FRONTEND.md) §10。摘要：

- [ ] 七頁皆可直接以網址抵達；篩選狀態寫進 URL 可分享
- [ ] 任何顯示分數處同視野可見原因
- [ ] 四種狀態（載入 / 空 / 錯誤 / 缺資料）全部實作
- [ ] 派工單列印每項不跨頁，灰階可讀
- [ ] axe DevTools 零 critical；JS bundle < 250 KB gzip

### 14.4 CLOUD

- [ ] `sam deploy` 從零可重建全部資源
- [ ] **S3 Block Public Access 四項全開**，`aws s3api get-public-access-block` 驗證
- [ ] 直接存取 S3 物件 URL 回 403，經 CloudFront 回 200
- [ ] `/park/xxx` 直接輸入網址正常載入（SPA fallback 生效）
- [ ] 全部資源在 **us-west-2**
- [ ] CloudWatch Logs 保留期已設定（建議 7 天，省成本）

### 14.5 端到端

- [ ] 從 `git clone` 到本機看到完整畫面，步驟 ≤ 5 且文件化（§15）
- [ ] Demo 腳本（`NARRATIVE.md` §7）可在 8 分鐘內完整走完
- [ ] 斷網情況下 Demo 仍可進行（mock 模式）

---

## 15. 本機開發

四軌各自的啟動方式。**任何一軌都不應該為了啟動而等另一軌。**

### 15.1 前端（不需要後端）

```bash
cd frontend
npm install
VITE_API_BASE=mock npm run dev      # → http://localhost:5173
```

讀 `frontend/mock/*.json`，七頁全部可操作。

### 15.2 後端（不需要 AWS）

```bash
cd backend
pip install -r requirements.txt
SERVING_DIR=../out/serving python local_server.py   # → http://localhost:8000
```

`local_server.py` 用 Flask 包同一個 `app.handler`，從本機目錄讀 `serving/*.json` 而非 S3。前端改 `VITE_API_BASE=http://localhost:8000/api/v1` 即可串接。

### 15.3 ETL 與模型

```bash
export WATCHDOG_SALT="<本機自訂，不進 git>"
python etl/build_curated.py  --out ./out/curated
python model/train.py        --in ./out/curated --out ./out/model
python model/backtest.py     --in ./out/curated --model ./out/model
python model/score.py        --in ./out/curated --model ./out/model --out ./out/serving
```

全程本機執行，不需要 AWS 憑證。`./out/` 已在 `.gitignore`。

### 15.4 AWS 憑證

競賽帳號的憑證是短期 STS token，**不可進 git**。建議放在專案外的檔案再 source：

```powershell
# 存在 repo 之外，例如 %USERPROFILE%\aws-env.ps1
$Env:AWS_DEFAULT_REGION="us-west-2"
$Env:AWS_ACCESS_KEY_ID="..."
$Env:AWS_SECRET_ACCESS_KEY="..."
$Env:AWS_SESSION_TOKEN="..."
```

`.gitignore` 已涵蓋 `.env`、`*credentials*`、`aws-env.ps1`、`.aws/`。

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
