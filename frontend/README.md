# D 前端 · 小小守護員

React 18、TypeScript、Vite、React Router v6、TanStack Query、CSS Modules、Zod 與 MapLibre。實作依據：[`FRONTEND.md`](../docs/FRONTEND.md)、[`SPEC.md`](../docs/SPEC.md) §8／§9.2。

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
| `/map` | Canvas 點位、最高風險叢集、鍵盤園所選單、原因側欄、行政區模式 |
| `/park/:id` | 四維度、meta 權重、覆蓋率、原因、財務旗標、建議、切點時間軸、四個資料頁籤 |
| `/districts` | 29 區邊界，以高風險比例著色，排行排序與地圖 hover 連動 |
| `/validation` | SVG 四條效益曲線、K=50 標示、完整數據、分層指標與公立模型限制 |
| `/worklist` | 週次與名額 URL 狀態、A4 每頁兩家、原因／法條建議／簽章、頁碼 |

搜尋、排序、分頁、頁籤、週次、名額與地圖選取使用 URL。請求逾時 10 秒，5xx 間隔 1 秒重試一次，4xx 不重試；錯誤不呈現原始伺服器訊息。所有 API 回應通過 Zod；顯示欄位採白名單，不保留 `owner_key` 等個人識別欄位。

## 驗證

```powershell
npm test
npx playwright install chromium
npm run test:e2e
npm run build
```

Vitest 驗證契約、缺資料、重試／逾時與元件語意；Playwright 驗證七頁直連、axe critical／serious、URL 還原、四種寬度、鍵盤選單、地圖選取、列印展開及 PDF。輸出在 `test-results/`（不進版控）。MapLibre 為延遲載入 chunk，首次開啟總覽不需下載。

## 資料與後端交接

- `mock/` 是既有示範資料，不代表真實風險或驗證結果。所有原因直接顯示資料來源文案。原始 mock 第 40、47 張派工單不足三條原因，已在產生器與 fixture 補上該園既有的行政區輿情訊號。
- mock 派工單僅有 50 筆已撰寫建議；選 100／200 時標示回傳不足，只列印實際回傳內容，不編造其餘項目。
- 本次後端 `/parks` 不附原因，前端透過 `/parks/{id}` 取得，並以 Query 快取；原因取得前不顯示分數。
- 本次後端尚未支援停辦園清單，正式 API 模式的「包含已停辦」會顯示不支援；mock 可驗證。`/parks` 的 `dir` 參數仍需 C 確認依契約排序；前端傳入與保存 URL。
- 已補上既有後端 `/parks/{id}/brief` 所需的 `mock/briefs.json`；建議取自已撰寫的派工單，其餘園所顯示尚未提供建議。產生器可重建此檔。
- 既有後端 `/worklist` 固定讀檔，尚未依週次與 K 取資料。前端顯示回傳週次，與選定週次不符時停用列印，避免印錯週次。
- 現有 mock 沒有評鑑、收費、財報 PDF 明細，頁籤保留並說明缺失。Zod 支援 SPEC §3.7 收費文件、§3.8 財報文件及 presigned URL；完整資料需 A／B／C 提供。
- 地圖的 OpenStreetMap 底圖需要網路，叢集數字使用本機字型。WebGL 或底圖失敗仍可使用園所選單及本地行政區邊界。邊界來源與年份見 [`public/BOUNDARIES.md`](public/BOUNDARIES.md)。
- 依規格保留 React Router v6。安裝時 npm audit 回報該主要版本的兩項中等風險（反斜線重導向、SSR 錯誤反序列化）；本前端沒有 SSR，也不把使用者輸入當導航目的地。升級 v7 需另行調整指定技術版本。MapLibre 與 Vitest 已使用修補版本。

實體印表機、正式 API、CloudFront 部署，以及不同機器的 Lighthouse／LCP 與地圖渲染時間應在交付環境再次驗證；不能由本機建置結果推定。

效能複測：先 `npm run build:mock` 並啟動 `npm run preview`（4173），另開終端執行 `node scripts/performance.mjs`。報告寫入 `test-results/lighthouse.html` 與 `performance.json`。地圖時間從加入 GeoJSON source 計至首次 source 完成後 render，包含點位解析及叢集；不把底圖下載列入點位渲染時間。

本機驗收（2026-09-12，Chromium／1280×900，mock 正式建置）：10 個單元測試與 5 個瀏覽器情境通過；七頁 axe 無 critical／serious；PDF 共 25 頁，每頁兩個簽章欄；桌機 Lighthouse 93、LCP 653 ms、TBT 0 ms、1,178 點來源解析至繪製 173 ms。首次總覽 JS 約 90 KB gzip（主程式、總覽、篩選、mock adapter 合計），不含延遲載入的 MapLibre 與 worker。
