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
| [`NARRATIVE.md`](NARRATIVE.md) | 簡報者 | 對外說明口徑、敘事結構、九個發現、Q&A 預備、Demo 腳本 |
| [`ASSIGNMENTS.md`](ASSIGNMENTS.md) | 全隊 | 五個角色的任務簡報，可整段貼給各自的 AI |

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

**四個維度**，各自 0–100，加權後轉為**同類型組內百分位**。完整定義見 §5。

| 維度 | 輸入 | 公立/非營利 | 私立 |
|---|---|--:|--:|
| **違規** | 切點前裁罰、負責人前科、兄弟園 | 35% | 50% |
| **評鑑** | 基礎評鑑、追蹤評鑑、幼照法第 51 條處分 | 20% | 28.6% |
| **輿情** | 園級 SRI + 區級熱度（三層，§5.5） | 15% | 21.4% |
| **營運** | 財報執行率、查核缺失、招生、收費 | 30% | 不適用 |

`risk_score = 100 × ECDF_type(R_raw)`，語意是「**同類型園所中的相對風險位置**」，**不是裁罰機率**。

用組內百分位而非機率的理由：基準率只有 10.6%，校準後的機率最高約 0.45，「風險 45 分」對稽查員沒有意義。用組內百分位而非全母體百分位的理由：公立與私立的基準率差一倍（5.8% vs 12.0%），跨類型比較絕對分數沒有意義。

### 1.4 分級（tier）

依 `RISK` 由高至低排序，**按名次切**，不按分數切：

| 級別 | 名次 | 園數 | 對應稽查量能 |
|---|---|---|---|
| 高 | 1 – 50 | 50 | 優先實地稽查 |
| 中 | 51 – 200 | 150 | 書面查核 / 抽查 |
| 低 | 201 – 1,178 | 978 | 例行 |

> 按名次切而非按分數切，是因為稽查人力是固定的。分數門檻會隨資料更新漂移，名次不會。

> **分級與分數用不同基準**（2026-09-12 決議）：`risk_score` 是組內百分位（回答「同類中多危險」），`tier` 是全市合併排序的名次（回答「這週查不查」）。合併排序用 `R_raw` 而非 `risk_score`，以保留尾端差距。詳見 §5.2。

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
| 8 | 收費明細 | `data/新北市...收費明細.json` | **280 園，100% 為公立**（95.2% 的公立園），115 學年度 | ✅ 檔名誤導，見 §5.6.1 |
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
| 私幼無財報（868 園、95.3% 的裁罰） | 營運維度永遠只覆蓋 280 園 | 這是題目本身的縫，直接在簡報指出，不要假裝補得起來 |

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
  "institution_type": "私立",
  "peer_group": "私立",
  "as_of_date": "2026-09-12",
  "risk": {
    "score": 87.4,
    "score_basis": "組內百分位",
    "rank": 23,
    "rank_basis": "全市合併",
    "tier": "高",
    "raw": 0.7412,
    "coverage": 0.83,
    "model_version": "risk-v2"
  },
  "dimensions": {
    "violation":  {"applicable": true,  "score": 96.8, "coverage": 1.00, "weight": 0.500, "validated": true},
    "evaluation": {"applicable": true,  "score": 74.1, "coverage": 1.00, "weight": 0.286, "validated": true},
    "sentiment":  {"applicable": true,  "score": 31.2, "coverage": 0.40, "weight": 0.214, "validated": true},
    "operation":  {"applicable": false, "score": null, "coverage": 0.00, "weight": null,  "validated": false,
                   "note": "私立幼兒園依法不需公告財務報告"}
  },
  "reasons": [
    {"code": "VIO_PUNISH_COUNT", "label": "切點前已被裁罰 5 次，同類型前 3%",
     "weight": 0.41, "dimension": "violation", "validated": true},
    {"code": "EVAL_FAIL", "label": "基礎評鑑 2 次未全數指標通過",
     "weight": 0.22, "dimension": "evaluation", "validated": true},
    {"code": "MEDIA_TOWN_HEAT", "label": "所在行政區近 90 天輿情熱度全市第 4",
     "weight": 0.11, "dimension": "sentiment", "validated": true}
  ],
  "finance_flags": [
    {"code": "OPER_PERSONNEL_EXEC", "label": "人事費執行率 64%，同儕中位數 90%",
     "severity": 3, "year": 112, "validated": false}
  ],
  "media": {"sri": 0.0, "has_signal": false, "town_heat_per_park": 0.42, "last_negative_at": null},
  "timeline": [
    {"date": "2023-07-03", "category": "超收", "law": "第8條第6項", "fine": 60000,
     "penalty_raw": "罰鍰：60,000元", "is_after_cutoff": false}
  ]
}
```

**`reasons` 規則**：固定回傳**至多 3 筆**，依 `weight` 由大至小。`label` 是白話句子，由後端組好，前端直接顯示，不做字串拼接。`code` 供前端決定圖示與顏色。

**`dimensions` 規則**：

| 欄位 | 規則 |
|---|---|
| `applicable` | 該維度是否適用於此園。私立的 `operation` 一律 `false` |
| `score` | `applicable = false` 時**必須是 `null`，不得是 0**。0 分等於懲罰守法者 |
| `coverage` | 0–1，該維度實際取得的子指標權重占比。前端據此顯示可靠度 |
| `weight` | 該維度在此園所類型下的權重。`applicable = false` 時為 `null` |
| `validated` | 該維度是否能以裁罰資料驗證。**營運維度一律 `false`**，前端須顯示警語 |
| `note` | 不適用或覆蓋率低時的白話說明，前端直接顯示 |

### 3.4 `curated/features.json`

模型的直接輸入。一列一園，欄位即 §4 特徵字典。

```json
{
  "park_id": "00ac631e-...",
  "institution_type": "私立",
  "cutoff": "2025-01-01",
  "label": false,

  "vio_pun_weighted": 7.83,
  "vio_pun_count": 5,
  "vio_owner_prior_count": 3,
  "vio_sibling_pun_count": 4,
  "vio_abuse_count": 0,
  "vio_days_since_last": 178,
  "vio_cat_師資": 1, "vio_cat_超收": 2, "vio_cat_不當管教": 0,
  "vio_cat_師生比": 2, "vio_cat_收費爭議": 0, "vio_cat_食安衛生": 0,
  "vio_cat_交通車": 0, "vio_cat_設施安全": 0, "vio_cat_其他行政": 0,
  "vio_owner_cross_park": true,
  "vio_sibling_count": 7,
  "vio_chain_size": 8,
  "vio_archetype": "連鎖累犯",

  "eval_base_fail_count": 2,
  "eval_admin_count": 2,
  "eval_followup_count": 1,
  "eval_admin_penalty": true,
  "eval_years_since": 1.8,
  "eval_missing": false,

  "media_sri": 0.0,
  "media_has_signal": false,
  "media_top_severity": null,
  "media_is_burst": false,
  "media_town_heat_per_park": 0.42,
  "media_town_heat_rank": 4,
  "media_last_negative_at": null,

  "oper_applicable": false,

  "display_count_approved": 90,
  "display_area_per_child": 3.42,
  "display_years_since_reg": 28.4,
  "display_monthly_fee": 12000,
  "display_town": "土城區"
}
```

**命名規則**：`vio_` / `eval_` / `media_` / `oper_` 前綴對應四個維度（§5.0），`display_` 前綴是**不進模型、只供前端顯示**的欄位。這讓維度分數計算變成一行欄位篩選，也讓原因歸組不需查表。

私立園的 `oper_applicable = false` 且**不帶任何 `oper_*` 數值欄位**——不是填 0，是整組不存在。完整欄位定義見 §4。

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

`peer_median` 的比較群是**同行政區 + 同年齡 + 同收費項目 + 同收費期間 + 同半全日班**。群內樣本 < 5 時改用收縮中位數（§5.6.4），仍不足時欄位為 `null`。

> **僅公立園有此檔。** 280 筆全數為公立（實測 `類別` 欄 100% 為「公立」），非營利與私立皆無收費明細。檔名中的「與非營利」與內容不符。

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
  "peer_group": "非營利-有財報",
  "sub_scores": {
    "F": {"score": 42.1, "coverage": 1.00, "weight": 0.40},
    "H": {"score": 91.3, "coverage": 1.00, "weight": 0.45},
    "E": {"score": 18.0, "coverage": 1.00, "weight": 0.15}
  },
  "operation_score": 71.4,
  "audit_floor_applied": 80,
  "validated": false,
  "flags": [
    {"code": "OPER_PERSONNEL_EXEC", "label": "人事費執行率 64%，同儕中位數 90%",
     "severity": 3, "year": 112,
     "evidence": {"rate": 0.64, "peer_median": 0.90, "rank": "3/46"}}
  ],
  "source_pdf": "raw/pdf/{park_id}/113.pdf"
}
```

