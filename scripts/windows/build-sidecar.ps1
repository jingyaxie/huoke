# Build sidecar distribution for electron-builder extraResources
param(
    [string]$OutputRoot = "$PSScriptRoot\..\..\dist-sidecar"
)

$ErrorActionPreference = "Stop"
& "$PSScriptRoot\install-sidecar.ps1" -InstallRoot $OutputRoot -SkipPlaywright:$false
if (Test-Path "$PSScriptRoot\..\..\frontend\package.json") {
    & "$PSScriptRoot\build-frontend.ps1" -OutputDir (Join-Path $OutputRoot "frontend-dist")
}
Write-Host "[build-sidecar] ready: $OutputRoot" -ForegroundColor Green
