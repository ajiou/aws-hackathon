# D 前端 · 小小守護員

React 18、TypeScript、Vite、React Router v6、TanStack Query、Tailwind CSS 4、shadcn/ui（Radix）、Lucide React、CSS Modules、Zod 與 MapLibre。實作依據：[`FRONTEND.md`](../docs/FRONTEND.md)、[`SPEC.md`](../docs/SPEC.md) §8／§9.2。

## 啟動

需要 Node.js 22.12+ 或 24。

```powershell
cd frontend
npm ci
npm run dev -- --mode mock
```

開啟 http://127.0.0.1:5173 。也支援 README 原定的 `VITE_API_BASE=mock`；PowerShell 請使用 `$env:VITE_API_BASE = 'mock'`。

正式 API：

```powershell
$env:VITE_API_BASE = 'http://localhost:8000/api/v1'
npm run dev
```

正式建置預設使用同源 `/api/v1`：

```powershell
Remove-Item Env:VITE_API_BASE -ErrorAction SilentlyContinue
npm run build
```

靜態示範建置：`npm run build:mock`。`npm run preview` 預覽 `dist/`。

正式建置不包含 mock 檔案。部署需依 E 的規格設定 CloudFront SPA fallback；不使用公開 S3 網站。

## 頁面

| 路由 | 功能 |
|---|---|
| `/` | 園名搜尋、可搜尋多選行政區／設立別／分級、排序、50／100／200 筆分頁、篩選 chip |
| `/risk` | 前 50／100／200 名，直接展開後端原因，導向派工單 |
| `/map` | 設立別彩色點位、數量叢集、公立／非營利／私立複選、行政區與風險篩選、園所基本資料彈窗、行政區模式 |
| `/park/:id` | 四維度、meta 權重、覆蓋率、原因、財務旗標、建議、切點時間軸、四個資料頁籤 |
| `/districts` | 29 區邊界，以高風險比例著色，排行排序與地圖 hover 連動 |
| `/validation` | SVG 四條效益曲線、K=50 標示、完整數據、分層指標與公立模型限制 |
| `/worklist` | 週次與名額 URL 狀態、A4 每頁兩家、原因／法條建議／簽章、頁碼 |

搜尋、排序、分頁、頁籤、週次、名額與地圖選取使用 URL。請求逾時 10 秒，5xx 間隔 1 秒重試一次，4xx 不重試；錯誤不呈現原始伺服器訊息。所有 API 回應通過 Zod；顯示欄位採白名單，不保留 `owner_key` 等個人識別欄位。

主要導覽改為頂部橫向選單，手機可橫向捲動。右上方搜尋在總覽與地圖頁會即時套用；其他頁面送出搜尋後前往總覽。地圖點位和鍵盤園所選單皆可開啟 shadcn Dialog，顯示地址、電話、核定人數與完整分析連結，支援 Escape 關閉及焦點返回。

## 地圖底圖