`sub_scores` 的組成依同儕群而異（§5.6.0）：非營利-有財報為 F/H/E，公立-獨立為 F/E/C，公立-附設只有 C。查核缺失（A）已降為旗標，不再是子維度（§5.6.6）。`audit_floor_applied` 記錄下限規則是否生效（80 或 90），`null` 表示未觸發。`validated` 永遠是 `false`，理由見 §4.4。

> `operation_score` 已套用下限規則。若加權結果低於 `audit_floor_applied`，以下限值為準——這是規則覆蓋計算，必須可追溯。

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

四個維度，對應 §5.0 的權重表。欄位前綴即維度：`vio_` / `eval_` / `media_` / `oper_`。

所有特徵一律以 `CUTOFF = 2025-01-01` 為界計算。每個特徵標明**風險方向**（上尾 / 下尾 / 雙尾）與**轉換方式**（零膨脹 / ECDF），供 §5.1 使用。

### 4.1 違規維度 `vio_`

公立/非營利 35%、私立 50%。**全案最強的維度。**

| 欄位 | 型別 | 維度內權重 | 方向 | 轉換 | 實測 |
|---|---|--:|---|---|---|
| `vio_pun_weighted` | float | 40% | 上尾 | 零膨脹 | `Σ severity × 0.5^(days/540)`，見 §5.3 |
| `vio_pun_count` | int | 20% | 上尾 | 零膨脹 | 0 次 8.4% → 3 次 21.9% |
| `vio_owner_prior_count` | int | 20% | 上尾 | 零膨脹 | **無 8.6% → 有 14.5%（1.69x）** |
| `vio_sibling_pun_count` | int | 10% | 上尾 | 零膨脹 | 無 10.1% → 有 13.6% |
| `vio_abuse_count` | int | 10% | 上尾 | 零膨脹 | 0 次 10.3% → 1 次 23.1% |

輔助欄位（不直接計分，供原因碼與前端顯示使用）：

| 欄位 | 型別 | 用途 |
|---|---|---|
| `vio_days_since_last` | int | 最近一次裁罰距切點天數 → `VIO_RECENT` |
| `vio_cat_*` | int × 9 | 各類別次數（師資/超收/不當管教/師生比/收費爭議/食安衛生/交通車/設施安全/其他行政）→ `VIO_CAT_CONCENTRATED` 與派工單的查核建議 |
| `vio_owner_cross_park` | bool | 負責人跨園被罰（38 人）→ `VIO_CHAIN_REPEAT` |
| `vio_sibling_count` | int | 兄弟園數 |
| `vio_chain_size` | int | 同負責人名下園數（lift 1.31x）。**併入本維度**，因為它衡量的是違規的擴散面 |
| `vio_archetype` | cat | 未被罰 730 / 單園被罰 320 / 負責人他園有前科 66 / 連鎖累犯 96 |

> `vio_chain_size` 用 `owner_key` 分組計算，`owner` 為 null 的 68 園一律設 1，**不可視為同一人**。

### 4.2 評鑑維度 `eval_`

公立/非營利 20%、私立 28.6%。來源 `data/評鑑結果.json`，**僅取 `評鑑完成日 < CUTOFF` 的列**（丟棄 280 列：258 列日期在切點後、22 列「尚未接受評鑑」無日期）。

| 欄位 | 型別 | 維度內權重 | 方向 | 轉換 | 實測 lift |
|---|---|--:|---|---|---|
| `eval_base_fail_count` | int | 40% | 上尾 | 零膨脹 | **0/1/2/3 次 → 9.2% / 12.8% / 16.7% / 28.6%，單調，最高 2.71x** |
| `eval_admin_count` | int | 35% | 上尾 | 零膨脹 | 曾受處分 **22.9% vs 10.8%，2.16x**（35 園 / 78 列） |
| `eval_followup_count` | int | 25% | 上尾 | 零膨脹 | **0/1/2 次 → 9.2% / 13.7% / 16.8%，單調，1.59x** |

輔助欄位：

| 欄位 | 型別 | 用途 |
|---|---|---|
| `eval_admin_penalty` | bool | `eval_admin_count > 0`，供原因碼使用 |
| `eval_years_since` | float | 距最近一次評鑑年數 |
| `eval_missing` | bool | 137 園無切點前評鑑紀錄 → **`a = 0`，該維度 `Coverage = 0`，不以 0 分計** |

