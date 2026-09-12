# 上傳資料與前端。SPEC §7.4 部署順序第 2、3 步。
param(
    [string]$StackName = "watchdog-infra",
    [string]$Region    = "us-west-2",
    [switch]$UseMock                       # 還沒有真實 serving 時用 mock 先跑通
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Out-Val($key) {
    aws cloudformation describe-stacks --stack-name $StackName --region $Region `
        --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
}
$dataBucket = Out-Val "DataBucketName"
$siteBucket = Out-Val "SiteBucketName"
$distId     = Out-Val "DistributionId"
Write-Output "data=$dataBucket  site=$siteBucket  dist=$distId"

# serving 資料
$serving = if ($UseMock) { Join-Path $root "frontend\mock" } else { Join-Path $root "out\serving" }
if (Test-Path $serving) {
    Write-Output "上傳 serving/ <- $serving"
    aws s3 sync $serving "s3://$dataBucket/serving/" --exclude "*.py" --region $Region
} else {
    Write-Output "略過 serving（$serving 不存在）"
}

# 前端 build
$dist = Join-Path $root "frontend\dist"
if (Test-Path $dist) {
    Write-Output "上傳前端 <- $dist"
    aws s3 sync $dist "s3://$siteBucket/" --delete --region $Region
    aws cloudfront create-invalidation --distribution-id $distId --paths "/*" `
        --query "Invalidation.Id" --output text
} else {
    Write-Output "略過前端（先跑 cd frontend; npm run build）"
}
