# 任務分配表

每個角色一段完整簡報，**可直接整段貼給你的 AI**。五個角色互不阻塞，唯一耦合點是 [`SPEC.md`](SPEC.md) §8 API 契約（已凍結）。

| 角色 | 代號 | 負責 | 關鍵路徑 | 預估 |
|---|---|---|---|---|
| 資料與模型 | **A** | ETL、特徵、分數、回測 | ★ 是 | 12h |
| 營運維度 | **B** | 財報／決算抽表、營運係數 | ★ 是 | 8h |
| 後端 | **C** | 9 支 API、部署 | 否 | 6h |
| 前端 | **D** | 7 個頁面 | 否 | 14h |
| 雲端 | **E** | IaC、S3/CloudFront、監控 | 否 | 6h |

> **人數不足時的合併順序**：E 併入 C → B 併入 A → D 找第二人支援。
> **A 與 B 是關鍵路徑**，其他人卡住不會擋住他們，他們卡住會擋住所有人。

---

## 共同規則（所有角色都要遵守）

貼給 AI 時請一併附上這段。

```
專案：新北市教保機構風險預警系統（AWS 黑客松）
Repo：https://github.com/ajiou/aws-hackathon

三條不可違反的規則：

1. 不上傳任何自然人姓名到 AWS。競賽規範第 2 條禁止匯入個人資料。
   裁罰紀錄的行為人與 preschools.owner 都是真名，一律用
   etl/pii.py 的 hash_person() 雜湊。SALT 從環境變數 WATCHDOG_SALT 讀，
   不得寫進程式碼或 commit。

2. 特徵只能用切點 2025-01-01 之前的資料。preschools.json 的 penalty
   欄位已證實是標籤洩漏，必須整欄刪除（SPEC §2.4）。

3. S3 bucket 一律 private，前端走 CloudFront + OAC，
   不可用 S3 Website Hosting。

工作方式：
- 開分支做事，不要直接推 main。分支命名 <代號>-<主題>，如 a-etl。
- 動到 SPEC §8 API 契約要先在群組講，前端已照它開發。
- 數字要實測，不要沿用文件裡的舊數字——已經發生過兩次文件數字與
  實際資料不符（penalty 洩漏、安興 51%）。
```

---

## A — 資料與模型

```
你負責這個專案的資料管線與風險模型。

先讀：
- docs/SPEC.md 的 §1 定義、§2 資料盤點、§3 資料契約與 ETL、
  §4 特徵字典、§5 分數計算、§6 模型與驗證
- etl/constants.py、etl/quality.py、etl/pii.py（已寫好，直接用）
- data/media/README.md —— 輿情資料已進 repo

輿情資料（2026-09-12 已進版控，7 份 JSON）：
  data/media/docs.json           2,900 篇文件（刻意不含新聞全文）
  data/media/doc_resolution.json 實體解析 A 161 / B 352 / C 137 / X 2,250
  data/media/doc_links.json      A 級綁定 209 筆，park_id 與 preschools.json 相同
  data/media/doc_analysis.json   LLM 抽取 580/2,900，其餘 2,320 待補
  data/media/district_heat.json  區級熱度（SPEC §5.5 的 L2 層）
  data/media/park_risk.json      既有 SRI 結果，供對照
最重要的一件事：只用 L1 園級訊號覆蓋率僅 3.3%（40/1,178 園），
必須加上 L2 區級才有意義。維度內權重 L1 60% / L2 40%，見 SPEC §5.5。

你要產出：
1. etl/build_curated.py
   照 SPEC §3.10 的八個步驟，每步結束呼叫對應的 assert。
   輸入 data/ 下的檔案，輸出 out/curated/*.json（8 份，schema 見 §3.2–§3.9）。
   營運維度的 oper_* 欄位由 B 提供，你先留介面，缺檔時 coverage=0。

2. etl/features.py
   實作 §4 的特徵字典。欄位前綴 vio_ / eval_ / media_ / oper_ / display_。
   零膨脹百分位的實作見 §5.1，只套用在有自然零點且零值占比 > 20% 的指標。

3. model/train.py、model/backtest.py、model/score.py
   四維度加權（§5.0 權重表）、覆蓋率加權（§5.1）、
   同儕群內 ECDF（§5.2）、全市合併排序決定 tier。
   回測照 §6.2，主指標 Precision@50。

完成的定義（SPEC §14.1）：
- 八個 curated/*.json 產出，所有 assert 通過
- features.json 1,212 筆，正樣本 128 筆
- 評鑑 join 命中率 100%（1,101/1,101）
- Precision@50 >= 28.0%（低於這個數字模型沒有價值，見 §6.3）
- 分層結果（私立/公立/非營利）已寫入 curve.json
- 權重敏感度已掃描（違規權重 40–60%），寫入 model/metrics.json
- serving/*.json 每筆 reasons 1–3 條，code 全在 §4.6 表內，
  同一維度不超過 2 條，無佔位符殘留

絕對不要做：
- 不要用 0 填補缺失值。缺資料就 coverage=0，理由見 §3.4 的警告框。
- 不要把 penalty 欄位當特徵。
- 不要為了衝高 Precision@50 去調權重。敏感度檢查顯示 40–47.5% 會
  多命中 2 家，但我們刻意不改——那是對測試集過擬合（NARRATIVE §5.4）。

跑起來：
  export WATCHDOG_SALT="自訂字串"
  python etl/build_curated.py --out ./out/curated
  python model/score.py --in ./out/curated --model ./out/model --out ./out/serving

你卡住會擋住所有人。out/serving 一產出就通知 C。
```