> ⚠ **不可用 0 代表缺失。** `eval_base_fail_count = 0` 是「評鑑全數通過」，缺失是「沒有評鑑紀錄」。兩者被罰率 9.2% 與 5.8%，方向相反。

此維度單獨的 Precision@50 = 24.0%，與違規維度相當——**兩者帶的是不同資訊**，見 §6.3。

#### 洩漏檢查結果（2026-09-12 實測）

| 檢查項 | 結果 | 判定 |
|---|---|---|
| 名稱 join（1,101 園 → `preschools.json`） | **1,101 / 1,101 完全相符** | ✅ 不需模糊比對 |
| 「行政處分」列的日期範圍 | 2015-06-22 ~ **2024-11-20**，切點後 **0 列** | ✅ **無洩漏**，可安心當特徵 |
| 評鑑完成日最大值 | **2025-11-28** | ⚠ 258 列在切點後，**ETL 必須過濾** |
| 原始 xlsx 的 `園所彙總` 表 | 以全部列預聚合，含切點後 | ❌ **已於轉檔時捨棄** |

> 「行政處分」的述文本身寫著罰鍰金額與第幾次違反（40 列含「新臺幣」）。這是**評鑑體系內的處分**（幼照法第 51 條，未通過評鑑不改善），與裁罰紀錄的第 8/16/26/33 條（超收、師生比、不當對待）是**不同法條、不同事件**，因此不是重複計算。

### 4.3 輿情維度 `media_`

公立/非營利 15%、私立 21.4%。三層設計見 §5.5。

| 欄位 | 型別 | 層級 | 維度內權重 | 覆蓋率 |
|---|---|---|--:|---|
| `media_sri` | float 0–100 | L1 園級 | 60% | 3.3%（40 園） |
| `media_town_heat_per_park` | float | L2 區級 | 40% | **100%** |

輔助欄位：

| 欄位 | 型別 | 用途 |
|---|---|---|
| `media_has_signal` | bool | **缺失指示欄**。`sri = 0` 是「沒被報導」不是「安全」 |
| `media_top_severity` | int 1–5 | 最嚴重事件等級 → 原因碼 |
| `media_is_burst` | bool | 近 30 天 ≥2 起、此前 90 天無事件 |
| `media_town_heat_rank` | int 1–29 | 區級熱度名次 → `MEDIA_TOWN_HEAT` |
| `media_last_negative_at` | date | 最近一則負面報導日期 |

> **L1 缺席時 `a = 0`，由 L2 撐起該維度。** 若只用 L1，96.7% 的園 `Coverage = 0`，該維度權重形同虛設。

### 4.4 營運維度 `oper_`（僅公立／非營利）

公立/非營利 30%、**私立 `applicable = false`、`score = null`、`Coverage = 0`**。

完整公式見 §5.6，此處只列欄位。

#### 公立-獨立（21 園）`O = 60%·F + 25%·E + 15%·C`

| 欄位 | 子維度 | 方向 |
|---|---|---|
| `oper_expense_deviation` | F 財務 | 雙尾 |
| `oper_tuition_exec_rate` | F | 下尾 |
| `oper_deficit_ratio` | F | 上尾 |
| `oper_cash_decrease_ratio` | F | 上尾 |
| `oper_debt_ratio` / `oper_networth_decline` | F | 上尾 |
| `oper_enroll_ratio` | E 招生 50% | 下尾 |　※ 實際招生數來源：`docs/總說明/*.md`
| `oper_enroll_decline` | E 30% | 上尾 |
| `oper_over_enroll` | E 20% | 上尾（確認超收 → 直接 100） |
| `oper_fee_deviation` | C 收費 60% | 雙尾 |
| `oper_fee_consistency` | C 25% | 上尾 |
| `oper_fee_completeness` | C 15% | 上尾 |

#### 公立-附設（273 園）`O = 100%·C`

只有 `oper_fee_*` 三個欄位。其餘 `oper_*` 欄位不存在（**不是 0**）。

#### 非營利-有財報（12 園）`O = 40%·F + 45%·H + 15%·E`

| 欄位 | 子維度 | 權重 | 方向 |
|---|---|--:|---|
| `oper_income_exec_deviation` | F | 等權 | 雙尾 |
| `oper_expense_exec_deviation` | F | 等權 | 雙尾 |
| `oper_deficit_ratio` | F | 等權 | 上尾 |
| `oper_liquidity` | F | 等權 | 上尾 |
| `oper_debt_ratio` | F | 等權 | 上尾 |
| `oper_personnel_exec_rate` | **H 人事** | 25% | 下尾 |
| `oper_teacher_salary_exec_rate` | H | 35% | 下尾 |
| `oper_overtime_exec_rate` | H | 20% | 上尾 |
| `oper_substitute_exec_rate` | H | 20% | 上尾 |
| `oper_enroll_*` | E | 同公立 | — |

#### 非營利-無財報（41 園）與私立（835 園）

`oper_applicable = false`，不帶任何 `oper_*` 欄位。

#### 旗標欄位（不進分數，見 §5.6.6）

| 欄位 | 用途 |
|---|---|
| `oper_audit_flags` | 查核表「否」的項目清單 → `finance_flags` |
| `oper_audit_major_count` | 重大缺失數 → 觸發 §5.6.7 的 80／90 下限 |

> **H 人事是財報唯一能接上教保風險的橋。** 裁罰前三名全是人力問題（師資 318、超收 268、不當管教 206），而人力不足會在財報上留下「編了預算沒聘滿人」的痕跡。見 [`NARRATIVE.md`](NARRATIVE.md) §4.4。

#### ⚠ 此維度無法以裁罰驗證

有財報的 280 園中被裁罰過的僅 6 間。所有 `oper_*` 特徵的權重是**領域判斷手訂**，`dimensions.operation.validated` 一律 `false`。理由與取捨見 §5.6。

### 4.5 不進模型的欄位

基本資料 25 欄中，只有 `vio_chain_size` 進了模型（併入違規維度）。其餘一律**只供前端顯示與分層**，不進分數。

| 欄位 | 實測 lift | 用途 |
|---|---|---|
| `type`（設立別） | 私立 12.0% / 公立 5.8% / 非營利 14.0% | **分層鍵**，決定權重表與同儕群 |
| `town` | — | 分層、地圖、區級輿情 join |
| `count_approved` | 1.15x (≥150) | 顯示、超收判定分母 |
| `area_per_child` | 1.19x (<2 m²) | 顯示 |
| `years_since_reg` | 1.37x (5–15 年) | 顯示 |
| `monthly_fee` | 1.19x (10k–20k) | 顯示 |
| `floor_count` / `is_pre_public` / `has_afterschool` | 0.85–1.1x | 顯示 |
| `penalty` | — | ❌ **已刪除**，是洩漏，見 §2.4 |
| `is_free5` / `shuttle` | 可用率 0% | ❌ 已丟棄 |

