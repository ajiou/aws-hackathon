# 部署基礎設施。SPEC §7.4。
#
#   . $HOME/aws-env.ps1          # 先 source 競賽憑證（不在 repo 裡）
#   ./infra/deploy.ps1
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

# 2. 建置 Lambda 套件。
#
#    backend/ 的程式用絕對匯入（from backend.x import y），這樣 uvicorn 與
#    pytest 都能從 repo 根目錄執行。因此 zip 裡必須有一個真正的 backend/
#    目錄，不能只是它的零散內容 —— 這就是 CodeUri 指向 out/lambda/ 的原因。
#
#    另外 aws cloudformation package 只打包不安裝相依。fastapi、mangum、
#    pydantic 都不在 Lambda runtime 內，必須自己裝進去。
$stage    = Join-Path $root "out/lambda"
$stagePkg = Join-Path $stage "backend"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stagePkg | Out-Null

Write-Output "建置 Lambda 套件 ..."
Get-ChildItem (Join-Path $root "backend") -Filter "*.py" |
    Where-Object { $_.Name -ne "local_server.py" } |
    Copy-Item -Destination $stagePkg

python -m pip install --quiet --target $stage --only-binary=:all: `
    --platform manylinux2014_x86_64 --python-version 3.12 `
    -r (Join-Path $root "backend/requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install 失敗" }

# boto3 / botocore 已在 Lambda runtime 內，移掉可省下約 15 MB 與冷啟時間
Get-ChildItem $stage -Directory |
    Where-Object {
        $_.Name -match '^(boto3|botocore|s3transfer|dateutil|urllib3|jmespath|six)' -or
        $_.Name -match '\.dist-info$'
    } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$mb = [math]::Round(((Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Output "  套件大小 $mb MB"

# 3. 打包並上傳
$packaged = Join-Path $env:TEMP "watchdog-packaged.yaml"
Write-Output "上傳 Lambda 套件 ..."
aws cloudformation package `
    --template-file (Join-Path $PSScriptRoot "template.yaml") `
    --s3-bucket $artifactBucket `
    --output-template-file $packaged `
    --region $Region
if ($LASTEXITCODE -ne 0) { throw "package 失敗" }

# 4. 部署
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
Write-Output "  ./infra/upload.ps1     # 上傳 serving 資料與前端"
Write-Output "  ./infra/verify.ps1     # 驗收 SPEC §14.4"
