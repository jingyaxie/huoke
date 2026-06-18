# Prepare desktop bundle before Tauri build (frontend dist + Python backend)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$BundleDir = Join-Path $Root "desktop/bundle"
$BackendSrc = Join-Path $Root "backend"
$RuntimeDir = Join-Path $BundleDir "runtime"
$TargetBackend = Join-Path $BundleDir "backend"

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

$PortableDir = Join-Path $RuntimeDir "python"
$RequirementsFile = Join-Path $TargetBackend "requirements.txt"
. "$PSScriptRoot/install_portable_python_win.ps1"
Install-HuokePortablePython -TargetDir $PortableDir -RequirementsFile $RequirementsFile | Out-Null
$PortablePython = Find-PortablePythonExe -Root $PortableDir
if (-not $PortablePython) {
  throw "Portable Python binary missing under $PortableDir"
}

Write-Host "Verifying portable Python can load backend (production-like env)..."
$env:PYTHONPATH = $TargetBackend
$null = Set-PortablePythonEnvForExe -PythonExe $PortablePython
& $PortablePython -c "import greenlet; from greenlet._greenlet import _C_API; from app.main import app; print('backend import ok')"
if ($LASTEXITCODE -ne 0) { throw "backend import smoke test failed" }
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue

@{
  kind = "huoke-desktop-bundle"
  python = "runtime/python"
  playwright_browsers = "runtime/playwright-browsers"
  backend = "backend"
  frontend = "frontend-dist"
  notes = "Self-contained desktop runtime with bundled Playwright Chromium; system Chrome is optional."
} | ConvertTo-Json | Set-Content -Path (Join-Path $BundleDir "BUNDLE_MANIFEST.json") -Encoding UTF8

Write-Host "Bundle ready: $BundleDir"