> **誠實說明**：基本資料欄位的 lift 幾乎都在 0.85–1.2x 之間，接近雜訊。把它們排除在模型外是**實測後的決定**，不是疏漏。它們的價值在分層與敘事，不在預測力。這個立場的答法見 [`NARRATIVE.md`](NARRATIVE.md) §5.2。

### 4.6 原因碼表（reason codes）

`serving/scores.json` 的 `reasons[].code` 只能取自下表。**後端依此產生 `label`，前端依此決定圖示與顏色**，兩邊不得自行新增。

| code | 維度 | 觸發條件 | label 模板 |
|---|---|---|---|
| `VIO_PUNISH_COUNT` | 違規 | `vio_pun_count >= 3` 或同類型前 10% | 切點前已被裁罰 {n} 次，同類型前 {pct}% |
| `VIO_RECENT` | 違規 | `vio_days_since_last <= 365` | 最近一次裁罰距切點僅 {days} 天 |
| `VIO_ABUSE` | 違規 | `vio_abuse_count >= 1` | 曾有 {n} 次幼兒不當對待裁罰紀錄 |
| `VIO_OWNER_PRIOR` | 違規 | `vio_owner_prior_count >= 1` | 同一負責人名下另有 {n} 園，其中 {m} 園亦有裁罰紀錄 |
| `VIO_CHAIN_REPEAT` | 違規 | `vio_archetype == "連鎖累犯"` | 屬連鎖累犯樣態：負責人跨 {n} 園累計 {m} 次處分 |
| `VIO_SIBLING` | 違規 | `vio_sibling_pun_count >= 2` | 同負責人之兄弟園累計 {n} 次裁罰 |
| `VIO_CAT_CONCENTRATED` | 違規 | 單一類別占該園裁罰 ≥ 50% 且 ≥ 2 次 | 歷史違規集中於{category}（{n} 次） |
| `VIO_CHAIN_SIZE` | 違規 | `vio_chain_size >= 3` | 同一負責人名下共 {n} 園 |
| `EVAL_FAIL` | 評鑑 | `eval_base_fail_count >= 1` | 基礎評鑑 {n} 次未全數指標通過 |
| `EVAL_ADMIN` | 評鑑 | `eval_admin_penalty == true` | 曾受幼照法第 51 條行政處分 {n} 次 |
| `EVAL_FOLLOWUP` | 評鑑 | `eval_followup_count >= 1` | 曾接受追蹤評鑑 {n} 次 |
| `EVAL_MISSING` | 評鑑 | `eval_missing == true` | 查無切點前評鑑紀錄，可能為新立案園所 |
| `MEDIA_PARK` | 輿情 | `media_sri >= 15` | 近期有 {n} 起負面報導，最高嚴重度 {sev} |
| `MEDIA_BURST` | 輿情 | `media_is_burst == true` | 輿情近 30 天出現爆發，此前 90 天無事件 |
| `MEDIA_TOWN_HEAT` | 輿情 | `media_town_heat_rank <= 5` | 所在行政區近 90 天輿情熱度全市第 {rank} |
| `OPER_PERSONNEL_EXEC` | 營運 | 人事費執行率 < 同儕 P10 | 人事費執行率 {pct}%，同儕中位數 {med}% |
| `OPER_SUBSTITUTE_EXEC` | 營運 | 代課代班費執行率 < 0.4 | 代課代班費執行率 {pct}% |
| `OPER_AUDIT_MAJOR` | 營運 | `oper_audit_major_count >= 1` | 查核有 {n} 項重大缺失 |
| `OPER_ENROLL_LOW` | 營運 | `oper_enroll_ratio` < 同儕 P10 | 實際招生為核定人數的 {pct}% |
| `OPER_OVER_ENROLL` | 營運 | `oper_over_enroll == true` | 實際招生超過核定人數 {n} 人 |
| `OPER_FEE_DEVIATION` | 營運 | `abs(oper_fee_deviation) > 20` | 收費較同區同類型中位數{高/低} {pct}% |

**規則**：

1. `reasons` 取 `weight` 前 3 名，**同一維度最多 2 條**，確保不會三條全是違規
2. `weight` = 該特徵的維度內權重 × 維度權重 × 標準化後的分數
3. **`OPER_*` 類別必須附 `"validated": false`**，前端在該條原因旁顯示 ⓘ 警語
4. label 中所有 `{}` 佔位符必須有實際數值，**不得輸出帶佔位符的字串**
5. **任何 label 不得出現自然人姓名**（§10.1）

---

## 5. 分數計算

> **v2 模型（2026-09-12 整合）**：本章整合 [`營運係數.md`](營運係數.md) 的四維度設計與本規格原有的監督式驗證框架。四項衝突已拍板，見 §5.0。

### 5.0 四維度模型與四項決議

風險分數由**四個維度**組成，取代 v1 的 A / D 兩塊：

| 維度 | 內容 | 對應 v1 |
|---|---|---|
| **違規** | 切點前裁罰紀錄、負責人前科、兄弟園 | D |
| **評鑑** | 基礎評鑑未通過、追蹤評鑑、幼照法第 51 條行政處分 | A 的一部分 |
| **輿情** | 三層訊號（園級 SRI / 區級熱度 / 全市溫度），見 §5.3 | A 的一部分 |
| **營運** | 財報執行率、查核缺失、招生、收費異常 | B+C（原為旗標，現進分數） |

#### 權重

| 園所類型 | 違規 | 評鑑 | 輿情 | 營運 |
|---|--:|--:|--:|--:|
| 公立 | 35% | 20% | 15% | 30% |
| 非營利 | 35% | 20% | 15% | 30% |
| **私立**（868 園，95.3% 的裁罰） | **50%** | **28.6%** | **21.4%** | 不適用 |

私立的權重是公立權重去掉營運後重新正規化（35/70、20/70、15/70）。

> **私立的權重與 v1 實測最佳值接近**：v1 是 A 0.43 / D 0.57，v2 私立是（評鑑+輿情）50% /（違規）50%。差異在 v2 完全捨棄基本資料 11 個欄位——而 §4.1 實測那些欄位的 lift 都在 0.85–1.2x，接近雜訊。**捨棄它們是有依據的**。

#### 四項決議（2026-09-12）

