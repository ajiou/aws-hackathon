# 部署基礎設施。SPEC §7.4。
#
#   . $HOME\aws-env.ps1          # 先 source 競賽憑證（不在 repo 裡）
#   .\infra\deploy.ps1
#
# 不需要 SAM CLI：aws cloudformation package 做同樣的打包工作。

param(
    [string]$StackName = "watchdog-infra",
    [string]$Region    = "us-west-2"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$account = (aws sts get-caller-identity --query Account --output text)
if (-not $account) { throw "取不到 AWS 帳號，先 source 憑證" }
$artifactBucket = "watchdog-artifacts-$account"

Write-Output "帳號 $account｜區域 $Region｜stack $StackName"

# 1. 打包用的 bucket（存 Lambda zip），private
$exists = aws s3api head-bucket --bucket $artifactBucket 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Output "建立打包 bucket $artifactBucket"
    aws s3api create-bucket --bucket $artifactBucket --region $Region `
        --create-bucket-configuration LocationConstraint=$Region | Out-Null
    aws s3api put-public-access-block --bucket $artifactBucket `
        --public-access-block-configuration `
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" | Out-Null
}

# 2. 打包：把 backend/ 上傳並改寫 CodeUri
$packaged = Join-Path $env:TEMP "watchdog-packaged.yaml"
Write-Output "打包 backend/ ..."
aws cloudformation package `
    --template-file (Join-Path $PSScriptRoot "template.yaml") `
    --s3-bucket $artifactBucket `
    --output-template-file $packaged `
    --region $Region
if ($LASTEXITCODE -ne 0) { throw "package 失敗" }

# 3. 部署
Write-Output "部署中（CloudFront 首次建立約 10-15 分鐘）..."
aws cloudformation deploy `
    --template-file $packaged `
    --stack-name $StackName `
    --capabilities CAPABILITY_IAM `
    --region $Region `
    --no-fail-on-empty-changeset
if ($LASTEXITCODE -ne 0) { throw "deploy 失敗" }

Write-Output "`n=== Outputs ==="
aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}" --output table

Write-Output "`n下一步："
Write-Output "  .\infra\upload.ps1     # 上傳 serving 資料與前端"
Write-Output "  .\infra\verify.ps1     # 驗收 SPEC §14.4"
