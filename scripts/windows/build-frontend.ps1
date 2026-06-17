# 构建 Huoke Vue 管理台静态资源
param(
    [string]$FrontendRoot = "$PSScriptRoot\..\..\frontend",
    [string]$OutputDir = "$PSScriptRoot\..\..\dist-sidecar\frontend-dist"
)

$ErrorActionPreference = "Stop"
Push-Location $FrontendRoot
try {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    npm run build
    if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
    Copy-Item -Recurse "dist" $OutputDir
    Write-Host "[frontend] 输出: $OutputDir" -ForegroundColor Green
} finally {
    Pop-Location
}
