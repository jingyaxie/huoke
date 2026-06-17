# Build Huoke Windows desktop installer (Tauri NSIS + bundled Python backend)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $Root "desktop"

function Find-ChromePath {
  $paths = @(
    (Join-Path ${env:ProgramFiles} "Google/Chrome/Application/chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google/Chrome/Application/chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google/Chrome/Application/chrome.exe")
  )
  foreach ($p in $paths) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

$Chrome = Find-ChromePath
if (-not $Chrome) {
  Write-Warning "Google Chrome not found. Build can continue, but browser automation requires Chrome on target machines."
} else {
  Write-Host "Chrome: $Chrome"
}

$Python = Find-HuokePython
if (-not $Python) {
  Write-Error "Python 3.11+ is required for bundling. Install from https://www.python.org/downloads/"
}
Write-Host "Python: $Python"

if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
  Write-Error "Rust toolchain is required. Install from https://rustup.rs/ and ensure MSVC build tools are available."
}

Push-Location $DesktopDir
if (-not (Test-Path "node_modules")) {
  npm install
}

Write-Host ""
Write-Host "Building Windows NSIS installer..."
Write-Host "First build may take 10-20 minutes (deps + Rust compile + Python packages)..."
Write-Host ""

npm run build

Pop-Location

$BundleDir = Join-Path $DesktopDir "src-tauri/target/release/bundle/nsis"
Write-Host ""
Write-Host "Build finished. Output directory:"
Write-Host "  $BundleDir"
if (Test-Path $BundleDir) {
  Get-ChildItem $BundleDir -Filter "*.exe" | ForEach-Object {
    Write-Host "  Installer: $($_.FullName)"
  }
}