採用 [OpenFreeMap](https://openfreemap.org/) 的 OpenMapTiles 向量底圖，不需要 API key。底圖樣式集中於 `src/components/mapStyle.ts`：

- 保留道路、河流、綠地與行政區界，行政區名稱取自本地 29 區邊界。
- 縮小時顯示主幹道；放大至 zoom 13 顯示次要道路與主要道路名，不顯示巷弄名稱。
- zoom 11 起顯示排名靠前（rank ≤ 3）的車站、醫院、博物館、公園、市政機關，zoom 12 起顯示公園名稱；不顯示一般商店、餐廳、便利商店或公車站等密集標籤。
- 中文名稱優先，標籤碰撞時自動隱藏，園所點位繪製於底圖上方。

道路與地標需要網路；行政區界、行政區名與園所點位不依賴外部圖磚。保留 OpenFreeMap、OpenMapTiles、OpenStreetMap 來源標示。行政區邊界為 2011 年資料，僅供分布示意。已移除先前的 CARTO 無標籤模式，不再需要 `VITE_CARTO_API_KEY`。

正式 `/map` 若未提供設立別，會以 `/parks` 每頁 200 筆讀取完整清單並依 `park_id` 串接；不依園名推測分類。資料快取五分鐘，搜尋和篩選在本地執行。行政區熱力使用全市統計，不套用園所分布的篩選。

## 驗證

```powershell
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Vitest 驗證契約、缺資料、重試／逾時與元件語意；Playwright 驗證七頁直連、axe critical／serious、URL 還原、四種寬度、鍵盤選單、地圖選取、列印展開及 PDF。輸出在 `test-results/`（不進版控）。MapLibre 為延遲載入 chunk，首次開啟總覽不需下載。

本次改版驗證：正式建置、14 項單元測試與 8 項 Chromium 瀏覽器情境通過；包含實際 Canvas 點位點擊、設立別篩選、基本資料彈窗、跨頁搜尋、手機版及 25 頁列印 PDF。未執行需要另外設定 `LIVE_API` 的 3 項線上 API 測試。

## 資料與後端交接

- `mock/` 是既有示範資料，不代表真實風險或驗證結果。所有原因直接顯示資料來源文案。原始 mock 第 40、47 張派工單不足三條原因，已在產生器與 fixture 補上該園既有的行政區輿情訊號。
- mock 派工單僅有 50 筆已撰寫建議；選 100／200 時標示回傳不足，只列印實際回傳內容，不編造其餘項目。
- 本次後端 `/parks` 不附原因，前端透過 `/parks/{id}` 取得，並以 Query 快取；原因取得前不顯示分數。
- 本次後端尚未支援停辦園清單，正式 API 模式的「包含已停辦」會顯示不支援；mock 可驗證。`/parks` 的 `dir` 參數仍需 C 確認依契約排序；前端傳入與保存 URL。
- 已補上既有後端 `/parks/{id}/brief` 所需的 `mock/briefs.json`；建議取自已撰寫的派工單，其餘園所顯示尚未提供建議。產生器可重建此檔。
- 既有後端 `/worklist` 固定讀檔，尚未依週次與 K 取資料。前端顯示回傳週次，與選定週次不符時停用列印，避免印錯週次。
- 現有 mock 沒有評鑑、收費、財報 PDF 明細，頁籤保留並說明缺失。Zod 支援 SPEC §3.7 收費文件、§3.8 財報文件及 presigned URL；完整資料需 A／B／C 提供。
- OpenFreeMap 道路與地標需要網路，行政區輪廓、區名與叢集數字使用本地資料及字型。WebGL 或底圖失敗仍可使用園所選單及本地行政區邊界。邊界來源與年份見 [`public/BOUNDARIES.md`](public/BOUNDARIES.md)。
- 依規格保留 React Router v6。安裝時 npm audit 回報該主要版本的兩項中等風險（反斜線重導向、SSR 錯誤反序列化）；本前端沒有 SSR，也不把使用者輸入當導航目的地。升級 v7 需另行調整指定技術版本。MapLibre 與 Vitest 已使用修補版本。

實體印表機、正式 API、CloudFront 部署，以及不同機器的 Lighthouse／LCP 與地圖渲染時間應在交付環境再次驗證；不能由本機建置結果推定。

效能複測：先 `npm run build:mock` 並啟動 `npm run preview`（4173），另開終端執行 `node scripts/performance.mjs`。報告寫入 `test-results/lighthouse.html` 與 `performance.json`。地圖時間從加入 GeoJSON source 計至首次 source 完成後 render，包含點位解析及叢集；不把底圖下載列入點位渲染時間。

改版前的本機效能基準（2026-09-12，Chromium／1280×900，mock 正式建置）：桌機 Lighthouse 93、LCP 653 ms、TBT 0 ms、1,178 點來源解析至繪製 173 ms。這些效能數字尚未針對本次 Tailwind／shadcn 改版重測。
