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

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

Write-Host "==> Preparing desktop bundle"
Write-Host "Building frontend (same-origin /api)..."
Push-Location $FrontendDir
try {
  if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") {
      npm ci
    } else {
      npm install
    }
    if ($LASTEXITCODE -ne 0) { throw "frontend npm install failed" }
  }
  $env:VITE_API_BASE_URL = "/api"
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
} finally {
  Pop-Location
}

$Python = Find-HuokePython
if (-not $Python) {
  Write-HuokePythonDiagnostics
  throw "Python 3.11+ not found. Install Python 3.11 or 3.12 to prepare the desktop bundle."
}
$PythonExe = Set-HuokePythonEnv $Python
Write-Host "Python: $PythonExe"

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
if (-not (Test-Path $FrontendDist)) {
  throw "Frontend dist not found: $FrontendDist"
}
Write-Host "Copying frontend dist..."
$TargetFrontend = Join-Path $BundleDir "frontend-dist"
robocopy $FrontendDist $TargetFrontend /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Frontend dist copy failed" }

Write-Host "Creating virtualenv..."
& $PythonExe -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed with exit code $LASTEXITCODE" }

$PipPython = Join-Path $VenvDir "Scripts/python.exe"
if (-not (Test-Path $PipPython)) {
  throw "Bundled venv python not found: $PipPython"
}

Invoke-Checked "pip upgrade" {
  & $PipPython -m pip install --disable-pip-version-check -U pip setuptools wheel
}
Invoke-Checked "pip install requirements" {
  & $PipPython -m pip install --disable-pip-version-check -r (Join-Path $TargetBackend "requirements.txt")
}

Write-Host "Bundle ready: $BundleDir"