| # | 衝突 | 決議 | 理由 |
|---|---|---|---|
| 1 | 分級切法 | **分數用組內百分位，分級用全市合併排序** | 分數回答「同類中多危險」，分級回答「這週查不查」。全照組內前 15% 會產生 182 園高風險，對應不到 50 個稽查名額，且會把 44 個名額分給 lift 僅 1.18x 的公立園 |
| 2 | 營運是否進分數 | **進分數，但僅公立／非營利，且必須標註無法驗證** | 營運只影響公立+非營利 347 園，而那正是監督式模型失效的區段（公立 lift 0.86x，比隨機還差）。它不是與監督式競爭，是補它的洞 |
| 3 | 百分位轉換 | **零膨脹修正**：0 值給 0 分，非 0 值在非 0 子集內排名 | 違規維度有 53.7% 的私立園原始值為 0，原樣 ECDF 會讓它們全部並列於 26.8 分，且尾端被壓縮（12 次 vs 3 次只差 8.1 分）。修正後拉開到 17.5 分，P@50 從 24.0% 回到 26.0% |
| 4 | 主驗證指標 | **Precision@50 為主**，Recall@Top15% / PR-AUC 為次 | @50 直接對應 50 個稽查名額，可翻譯成「同樣 50 家，隨機抓 5 家、我們抓 14 家」 |

### 5.1 指標 → 維度分數

每個指標先轉為同儕相對位置。同儕定義為 **園所類型 × 學年度**，不跨類型比較。

#### 風險方向

| 方向 | 語意 | 例 |
|---|---|---|
| 上尾 | 數值越高越危險 | 負債比、短絀率、加班費執行率 |
| 下尾 | 數值越低越危險 | 招生率、教保人員薪資執行率 |
| 雙尾 | 偏離同儕中位數越遠越危險 | 總預算執行率 |

#### 零膨脹百分位（決議 3）

```python
def pct_zero_inflated(values):
    """0 值給 0 分；非 0 值在非 0 子集內排名，映射到 (0, 100]。"""
    nonzero = sorted(v for v in values if v > 0)
    m = len(nonzero)
    out = []
    for v in values:
        if v <= 0:
            out.append(0.0)
        else:
            lo = bisect_left(nonzero, v); hi = bisect_right(nonzero, v)
            out.append(100 * (((lo + hi - 1) / 2) + 1) / m)
    return out
```

**適用時機**：該指標有明確的「零」語意（沒被罰過、沒有查核缺失）且零值占比 > 20%。
**不適用**：連續型且無自然零點的指標（執行率、負債比）→ 用一般 ECDF。

每個指標必須在特徵字典中標明用哪一種，見 §4。

#### 維度分數與覆蓋率

子指標缺資料時，不以 0 填補，改用覆蓋率加權：

```
S_D       = Σ(u_j · a_ij · P_ij) / Σ(u_j · a_ij)
Coverage_D = Σ(u_j · a_ij) / Σ(u_j)
```

`u_j` 是該指標在維度內的權重，`a_ij = 1` 表示資料存在、年度一致且通過核對，否則為 0。

> **這是 v2 相對 v1 的實質改進。** v1 用中位數填補缺失值，等於假設「沒資料的園跟中位數一樣」。覆蓋率加權則是「沒資料的指標不參與計算，並如實回報涵蓋了多少」。前端顯示 `coverage`，使用者看得到這個分數有多可靠。

### 5.2 總分與分級

#### 總分（組內百分位）

```
R_raw_i      = Σ(w_k · Coverage_ik · S_ik) / Σ(w_k · Coverage_ik)
risk_score_i = 100 × ECDF_peer_group(R_raw_i)
```

`risk_score` 的語意是「**在同儕群中的相對風險位置**」，**不是裁罰機率**。

> **同儕群不等於設立別。** 營運維度依「可取得的資料」再細分（§5.6.0），因為附設幼兒園制度上沒有獨立決算，把它和市立獨立園放進同一個 ECDF 是在比較不同的東西。違規／評鑑／輿情三個維度的同儕群仍是設立別，只有營運維度用細分群——**這是刻意的不對稱**，因為只有營運維度的資料可得性隨組織形態變化。

#### 分級（全市稽查量能）

分級**不**由 `risk_score` 的絕對值決定，而由全市合併排序的名次決定：

| 級別 | 名次 | 園數 | 對應稽查量能 |
|---|---|---|---|
| 高 | 1 – 50 | 50 | 優先實地稽查 |
| 中 | 51 – 200 | 150 | 書面查核 / 抽查 |
| 低 | 201 – 1,178 | 978 | 例行 |

合併排序用 `R_raw`（未經 ECDF 壓縮）而非 `risk_score`，以保留尾端差距。

> **為什麼分數與分級用不同基準**：分數要回答「這家在同類中算不算危險」——跨類型比較公立與私立的絕對分數沒有意義，因為兩者基準率差一倍（5.8% vs 12.0%）。分級要回答「這週的 50 個名額給誰」——那是全市共用的固定資源。兩個問題不同，答案就不該是同一個數字。

#### 公立園的特別處置

公立組內 lift 僅 1.18x（前 15%）至 0.86x（前 20 名），模型在此組實質無效。

**建議**：高風險名單以私幼為主，公立園維持例行普查，不佔用模型排序的稽查名額。若行政上必須納入，應另立公立園配額，不與私幼競爭同一批名次。

### 5.3 違規維度（原 D）

```
pun_weighted = Σ_events  severity(category) × 0.5^(days_before_cutoff / 540)
```

嚴重度對照表（**沿用 `sentinel/score_risk.py`，不用罰鍰金額**）：

| 類別 | severity |
|---|---|
| 性平事件 / 不當管教 | 5 |
| 食安衛生 / 設施安全 | 4 |
| 交通車 / 超收 / 師生比 / 師資 | 3 |
| 收費爭議 | 2 |
| 其他行政 | 1 |

半衰期 540 天。維度內子指標：`pun_weighted` 40%、`pun_count` 20%、`owner_prior_count` 20%、`sibling_pun_count` 10%、`pun_abuse_count` 10%。全部使用零膨脹百分位。

> 為何不用金額：40 筆「停止招生」「減少招收人數」的 `fine` 是 NULL / 0，但實質嚴重度高於多數罰鍰。用金額當權重會把最嚴重的案子算成 0 分。

### 5.4 評鑑維度

來源 `data/評鑑結果.json`，僅取 `評鑑完成日 < CUTOFF` 的列。子指標與權重：

| 子指標 | 權重 | 方向 | 轉換 |
|---|--:|---|---|
| `eval_base_fail_count` | 40% | 上尾 | 零膨脹 |
| `eval_admin_penalty` / `eval_admin_count` | 35% | 上尾 | 零膨脹 |
| `eval_followup_count` | 25% | 上尾 | 零膨脹 |

`eval_missing`（137 園無切點前評鑑紀錄）→ `a = 0`，該維度 `Coverage = 0`，**不以 0 分計**。