---

## B — 營運維度

```
你負責從 PDF 抽出財務數字，算出營運係數。

先讀：
- docs/SPEC.md §5.6（營運維度，四個同儕群）、§4.4（oper_ 欄位）、
  §3.8（finance.json 契約）
- docs/營運係數.md（子指標的推導理由）
- etl/ocr_extract.py（已驗證能抽 46/46 份非營利財報，直接擴充它）

四個同儕群，各用各的公式：
  公立-獨立      21 園   O = 60%F + 25%E + 15%C
  公立-附設     273 園   O = 100%C
  非營利-有財報   12 園   O = 40%F + 45%H + 15%E
  非營利-無財報   41 園   applicable=false，不是 0 分
  私立          835 園   applicable=false

資料在哪（已全部確認可用，不要再花時間找）：
- 非營利財報：data/ocr/*.pdf，46 份，附表二「經費流用及勻支檢查表」
  已驗證可抽：人事費 46/46、加班費 46/46、勞退提撥 40/46、
  代課代班費 只有 21/46（該子指標 coverage 上限就是 46%）
- 公立決算：E_教育局-資料集/資料集/公校/1XX年度決算書/第5冊/
  「基金用途明細表」有 用人費用 / 正式員額薪資 / 加（夜）班費，
  每項都有預算數、決算數、差異、差異%
- 實際招生數：docs/總說明/*.md（112/113/114 年度，已是文字檔不用 OCR）
  格式如「113 學年度上學期，實際招收幼生 260 人」
  變體：實際招收[普通班|幼兒園]?N班，[學生|幼生]人數 M 人
  連班級數都有，可算每班人數
- 收費明細：data/新北市...收費明細.json
  280 筆 100% 是公立（檔名寫「與非營利」是錯的，非營利與私立都沒有）

你要產出：
1. etl/ocr_extract.py 擴充 — 加上公立決算書的抽表
2. etl/operation.py — F/H/E/C 子分數、§5.6.7 的 80/90 下限規則
3. out/curated/finance.json、fees.json（schema 見 §3.7、§3.8）

抽表核對規則（SPEC §3.10 第 8 步）：
  預算、決算、差異、執行率四欄必須互相核對。
  差異超過金額 0.5% 或執行率 1 個百分點 → 該欄標為待人工確認，不進模型。

完成的定義：
- 46 份非營利財報 + 21 園公立決算全部抽出
- 每個 oper_* 欄位標明風險方向（上尾/下尾/雙尾）
- finance.json 帶 sub_scores、operation_score、audit_floor_applied、
  validated（永遠 false）
- 查核表「否」只出現在 finance_flags，不在任何維度分數中

絕對不要做：
- 不要給私立或非營利-無財報打 0 分。它們是 applicable=false、score=null。
- 不要把查核表「否」放進分數。3,202 個判定只有 11 個「否」，
  而且與裁罰反向（安興 0 個否卻被罰，大觀 7 個否卻沒被罰）。
- 不要聲稱營運維度經過驗證。有財務資料的園總共 33 家，
  被罰過的只有個位數，無法驗證。validated 一律 false。
```

---

## C — 後端

