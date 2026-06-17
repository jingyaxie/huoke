# Huoke Windows Sidecar - bundle python-runtime and install deps in-place
param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\dist-sidecar",
    [switch]$SkipPlaywright
)

$ErrorActionPreference = "Stop"
$BackendRoot = Join-Path $PSScriptRoot "..\..\backend"
$InstallRoot = Resolve-Path $InstallRoot -ErrorAction SilentlyContinue
if (-not $InstallRoot) {
    $InstallRoot = Join-Path (Split-Path $BackendRoot -Parent) "dist-sidecar"
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
}
$InstallRoot = (Resolve-Path $InstallRoot).Path
$resolvedBackend = $null
try {
    $resolvedBackend = (Resolve-Path $BackendRoot -ErrorAction Stop).Path
} catch {
    $resolvedBackend = $null
}
$BackendRoot = $resolvedBackend
if (-not $BackendRoot) {
    $fallbackBackend = Join-Path $InstallRoot "backend"
    if (Test-Path (Join-Path $fallbackBackend "app\main.py")) {
        $BackendRoot = $fallbackBackend
    } else {
        throw "[sidecar] backend source not found"
    }
}

Write-Host "[sidecar] install root: $InstallRoot" -ForegroundColor Cyan
$RuntimeDir = Join-Path $InstallRoot "python-runtime"
$Storage = Join-Path $InstallRoot "storage"
New-Item -ItemType Directory -Force -Path $Storage | Out-Null

function Get-BuildPythonPrefix {
    $prefix = (& python -c "import sys; print(sys.base_prefix)" 2>$null | Select-Object -First 1)
    if (-not $prefix) { throw "[sidecar] build python not found" }
    return $prefix.Trim()
}

function Ensure-RuntimePython([string]$Root) {
    $py = Join-Path $Root "python.exe"
    if (Test-Path $py) { return $py }

    $basePrefix = Get-BuildPythonPrefix
    if (Test-Path $Root) { Remove-Item -Recurse -Force $Root }
    Write-Host "[sidecar] copying python runtime from $basePrefix" -ForegroundColor Cyan
    Copy-Item -Recurse $basePrefix $Root
    if (-not (Test-Path $py)) {
        throw "[sidecar] python.exe missing after runtime copy: $py"
    }
    return $py
}

# Bundle MSVC runtime DLLs next to python.exe so native wheels (greenlet, etc.)
# load on clean machines without Visual C++ Redistributable installed.
function Copy-BundledVCRuntime([string]$RuntimeRoot) {
    $sys32 = Join-Path $env:WINDIR "System32"
    $dlls = @(
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "concrt140.dll"
    )
    foreach ($d in $dlls) {
        $src = Join-Path $sys32 $d
        $dst = Join-Path $RuntimeRoot $d
        if (Test-Path $src) {
            Copy-Item -Force $src $dst
            Write-Host "[sidecar] bundled VC runtime: $d" -ForegroundColor DarkCyan
        } elseif ($d -in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
            Write-Host "[sidecar] WARNING: required VC runtime missing on build host: $d" -ForegroundColor Yellow
        }
    }
}

$Py = Ensure-RuntimePython $RuntimeDir

Write-Host "[sidecar] bootstrapping pip in python-runtime" -ForegroundColor Cyan
& $Py -m ensurepip --upgrade 2>$null | Out-Null
& $Py -m pip install -U pip wheel | Out-Null

Write-Host "[sidecar] installing backend requirements into python-runtime" -ForegroundColor Cyan
& $Py -m pip install -r (Join-Path $BackendRoot "requirements.txt") | Out-Null

# Reinstall greenlet against this exact interpreter (avoid stale/copied wheels).
Write-Host "[sidecar] reinstalling greenlet for bundled runtime" -ForegroundColor Cyan
& $Py -m pip install --force-reinstall --no-cache-dir "greenlet>=3.0" | Out-Null

# Bundle VC runtime AFTER deps so the DLLs sit beside python.exe for the work-dir copy.
Write-Host "[sidecar] bundling MSVC runtime DLLs into python-runtime" -ForegroundColor Cyan
Copy-BundledVCRuntime $RuntimeDir

if (-not $SkipPlaywright) {
    Write-Host "[sidecar] installing Playwright Chromium" -ForegroundColor Cyan
    & $Py -m playwright install chromium
}

# Copy backend code and scripts
$TargetBackend = Join-Path $InstallRoot "backend"
$backendSourceResolved = (Resolve-Path $BackendRoot -ErrorAction Stop).Path
$backendTargetResolved = $null
try {
    $backendTargetResolved = (Resolve-Path $TargetBackend -ErrorAction Stop).Path
} catch {
    $backendTargetResolved = $null
}
if ($backendTargetResolved -and ($backendSourceResolved.ToLower() -eq $backendTargetResolved.ToLower())) {
    Write-Host "[sidecar] backend source equals target; skip copy" -ForegroundColor Yellow
} else {
    if (Test-Path $TargetBackend) { Remove-Item -Recurse -Force $TargetBackend }
    Copy-Item -Recurse $BackendRoot $TargetBackend
}

$TargetScripts = Join-Path $InstallRoot "scripts\windows"
$scriptRootResolved = (Resolve-Path $PSScriptRoot).Path
$targetScriptsResolved = $null
try {
    $targetScriptsResolved = (Resolve-Path $TargetScripts -ErrorAction Stop).Path
} catch {
    $targetScriptsResolved = $null
}
if ($targetScriptsResolved -and ($scriptRootResolved.ToLower() -eq $targetScriptsResolved.ToLower())) {
    Write-Host "[sidecar] scripts already in place; skip copy" -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Force -Path $TargetScripts | Out-Null
    Copy-Item -Force "$PSScriptRoot\*.ps1" $TargetScripts
}

$EnvExample = Join-Path (Split-Path $BackendRoot -Parent) ".env.sidecar.example"
$EnvFile = Join-Path $InstallRoot ".env"
if (Test-Path $EnvFile) { Remove-Item -Force $EnvFile }
if (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
}

@"
STORAGE_ROOT=$Storage
DATABASE_URL=sqlite+pysqlite:///$($Storage -replace '\\','/')/huoke_sidecar.db
DOUYIN_HEADLESS=false
XHS_HEADLESS=false
COMPAT_ENABLED=true
"@ | Add-Content -Path $EnvFile -Encoding ASCII

# Remove legacy venv to avoid stale launchers pointing at CI paths.
$LegacyVenv = Join-Path $InstallRoot "venv"
if (Test-Path $LegacyVenv) {
    Remove-Item -Recurse -Force $LegacyVenv
}

$bundleVersion = "0.0.0"
$pkgPath = Join-Path $PSScriptRoot "..\..\package.json"
if (Test-Path $pkgPath) {
    try {
        $bundleVersion = (Get-Content $pkgPath -Raw | ConvertFrom-Json).version
    } catch {
        $bundleVersion = "0.0.0"
    }
}
$marker = @{
    sidecar_bundle_version = $bundleVersion
    built_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json -Compress
Set-Content -Path (Join-Path $InstallRoot "bundle-version.json") -Value $marker -Encoding ASCII

Write-Host "[sidecar] done. run: scripts\windows\run-engine.ps1" -ForegroundColor Green