實測 lift 見 §4.2。此維度單獨的 Precision@50 = 24.0%，與違規維度相當。

### 5.5 輿情維度 — 三層設計

**A 級（明文點名園所）只佔 2.6%，若只用 A 級，1,178 園中只有 40 園有輿情分數。** 因此分三層，各有各的用途與覆蓋率：

```
L1 園級（A 級連結，40 園，覆蓋 3.3%）
    SRI = 100 × (1 − exp(−Σ w_event / 3.0))
    w_event = severity × credibility × entity_conf × source_weight × resonance × decay
    · 同園 × 同事件類型 × 同 ISO 週 = 同一起事件（去重，避免 70 篇轉載灌爆分數）
    · resonance = 1.3 if 3 家以上不同媒體都報
    · 半衰期：性平/不當管教 180d，食安/設施/交通車 120d，超收/收費/行政 60d，師資/欠薪 30d

L2 區級（B 級，29 區，覆蓋 100% 園所）      ★ 這層才是主力
    heat          = Σ severity × credibility × decay   （該區所有 B 級文件）
    heat_per_park = heat / 該區 is_active 園數

L3 市級（C 級，137 篇）
    只算全市溫度的時間序列，不落到任何園所 → 不進分數，僅作前端趨勢折線
```

**維度內權重**：L1 園級 60%、L2 區級 40%。

> **這解決了「輿情 15% 權重對 96.7% 的園是空的」問題。** 若只用 L1，絕大多數園的輿情 `Coverage = 0`，15% 權重形同虛設。加入 L2 後，每一園都至少有區級訊號，覆蓋率達 100%。

**B 級刻意不落到個別園所。**「板橋某私立幼兒園」不該讓板橋 162 家各背一筆嫌疑——誤標一家幼兒園，是拿政府公信力賠一家業者的商譽。B 級的作用是**縮小稽查範圍**，不是指認。

**缺失處理**：`sri == 0` 不代表該園安全，只代表沒被報導。一律附 `sri_has_signal` 指示欄。

**待補**：`doc_analysis` 只標了 580/2,900。需用 Bedrock 補標剩餘 2,320 篇，1 RPS 下約 39 分鐘，**離線批次跑，不在 API 路徑上**。

### 5.6 營運維度（僅公立／非營利）

**私立 835 園一律 `applicable = false`、`score = null`、`Coverage = 0`，不是 0 分。** 私幼依法不需公告財報，也無公開收費明細，把它當 0 分等於懲罰守法者。

#### 5.6.0 同儕群依「可取得的資料」定義，不只依設立別

這是本維度最重要的設計決定。**同一個設立別裡，不同組織形態的財務可見度差距極大**，把它們放進同一個 ECDF 是在比較不同的東西。

新北公立 294 園的實際組成（2026-09-12 實測）：

| 組成 | 園數 | 財務記帳方式 | 有獨立決算書 |
|---|---:|---|---|
| 國小附設幼兒園 | 183 | 併入該國小預算單位 | ❌ |
| 分班 | 49 | 附屬於本園 | ❌ |
| 國中（小）附設幼兒園 | 33 | 併入該國中預算單位 | ❌ |
| 實驗小學附設 | 5 | 併入實小預算單位 | ❌ |
| **市立獨立幼兒園** | **24** | **自己就是一個預算單位** | ✅ |

`113年決算書第五冊`（710 頁）共 25 個預算單位，其中 **21 個就是市立獨立幼兒園**。國中、國小在第三、四冊。

> **273 家附設園沒有獨立決算不是資料缺漏，是制度使然。** 教育局本身就沒有「板橋國小附幼」這個獨立決算，去要也要不到。這點要寫進簡報的資料限制說明。

因此營運維度分為**四個同儕群**，各用各的公式、各自做 ECDF：

| 同儕群 | 園數 | 公式 | 資料來源 |
|---|---:|---|---|
| **公立-獨立** | 21 | `O = 60%·F + 25%·E + 15%·C` | 決算書第五冊 + 收費明細 |
| **公立-附設** | 273 | `O = 100%·C` | 收費明細（280 園中的附設部分） |
| **非營利-有財報** | 12 | `O = 40%·F + 45%·H + 15%·E` | OCR 財報 |
| **非營利-無財報** | 41 | `applicable = false` | — |

私立 835 園：`applicable = false`。

#### 5.6.1 資料涵蓋實況

| 資料 | 公立 | 非營利 | 私立 |
|---|---|---|---|
| 收費明細（115 學年度） | **280 / 294 = 95.2%** | **0** | **0** |
| 財報或決算 | 21 / 294 = 7.1% | 12 / 53 = 22.6% | 0 |

> ⚠ **`data/新北市公立與非營利幼兒園_115學年度收費明細.json` 的檔名有誤導性。** 實測 280 筆全部是公立（檔案內 `類別` 欄 100% 為「公立」，對照 `preschools.json` 的 `type` 亦為 100% 公立）。**非營利與私立皆無收費明細。** 因此收費異常（C）只出現在公立的兩個同儕群。

#### 5.6.2 公立-獨立（21 園）

```
O = 60%·F + 25%·E + 15%·C
```

**F 財務**（內部等權，來源決算書第五冊）：

| 指標 | 方向 |
|---|---|
| 總支出預決算偏離 | 雙尾 |
| 學雜費收入執行率 | 下尾 |
| 本期短絀／基金來源 | 上尾 |
| 現金淨減少／期初現金 | 上尾 |
| 負債／資產、淨資產年減率（取平均） | 上尾 |

**E 招生**：實際招生／核定人數 50%（下尾）、招生人數年減率 30%（上尾）、超過核定人數 20%（同年度確認超收時該項直接 100 分）。核定與實際年度無法對齊時 `a = 0`。

**C 收費**：見 §5.6.4。

#### 5.6.3 公立-附設（273 園）

```
O = 100%·C
```

這 273 園制度上沒有獨立財務資料，**營運分數等同收費異常分數**。這是誠實的做法：不假裝有財務訊號，也不因此把它們判為不適用——收費明細是真實可用的訊號，覆蓋率 95%。

> 前端在這群園的營運維度顯示 `note`：「本園為附設幼兒園，財務併入所屬學校，營運分數僅依收費明細計算」。

#### 5.6.4 收費異常 C（公立專用）

| 子項 | 權重 | 說明 |
|---|--:|---|
| 同儕收費偏離 | 60% | 雙尾。比較條件：學年度 × 年齡 × 收費項目 × 收費期間 × 半日／全日班 |
| 年齡／學期／半全日班一致性 | 25% | 同園內各年齡、上下學期、半全日的單價邏輯是否自洽 |
| 缺漏、重複或非預期收費項目 | 15% | 上尾 |

