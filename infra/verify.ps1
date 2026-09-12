# 驗收 SPEC §14.4。每一項都是可被別人獨立重跑的檢查。
param(
    [string]$StackName = "watchdog-infra",
    [string]$Region    = "us-west-2"
)
$ErrorActionPreference = "Continue"
$pass = 0; $fail = 0
function Check($name, $ok, $detail) {
    if ($ok) { Write-Output "  [PASS] $name"; $script:pass++ }
    else     { Write-Output "  [FAIL] $name — $detail"; $script:fail++ }
}
function Out-Val($key) {
    aws cloudformation describe-stacks --stack-name $StackName --region $Region `
        --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
}

Write-Output "SPEC §14.4 雲端驗收`n"

# 1. 全部資源在 us-west-2
$stackRegion = (aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].StackId" --output text) -split ":" | Select-Object -Index 3
Check "全部資源在 us-west-2" ($stackRegion -eq "us-west-2") "實際為 $stackRegion"

# 2. 兩個 bucket 的 Block Public Access 四項全開
foreach ($k in @("DataBucketName","SiteBucketName")) {
    $b = Out-Val $k
    $j = aws s3api get-public-access-block --bucket $b --region $Region `
        --query "PublicAccessBlockConfiguration" --output json | ConvertFrom-Json
    $all = $j.BlockPublicAcls -and $j.IgnorePublicAcls -and $j.BlockPublicPolicy -and $j.RestrictPublicBuckets
    Check "$b Block Public Access 四項全開" $all ($j | ConvertTo-Json -Compress)
}

# 3. 直接存取 S3 物件回 403，經 CloudFront 回 200
$site = Out-Val "SiteBucketName"
$direct = "https://$site.s3.$Region.amazonaws.com/index.html"
$code = (curl.exe -s -o NUL -w "%{http_code}" $direct)
Check "直接存取 S3 物件被拒" ($code -eq "403") "實際 HTTP $code"

$url = Out-Val "SiteUrl"
$code = (curl.exe -s -o NUL -w "%{http_code}" "$url/")
Check "經 CloudFront 取首頁" ($code -eq "200") "實際 HTTP $code"

# 4. SPA fallback：深層路由直接輸入網址要回 200
$code = (curl.exe -s -o NUL -w "%{http_code}" "$url/park/does-not-exist")
Check "SPA fallback（/park/xxx 回 200）" ($code -eq "200") "實際 HTTP $code"

# 5. API 可用且不洩漏內部資訊
$api = Out-Val "ApiUrl"
$meta = curl.exe -s "$api/meta"
Check "GET /meta 回傳 JSON" ($meta -match '"population"') $meta
$err = curl.exe -s "$api/parks/does-not-exist"
Check "不存在的 park 回 PARK_NOT_FOUND" ($err -match "PARK_NOT_FOUND") $err
Check "錯誤訊息不洩漏 bucket 名稱" (-not ($err -match $site)) "錯誤訊息含 bucket 名稱"

# 6. Lambda IAM 只有唯讀
$role = aws iam list-roles --query "Roles[?contains(RoleName,'watchdog')].RoleName" --output text
$hasWrite = $false
foreach ($r in ($role -split "\s+" | Where-Object { $_ })) {
    $pol = aws iam list-role-policies --role-name $r --query "PolicyNames" --output text
    foreach ($p in ($pol -split "\s+" | Where-Object { $_ })) {
        $doc = aws iam get-role-policy --role-name $r --policy-name $p --output json
        if ($doc -match "s3:PutObject" -or $doc -match "s3:DeleteObject") { $hasWrite = $true }
    }
}
Check "Lambda IAM 無 S3 寫入權限" (-not $hasWrite) "發現 PutObject/DeleteObject"

# 7. CloudWatch Logs 保留期已設定
$ret = aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/watchdog" `
    --region $Region --query "logGroups[0].retentionInDays" --output text
Check "CloudWatch Logs 保留期已設定" ($ret -ne "None" -and $ret) "retentionInDays=$ret"

Write-Output "`n通過 $pass 項，失敗 $fail 項"
if ($fail -gt 0) { exit 1 }
