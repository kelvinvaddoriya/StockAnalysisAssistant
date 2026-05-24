# frontend/deploy.ps1
# Usage: .\deploy.ps1 [-Bucket bourse-frontend-218160094200] [-DistributionId E2XQ3GPU9YS7D3]
param(
    [string]$Bucket = 'bourse-frontend-218160094200',
    [string]$DistributionId = 'E2XQ3GPU9YS7D3'
)

Write-Host "Building frontend..." -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed"; exit 1 }

Write-Host "Uploading to s3://$Bucket ..." -ForegroundColor Cyan
aws s3 sync dist/ "s3://$Bucket" --delete --cache-control "max-age=31536000,immutable"

# index.html must never be cached so CloudFront always serves the latest shell.
# --metadata-directive REPLACE wipes auto-detected Content-Type, so set it explicitly.
aws s3 cp "s3://$Bucket/index.html" "s3://$Bucket/index.html" `
    --metadata-directive REPLACE `
    --content-type "text/html; charset=utf-8" `
    --cache-control "no-cache,no-store,must-revalidate"

Write-Host "Invalidating CloudFront /index.html ..." -ForegroundColor Cyan
aws cloudfront create-invalidation --distribution-id $DistributionId --paths '/index.html' | Out-Null

Write-Host "Done. https://$((aws cloudfront get-distribution --id $DistributionId --query 'Distribution.DomainName' --output text))" -ForegroundColor Green