區內樣本不足時，同儕基準用**收縮中位數**：

```
Median* = (n_g × Median_g + 8 × Median_city) / (n_g + 8)
```

> **收費表是核准公告價格，偏離只作弱訊號，不直接視為違規。** 公立園收費由主管機關核定，偏離多半反映園所規模或服務內容差異，不是違法。這點必須在前端文案寫明。

#### 5.6.5 非營利-有財報（12 園）

```
O = 40%·F + 45%·H + 15%·E
```

> **權重已於 2026-09-12 調整**：原設計為 `30%F + 35%H + 25%A + 10%E`，查核缺失（A）降為旗標後（§5.6.6），其 25% 按比例重分配給 F、H、E。

**F 財務**（內部等權）：總收入執行率偏離（雙尾）、總支出執行率偏離（雙尾）、短絀／收入（上尾）、現金減少與流動性（上尾）、負債比與淨值衰退（上尾）。

**H 人事執行情形**——這是財報唯一能接上教保風險的橋：

| 子項 | 權重 | 方向 |
|---|--:|---|
| 人事費總執行率 | 25% | 下尾 |
| 園長及教保服務人員薪資執行率 | 35% | 下尾 |
| 加班費執行率 | 20% | 上尾（超過預算視為重大缺失，觸發 §5.6.7 下限） |
| 代課／代班費執行率 | 20% | 上尾及年度異常增加 |

> **低加班費、低代課費不自動判定為風險**，需看同儕與年度變化。預算為 0 時不除以零，該子項 `a = 0`。

裁罰前三名合計占 51%（師資 318、超收 268、不當管教 206、師生比 151）全是人力問題，而人力不足會在財報留下「編了預算卻沒聘滿人」的痕跡。46 份財報已全數抽表成功（`etl/ocr_extract.py`），人事費執行率中位數 90%。N09 安興 **112 學年度為 64%（46 份中第 3 低）**，該學年被裁罰 3 次不當管教。**n = 1，機制假說而非統計證據**，見 [`NARRATIVE.md`](NARRATIVE.md) §4.4。

**E 招生**：公式同公立-獨立。

#### 5.6.6 查核缺失降為旗標（2026-09-12 決議）

會計師查核表的「否」**不進營運分數**，改為稀有事件旗標。

| 理由 | 數據 |
|---|---|
| 變異不足 | 3,202 個判定中只有 **11 個「否」（0.34%）** |
| 與目標反向 | N09 安興 0 個「否」卻被裁罰；N10 大觀 7 個「否」卻從未被裁罰 |
| 量測的是不同東西 | 查核表查憑證、專戶、薪資級距、超支、借款；裁罰查師生比、無證人力、不當對待 |

11 個正樣本依經驗法則最多撐 1 個特徵，給 25% 權重會把雜訊放大。

**改為**：`oper_audit_flags`，任一「否」即列入 `finance_flags` 供人工複查，並保留 §5.6.7 的下限規則。查核表中直接查人員配置的三項（第 17 項園長薪資、第 19 項教師及教保員薪資、第 30 項代課費）與 H 人事執行率是同一組訊號，已由 H 涵蓋。

#### 5.6.7 查核下限規則（audit floor）

下限規則**保留**，因為它處理的是「罕見但嚴重」的情況，不需要統計顯著性：

| 條件 | 營運係數下限 |
|---|--:|
| 任一重大缺失（Severity 3） | **80** |
| 兩項以上重大缺失，或前期缺失未改善 | **90** |

嚴重度分級：

| Severity | 項目 |
|---|---|
| 3 | 收入漏列、違法或未授權支出、薪資／勞健保／退休金不符、加班超支、借貸或關係人交易異常、前期缺失未改善 |
| 2 | 憑證、帳務、預算流用或財務控制缺失 |
| 1 | 一般行政或文件缺失 |

下限是**規則覆蓋計算結果**，必須記錄在 `finance.json` 的 `audit_floor_applied`，讓稽查員追得到為什麼這家園分數被拉高。

#### 5.6.8 ⚠ 本維度無法以裁罰驗證

有財務資料的園（公立-獨立 21 + 非營利-有財報 12 = 33 園）中，被裁罰過的僅個位數。**無法訓練或驗證任何模型。**

因此：

1. 營運權重是**領域判斷手訂的**，不是從資料學出來的
2. `dimensions.operation.validated` 一律 `false`
3. 前端在營運相關的原因與旗標旁顯示「此維度依財務常規判斷，尚無足夠裁罰樣本可驗證」
4. 簡報中不得聲稱營運維度「經過驗證」

**為什麼仍然納入**：營運影響公立 294 + 非營利 12 = 306 園，而監督式模型在公立組的 lift 是 0.86x（比隨機還差）。**一個有領域依據但未驗證的訊號，勝過一個已證實無效的訊號。** 這個取捨要明講，不要藏。
---

## 6. 模型與驗證

### 6.1 兩條模型線並行

| | v2 主線（規則式加權） | 挑戰者 |
|---|---|---|
| 方法 | 四維度手訂權重 + 零膨脹百分位 + 覆蓋率加權（§5） | SageMaker 內建 XGBoost，全特徵單一模型 |
| 輸出 | 四維度分數 + 組內百分位 + 全市名次 | `p(被罰)` → 百分位 |
| 解釋 | 維度分數 × 權重，逐項可追 | SHAP |
| 角色 | **主線**。可上台講、可寫進公文、失敗風險低 | 效益曲線上多一條線；若顯著較優則換主線 |
| 可涵蓋私立以外 | ✅ 營運維度補上公立／非營利（§5.6） | ❌ 公立組正樣本不足，樹模型無法學 |

主線先做完並且能端到端跑通，挑戰者才動。黑客松時間內，**一個能解釋的 2.3x 勝過一個講不清楚的 2.8x**。

> **權重來源的誠實說明**：四維度權重是**領域判斷手訂**，不是從資料學出來的。正樣本只有 128 個，其中營運維度可用的僅 6 個，不足以估計 4 個維度的權重。此事實須寫進簡報方法說明，見 [`NARRATIVE.md`](NARRATIVE.md) §5.4。

### 6.2 驗證設計

