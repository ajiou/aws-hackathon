# 基礎設施

`template.yaml` 的註解保持純 ASCII —— AWS CLI 以系統編碼讀檔，Windows 的
cp950 無法解析 UTF-8 中文，會讓 `validate-template` 與 `package` 直接失敗。
中文說明放在這裡。

## 架構決定

| 決定 | 理由 |
|---|---|
| **不部署 SageMaker Endpoint** | 母體固定 1,178 園、資料日更一次，沒有線上推論需求。分數離線算好寫入 S3，Lambda 只做讀取與篩選。省掉最大的成本與部署風險。 |
| **不用 DynamoDB** | `serving/*.json` 約 3 MB，Lambda 冷啟載入模組層全域變數即可。維護一套 schema 與 GSI 比直接讀 JSON 更慢也更容易出錯。 |
| **單一 Lambda 內部路由** | 9 支 API 共用一個函式，減少冷啟次數與部署複雜度。 |
| **S3 不開 Website Hosting** | 靜態網站代管需要公開 bucket，違反競賽規範第 1 條。改走 CloudFront + OAC，bucket 維持 private。 |
| **SPA 路由用 CloudFront Function，不用 CustomErrorResponses** | `CustomErrorResponses` 對整個 distribution 生效，無法只綁一個 behavior。用它的話 API 正常回的 404 也會被改寫成 `/index.html`，前端收到的會是 S3 的 `AccessDenied` XML。實測見下方。 |
| **DataBucket 設 DeletionPolicy: Retain** | 刪 stack 時不會連資料一起刪掉。 |

## 資源

| 邏輯名稱 | 型別 | 重點設定 |
|---|---|---|
| `DataBucket` | S3 | private、SSE-S3、版本控制、Retain |
| `SiteBucket` | S3 | private、SSE-S3 |
| `SiteOAC` | CloudFront OAC | `SigningBehavior: always` |
| `SiteBucketPolicy` | S3 Policy | 只允許本 distribution 讀取；拒絕非 HTTPS |
| `ApiCachePolicy` | CloudFront | TTL 60s、query string 進 cache key、不轉發 cookie |
| `Distribution` | CloudFront | 兩個 behavior：`/api/*` → HttpApi、預設 → SiteBucket |
| `ApiFunction` | Lambda | Python 3.12 / 512 MB / 10s / 保留並行 10 |
| `HttpApi` | API Gateway | `$default` stage、限流 20 rps |
| `ApiLogGroup` | CloudWatch Logs | 保留 7 天 |

Lambda 的 IAM 只有 `serving/*` 與 `raw/pdf/*` 的 `s3:GetObject`——沒有寫入、
沒有 `curated/`、沒有 `model/`。

## 踩過的坑：CustomErrorResponses 會吃掉 API 的錯誤碼

第一版照常見的 SPA 教學，用 `CustomErrorResponses` 把 403/404 對應到
`/index.html` 回 200。部署後驗收發現：

```
直連 API Gateway：
  GET /api/v1/parks/does-not-exist
  → HTTP 404  {"error":{"code":"PARK_NOT_FOUND", ...}}

經 CloudFront：
  GET /api/v1/parks/does-not-exist
  → HTTP 403  <Error><Code>AccessDenied</Code></Error>
```

原因：`CustomErrorResponses` 是 distribution 層級設定，**不能只綁一個
behavior**。API 回的 404 被攔截後，CloudFront 轉去預設 origin（S3）撈
`/index.html`，當時 bucket 是空的，於是回 S3 的 AccessDenied。

即使 bucket 有 `index.html`，結果也只是變成「API 錯誤回傳一頁 HTML」，
SPEC §8.0 的錯誤契約一樣失效。

改用 viewer-request 的 CloudFront Function，第一行就讓 `/api/` 原樣通過。

## 操作

```powershell
. $HOME\aws-env.ps1          # 競賽憑證，不在 repo 裡

.\infra\deploy.ps1           # 建立/更新 stack（CloudFront 首次約 10-15 分鐘）
.\infra\upload.ps1 -UseMock  # 先用 mock 把整條路徑跑通
.\infra\upload.ps1           # 有真實 out/serving 之後改用這個
.\infra\verify.ps1           # 驗收 SPEC §14.4
```

不需要 SAM CLI。`aws cloudformation package` 做同樣的打包工作，少一個相依。

## 刪除

```powershell
aws cloudformation delete-stack --stack-name watchdog-infra --region us-west-2
```

`DataBucket` 因為 `DeletionPolicy: Retain` 會留下來，要手動清空再刪。
CloudFront distribution 的刪除約需 15 分鐘。