```
你負責 9 支 API 與 Lambda 部署。

先讀：
- docs/SPEC.md §8（API 契約，已凍結）、§8.0（通用規範）、§7.3（部署規格）
- backend/app.py（骨架已寫好，9 支路由已通，對 mock 煙霧測試過）
- backend/local_server.py（本機開發用）

現況：app.py 已能對 frontend/mock/ 回應全部 9 支 API。
你的工作是補完、加測試、接上真實 serving 資料、部署。

你要產出：
1. backend/app.py 補完
   - /parks/{id}/brief 的 briefs.json 讀取（A 產出後才有）
   - /map 的 town 篩選（mock 的 properties 目前沒有 town 欄位）
   - 回應加 schema 驗證，契約不符要在開發期就爆錯
2. backend/template.yaml（SAM 函式定義）
3. backend/tests/ — 每支 API 至少一個測試，含 404 與 400 路徑

完成的定義（SPEC §14.2）：
- 9 支 API schema 與 §8 完全一致
- 冷啟 < 3s，熱請求 p99 < 200ms
- 錯誤格式統一，不洩漏 bucket 名稱或 stack trace
- x-request-id 每個回應都有，且能在 CloudWatch Logs 查到
- /parks/{id} 傳不存在的 id 回 404 而非 500
- /worklist 回傳內容不含任何自然人姓名
- IAM role 只有 serving/* 與 raw/pdf/* 的 s3:GetObject

跑起來：
  SERVING_DIR=./frontend/mock python backend/local_server.py
  curl http://localhost:8000/api/v1/meta

絕對不要做：
- 不要改 §8 的欄位名。前端已照它開發，要改先在群組講。
- 不要在 Lambda 裡連資料庫。母體 1,178 筆、約 3 MB，
  冷啟讀進記憶體就好，理由見 §8.0 最後一段。
- 不要在 API 路徑上呼叫 Bedrock。1 RPS 限制，所有 LLM 產出離線預算。
```

---

## D — 前端

```
你負責 7 個頁面。你不需要等後端或模型，現在就能全速開工。

先讀：
- docs/FRONTEND.md 全部（設計 token、13 個元件、7 頁版面、
  狀態設計、無障礙、列印樣式）
- docs/SPEC.md §8（API 契約）、§9.2（三條系統層級規則）

立刻開工：
  cd frontend && npm install && VITE_API_BASE=mock npm run dev

frontend/mock/ 已有 9 份符合契約的假資料，用真實園名與座標產生，
母體 1,178 筆，涵蓋邊界案例：
  停辦 37 園 / 無評鑑 140 園 / 無營運 905 園 / 裁罰超過 8 筆 25 園

七個頁面（FRONTEND.md §5 各有版面圖與驗收）：
  1. 總覽搜尋 /            5. 行政區熱力圖 /districts
  2. 風險列表 /risk        6. 成效驗證 /validation ★ 決勝頁
  3. 地圖 /map             7. 稽查派工單 /worklist ★ 主線產出
  4. 單園詳情 /park/:id

技術選型已定（FRONTEND.md §9.1）：
  React 18 + TypeScript + Vite / React Router v6 /
  URL query string + TanStack Query（不用 Redux）/
  CSS Modules + design token（不引入 UI 框架）/
  自繪 SVG 圖表（不引入圖表庫）/ MapLibre GL JS

完成的定義（FRONTEND.md §10）：
- 七頁皆可直接以網址抵達；篩選狀態寫進 URL 可分享
- 任何顯示分數處，同一視野內可見 reasons
- 四種狀態（載入/空/錯誤/缺資料）在每個資料區塊皆已實作
- 派工單列印每項不跨頁，灰階可讀
- axe DevTools 零 critical；JS bundle < 250 KB gzip
- 1280/1024/768/375 四個寬度不破版

絕對不要做：
- 分級不要用綠色，也不要做連續色階。低分的語意是「這週不優先查」，
  不是「安全」。理由見 FRONTEND.md §1.3。
- 不要顯示任何自然人姓名。API 回的是 owner_key 雜湊值。
- 不要自己拼接原因文案。reasons[].label 由後端產生，直接顯示。
- 不要把 applicable=false 的維度畫成 0 分或「載入中」。
  顯示 —— 與 note 文字。

接真實後端時只要改：VITE_API_BASE=http://localhost:8000/api/v1
```

---

## E — 雲端