```
訓練：date <  2025-01-01 的特徵  →  預測 date >= 2025-01-01 是否被裁罰
母體：1,178 園（is_active == 1）
基準率：10.6%
主指標：Precision@50   （對應「高風險」級的 50 個稽查名額）
次指標：Recall@Top15%、Precision@200、PR-AUC、稽查效益曲線
分層  ：私立／公立／非營利組內各報一次（小樣本組改用較小的 K）
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

**這是模型必須超過的門檻：Precision@50 ≥ 28.0%。** 目標 ≥ 34%（3.2x）。

> ⚠ **上表的第 4、5 列是原始值直接加權**（v1 做法）。v2 改用零膨脹百分位後，同一排序的 Precision@50 是 **26.0%**（見 §5.1）。
>
> **門檻仍訂在 28.0%。** 零膨脹百分位換來的是跨類型可比性與抗離群值，不是準確度——若 v2 跑不到 28.0%，代表營運維度與輿情三層沒有補回那 2 個百分點，該檢討的是維度設計，不是降低標準。

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
| `SpaRouterFunction` | `AWS::CloudFront::Function` | viewer-request，SPA 路由。**不可改用 `CustomErrorResponses`**，見下方說明 |
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

**SPA 路由**：用 **CloudFront Function（viewer-request）** 把無副檔名且非 `/api/` 的路徑改寫成 `/index.html`。

> ⚠ **不可以用 `CustomErrorResponses`。** 那是網路上最常見的 SPA 作法，但它**對整個 distribution 生效，無法只綁一個 behavior**——API 正常回的 404 也會被攔截並改寫成 `/index.html`，導致前端收到的是 S3 的 `AccessDenied` XML 而不是 `PARK_NOT_FOUND`。
>
> 2026-09-12 實測：先用 `CustomErrorResponses` 部署，`GET /api/v1/parks/<不存在>` 直連 API Gateway 正確回 404 JSON，經 CloudFront 卻變成 HTTP 403 + `<Error><Code>AccessDenied</Code>`。整個 §8.0 的錯誤契約失效。
>
> 正解（`infra/template.yaml` 的 `SpaRouterFunction`）：
>
> ```js
> function handler(event) {
>   var request = event.request;
>   var uri = request.uri;
>   if (uri.indexOf('/api/') === 0) return request;   // API 原樣通過
>   var last = uri.substring(uri.lastIndexOf('/') + 1);
>   if (last.indexOf('.') === -1) request.uri = '/index.html';
>   return request;
> }
> ```

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
  "weights": {
    "公立":   {"violation": 0.35, "evaluation": 0.20, "sentiment": 0.15, "operation": 0.30},
    "非營利": {"violation": 0.35, "evaluation": 0.20, "sentiment": 0.15, "operation": 0.30},
    "私立":   {"violation": 0.50, "evaluation": 0.286, "sentiment": 0.214, "operation": null}
  },
  "peer_groups": {
    "公立-獨立":     {"n": 21,  "operation": "60%F + 25%E + 15%C"},
    "公立-附設":     {"n": 273, "operation": "100%C"},
    "非營利-有財報": {"n": 12,  "operation": "40%F + 45%H + 15%E"},
    "非營利-無財報": {"n": 41,  "operation": null},
    "私立":         {"n": 835, "operation": null}
  },
  "score_basis": "同儕群內百分位（ECDF by peer_group）",
  "rank_basis": "全市合併排序（R_raw）",
  "unvalidated_dimensions": ["operation"],
  "tiers": {"high": [1, 50], "medium": [51, 200], "low": [201, 1178]},
  "data_freshness": {"punishments": "2026-08-21", "media": "2026-08-21", "fees": "115學年度"},
  "model": {"name": "risk-v2", "precision_at_50": 0.28, "baseline": 0.106, "lift": 2.64,
            "secondary": {"recall_at_top15": 0.203, "pr_auc": null}}
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
  "model": {"name": "risk-v2", "precision_at_50": 0.28, "baseline": 0.106},
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
| **M1** 資料層 | ETL → `curated/*.json`、雜湊個資、品質 assert、**營運維度 OCR 抽表**（46 份財報 + 61 個公立園年度） | **7h** | — | 頁面骨架 3h | S3 + IaC 骨架 2h |
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
│   ├── features.py          §4 特徵字典（vio_/eval_/media_/oper_）
│   ├── operation.py         §5.6 營運維度：F/H/A/E 子分數與下限規則
│   ├── ocr_extract.py       財報與決算抽表與核對（§3.10 第 8 步）
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

**全數結案（2026-09-12）。M0 契約已凍結，四軌可同時開工。**

> 剩餘的不是決策而是實作待辦：營運維度的 OCR 抽表（46 份財報 + 61 個公立園年度）、輿情補標 2,320 篇。兩者都在 M1–M4 的排程內。

| # | 問題 | 影響 | 建議 | 狀態 |
|---|---|---|---|---|
| 1 | ~~評鑑資料在誰手上~~ | — | — | ✅ 2026-09-12 到齊並驗證 |
| 2 | ~~B+C 財務公式~~ | — | 已由 [`營運係數.md`](營運係數.md) 提供，整合為 §5.6 營運維度 | ✅ 2026-09-12 到齊 |
| 10 | ~~分級切法衝突~~ | — | **分數用組內百分位，分級用全市合併排序**（§5.2） | ✅ 2026-09-12 拍板 |
| 11 | ~~營運是否進分數~~ | — | **進，但僅公立／非營利，且 `validated: false`**（§5.6） | ✅ 2026-09-12 拍板 |
| 12 | ~~百分位轉換方式~~ | — | **零膨脹修正**：0 值給 0 分，非 0 值在非 0 子集內排名（§5.1） | ✅ 2026-09-12 拍板 |
| 13 | ~~主驗證指標~~ | — | **Precision@50 為主**，Recall@Top15% / PR-AUC 為次（§6.2） | ✅ 2026-09-12 拍板 |
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
- [ ] `serving/scores.json` 每筆的 `reasons` 皆 1–3 條，`code` 全部在 §4.6 表內，無佔位符殘留，同一維度不超過 2 條
- [ ] 四維度分數與 `coverage` 皆已產出；私立園 `operation.applicable = false` 且 `score = null`（**不是 0**）
- [ ] `dimensions.operation.validated` 一律為 `false`
- [ ] 零膨脹轉換只套用在有自然零點且零值占比 > 20% 的指標，其餘用一般 ECDF（§5.1）
- [ ] 營運維度四個同儕群各自產出（21 / 273 / 12 / 41 園），ECDF 在群內計算
- [ ] 收費明細確認 280 筆全為公立；非營利與私立的 `oper_fee_*` 欄位不存在
- [ ] 查核表「否」只出現在 `finance_flags`，**不在任何維度分數中**
- [ ] 下限規則生效時 `audit_floor_applied` 已記錄（80 或 90）
- [ ] 權重敏感度已掃描（違規權重 40–60%），結果寫入 `model/metrics.json`

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
- [ ] **`GET /api/v1/parks/<不存在>` 經 CloudFront 仍回 404 + `PARK_NOT_FOUND` JSON**（確認 SPA 路由沒有吃掉 API 的錯誤碼）
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
