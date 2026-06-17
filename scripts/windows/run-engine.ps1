# Start Huoke Sidecar FastAPI (127.0.0.1:18000)
param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\dist-sidecar",
    [int]$Port = 18000,
    [switch]$HeadedLogin
)

$ErrorActionPreference = "Stop"

function Test-IsReadOnlyPackagedRoot([string]$Root) {
    if (-not $Root) { return $false }
    $lower = $Root.ToLower()
    if ($lower -match '\\program files(\\|\s*\(x86\)\\|)') { return $true }
    if ($lower -match '\\resources\\huoke-sidecar') { return $true }
    return $false
}

function Get-WindowsWorkRoot() {
    return Join-Path $env:APPDATA "yingxiaoyi-pc-acquisition\huoke-sidecar-work"
}

function Test-PythonUsable([string]$pythonExe, [string]$runtimeRoot) {
    if (-not (Test-Path $pythonExe)) { return $false }
    $prevPath = $env:PATH
    $prevHome = $env:PYTHONHOME
    $prevPyPath = $env:PYTHONPATH
    try {
        $env:PATH = "$runtimeRoot;$runtimeRoot\DLLs;$runtimeRoot\Scripts;$env:PATH"
        Remove-Item env:PYTHONHOME -ErrorAction SilentlyContinue
        Remove-Item env:PYTHONPATH -ErrorAction SilentlyContinue
        $out = & $pythonExe -c "import greenlet; import uvicorn" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[sidecar] python import check failed: $out" -ForegroundColor Red
            return $false
        }
        return $true
    } catch {
        Write-Host "[sidecar] python import check exception: $_" -ForegroundColor Red
        return $false
    } finally {
        $env:PATH = $prevPath
        if ($prevHome) { $env:PYTHONHOME = $prevHome } else { Remove-Item env:PYTHONHOME -ErrorAction SilentlyContinue }
        if ($prevPyPath) { $env:PYTHONPATH = $prevPyPath } else { Remove-Item env:PYTHONPATH -ErrorAction SilentlyContinue }
    }
}

function Resolve-RuntimePython([string]$Root) {
    $runtime = Join-Path $Root "python-runtime"
    $py = Join-Path $runtime "python.exe"
    $backend = Join-Path $Root "backend"
    if (-not (Test-Path (Join-Path $backend "app\main.py"))) { return $null }
    if (-not (Test-PythonUsable $py $runtime)) { return $null }
    return @{
        Root = $Root
        Runtime = $runtime
        Python = $py
        Backend = $backend
    }
}

function Repair-WorkFromBundled([string]$WorkRoot) {
    $bundled = $env:HUOKE_SIDECAR_BUNDLED
    if (-not $bundled -or -not (Test-Path $bundled)) {
        Write-Host "[sidecar] bundled path missing (HUOKE_SIDECAR_BUNDLED)" -ForegroundColor Yellow
        return $false
    }
    $syncPs1 = Join-Path $bundled "scripts\windows\sync-sidecar-work.ps1"
    if (-not (Test-Path $syncPs1)) {
        Write-Host "[sidecar] sync-sidecar-work.ps1 missing in bundle" -ForegroundColor Yellow
        return $false
    }
    Write-Host "[sidecar] repairing work dir from bundled ..." -ForegroundColor Yellow
    & powershell.exe -ExecutionPolicy Bypass -File $syncPs1 -BundledRoot $bundled -WorkRoot $WorkRoot
    return $LASTEXITCODE -eq 0
}

# Packaged installs must never mutate Program Files; Electron syncs bundle to AppData work dir.
if (Test-IsReadOnlyPackagedRoot $InstallRoot) {
    $InstallRoot = Get-WindowsWorkRoot
}

if (-not (Test-Path $InstallRoot)) {
    if (Test-IsReadOnlyPackagedRoot (Join-Path $PSScriptRoot "..\..")) {
        if (-not (Repair-WorkFromBundled $InstallRoot)) {
            throw "[sidecar] work dir missing; restart app to sync bundled sidecar to userData"
        }
    } else {
        & "$PSScriptRoot\install-sidecar.ps1" -InstallRoot $InstallRoot
    }
}

$engine = Resolve-RuntimePython $InstallRoot
if (-not $engine) {
    $isWork = $InstallRoot.ToLower() -eq (Get-WindowsWorkRoot).ToLower()
    if ($isWork) {
        if (Repair-WorkFromBundled $InstallRoot) {
            $engine = Resolve-RuntimePython $InstallRoot
        }
        if (-not $engine) {
            throw "[sidecar] work runtime broken; delete $InstallRoot and restart app"
        }
    } else {
        Write-Host "[sidecar] runtime missing; installing (dev/CI only) ..." -ForegroundColor Yellow
        & "$PSScriptRoot\install-sidecar.ps1" -InstallRoot $InstallRoot
        $engine = Resolve-RuntimePython $InstallRoot
    }
}

if (-not $engine) {
    throw "[sidecar] no usable python runtime"
}

$InstallRoot = $engine.Root
$RuntimeRoot = $engine.Runtime
$EnginePython = $engine.Python
$Backend = $engine.Backend
$EnvFile = Join-Path $InstallRoot ".env"
$SidecarConfigDir = Join-Path $env:APPDATA "yingxiaoyi-pc-acquisition\huoke-sidecar"
$EnvSidecar = Join-Path $SidecarConfigDir ".env.sidecar"
$StorageRoot = Join-Path $env:APPDATA "yingxiaoyi-pc-acquisition\huoke-sidecar"

New-Item -ItemType Directory -Force -Path $StorageRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $StorageRoot "douyin\profile") | Out-Null

$env:PATH = "$RuntimeRoot;$RuntimeRoot\DLLs;$RuntimeRoot\Scripts;$env:PATH"
Remove-Item env:PYTHONHOME -ErrorAction SilentlyContinue
$env:PYTHONPATH = $Backend

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"')
            Set-Item -Path "env:$name" -Value $value
        }
    }
}
$env:HUOKE_ENV_SIDECAR_PATH = $EnvSidecar
if (Test-Path $EnvSidecar) {
    Get-Content $EnvSidecar | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"')
            Set-Item -Path "env:$name" -Value $value
        }
    }
}
if ($HeadedLogin) {
    $env:DOUYIN_HEADLESS = "false"
    $env:XHS_HEADLESS = "false"
}

$env:STORAGE_ROOT = $StorageRoot
$sqlitePath = (Join-Path $StorageRoot "huoke_sidecar.db") -replace '\\','/'
$env:DATABASE_URL = "sqlite+pysqlite:///$sqlitePath"
$env:DOUYIN_PROFILE_DIR = Join-Path $StorageRoot "douyin\profile"

$safeTmp = Join-Path $env:LOCALAPPDATA "Temp\yingxiaoyi-pc"
New-Item -ItemType Directory -Force -Path $safeTmp | Out-Null
$env:TEMP = $safeTmp
$env:TMP = $safeTmp

Write-Host "[sidecar] uvicorn app.main:app on 127.0.0.1:$Port ($EnginePython)" -ForegroundColor Cyan
Push-Location $Backend
try {
    & $EnginePython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