```
你負責基礎設施與部署。

先讀：
- docs/SPEC.md §7（AWS 架構）、§7.4（IaC 資源清單）、§10（合規限制）
- docs/黑客松競賽環境規範與限制_20260722.pdf

你要產出：
1. infra/template.yaml（SAM）
   DataBucket / SiteBucket / SiteOAC / SiteBucketPolicy /
   Distribution / HttpApi / ApiFunctionRole
2. 部署腳本與 CI

⚠ 2026-09-12 更新：E 軌已完成並部署，驗收 11/11 通過。
   https://d2p0ksy36o4foe.cloudfront.net
   下面保留給接手或重建的人。

關鍵設定（照 §7.4，不要自己發明）：
- Region 一律 us-west-2（規範指定 us-east-1 或 us-west-2）
- 兩個 bucket 的 PublicAccessBlockConfiguration 四項全 true
- CloudFront 走 OAC，SigningBehavior: always
- SPA 路由用 CloudFront Function（viewer-request），
  絕對不要用 CustomErrorResponses——它對整個 distribution 生效，
  會把 API 正常回的 404 也改寫成 /index.html。實測紀錄見
  infra/README.md 的「踩過的坑」。
- /api/* behavior TTL 60s，轉發 query string，不轉發 cookie
- Lambda：Python 3.12 / 512MB / 10s / ReservedConcurrentExecutions 10
- Lambda IAM 只給 serving/* 與 raw/pdf/* 的 s3:GetObject，不給寫入

完成的定義（SPEC §14.4）：
- sam deploy 從零可重建全部資源
- aws s3api get-public-access-block 驗證四項全開
- 直接存取 S3 物件 URL 回 403，經 CloudFront 回 200
- /park/xxx 直接輸入網址正常載入
- 全部資源在 us-west-2
- CloudWatch Logs 保留期已設定（建議 7 天）

絕對不要做：
- 不要建公開 S3 bucket 或用 S3 Website Hosting，違反競賽規範。
- 不要部署 SageMaker Endpoint。本系統不做線上推論，
  分數是離線批次算好的靜態結果（SPEC §0 關鍵前提）。
- 不要把 AWS 憑證寫進 repo。競賽用的是短期 STS token，
  放在專案外再 source，.gitignore 已涵蓋 .env / *credentials* / aws-env.ps1。
- 團隊若有人用 Kiro，/.kiro 資料夾必須保留在 repo，不可加進 .gitignore。
```

---

## 里程碑與交接點

| 階段 | A 資料模型 | B 營運 | C 後端 | D 前端 | E 雲端 |
|---|---|---|---|---|---|
| **M1** | ETL → curated | 非營利財報抽表 | 補完 app.py | 頁面骨架 + 元件庫 | S3 + IaC 骨架 |
| **M2** | 四維度分數 + 回測 | 公立決算抽表 | 接真實 serving | 搜尋頁 + 風險列表 | CloudFront + OAC |
| **M3** | 分層驗證 + 效益曲線 | 營運係數 + 下限規則 | 部署 Lambda | 地圖 + 詳情 + 熱力圖 | 部署串接 |
| **M4** | 輿情補標 2,320 篇 | finance.json 交付 | 派工單 API | 成效驗證 + 派工單 | 壓測 + 監控 |
| **M5** | 共同：簡報、Demo 腳本、Q&A 預備（NARRATIVE.md §7） | | | | |

三個硬交接點：

1. **B → A**：`finance.json` 交付。A 在此之前用 `coverage=0` 佔位，不會被擋。
2. **A → C**：`out/serving/*.json` 產出。C 在此之前用 `frontend/mock/` 開發。
3. **C → D**：真實 API 上線。D 在此之前用 `VITE_API_BASE=mock`。

**降級順序**（時間不足時依序砍，SPEC §11.1）：
1. 砍 XGBoost 挑戰者，只留規則式加權
2. 砍派工單的 LLM 白話文生成，只留模板
3. 砍行政區熱力圖，改用地圖點位著色
4. **不可砍**：時間切分回測與效益曲線、稽查派工單、輿情補標

---

## 剩下的三個真實風險

不是未知，是還沒做完的事。

| 風險 | 影響 | 誰負責 |
|---|---|---|
| 輿情 `doc_analysis` 只標了 580/2,900 | 不補標則園級輿情只覆蓋 40 園（3.3%），15% 權重形同虛設 | A，M4，Bedrock 1 RPS 約 39 分鐘 |
| 公立決算書 21 園的抽表尚未實作 | 公立-獨立同儕群的 F、E 維度無資料 | B，M2 |
| 前端與 IaC 尚未開始 | — | D、E |

其餘皆已驗證：非營利財報抽表 46/46、公立決算表格結構、實際招生數來源、評鑑 join 100%、後端 9 支路由對 mock 通過。
