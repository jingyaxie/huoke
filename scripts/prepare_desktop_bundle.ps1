# Prepare desktop bundle before Tauri build (frontend dist + Python backend)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$BundleDir = Join-Path $Root "desktop/bundle"
$BackendSrc = Join-Path $Root "backend"
$RuntimeDir = Join-Path $BundleDir "runtime"
$VenvDir = Join-Path $RuntimeDir ".venv"
$TargetBackend = Join-Path $BundleDir "backend"

Write-Host "Building frontend (same-origin /api)..."
Push-Location $FrontendDir
if (-not (Test-Path "node_modules")) {
  npm install
}
$env:VITE_API_BASE_URL = "/api"
npm run build
Pop-Location

$Python = Find-HuokePython
if (-not $Python) {
  Write-Error "Python 3.11+ not found. Install Python 3.11 or 3.12 to prepare the desktop bundle."
}

Write-Host "Cleaning old bundle..."
if (Test-Path $BundleDir) {
  Remove-Item -Recurse -Force $BundleDir
}
New-Item -ItemType Directory -Force -Path $TargetBackend, $RuntimeDir | Out-Null

Write-Host "Copying backend..."
$exclude = @(".venv", "__pycache__", ".pytest_cache", "reports", "storage")
robocopy $BackendSrc $TargetBackend /E /NFL /NDL /NJH /NJS /nc /ns /np `
  /XD $exclude | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Backend copy failed (robocopy exit $LASTEXITCODE)" }

$FrontendDist = Join-Path $FrontendDir "dist"
if (Test-Path $FrontendDist) {
  Write-Host "Copying frontend dist..."
  $TargetFrontend = Join-Path $BundleDir "frontend-dist"
  robocopy $FrontendDist $TargetFrontend /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "Frontend dist copy failed" }
}

Write-Host "Creating virtualenv ($Python)..."
Invoke-HuokePython $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }

$PipPython = Join-Path $VenvDir "Scripts/python.exe"
& $PipPython -m pip install -U pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $PipPython -m pip install -r (Join-Path $TargetBackend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency install failed" }

Write-Host "Bundle ready: $BundleDir"
