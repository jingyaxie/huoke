# Windows 桌面版：启动内置 FastAPI 后端
$ErrorActionPreference = "Stop"

function Resolve-HuokeDataDir {
  if ($env:HUOKE_DATA_DIR) { return $env:HUOKE_DATA_DIR }
  $appData = [Environment]::GetFolderPath("ApplicationData")
  return Join-Path $appData "com.huoke.desktop"
}

$DataDir = Resolve-HuokeDataDir
$LogFile = Join-Path $DataDir "logs/desktop-backend.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null

function Write-Log([string]$Message) {
  $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
  Add-Content -Path $LogFile -Value $line -Encoding UTF8
  Write-Output $line
}

trap {
  $err = $_.Exception.Message
  if ($_.ScriptStackTrace) { $err += "`n$($_.ScriptStackTrace)" }
  Write-Log "FATAL: $err"
  Write-Host "LOG_FILE=$LogFile" -ForegroundColor Red
  Write-Error $err
}

Write-Log "desktop-run-backend starting"
Write-Host "LOG_FILE=$LogFile"

$ScriptDir = $PSScriptRoot
$Root = if ($env:HUOKE_ROOT) { $env:HUOKE_ROOT } else { Split-Path -Parent $ScriptDir }

. (Join-Path $ScriptDir "desktop-bundle-cache.ps1")

function Resolve-HuokeBundleDir {
  if ($env:HUOKE_BUNDLE_DIR -and (Test-Path (Join-Path $env:HUOKE_BUNDLE_DIR "runtime"))) {
    return $env:HUOKE_BUNDLE_DIR
  }
  $candidates = @(
    (Join-Path $Root "desktop/bundle"),
    (Join-Path $Root "bundle")
  )
  foreach ($dir in $candidates) {
    if (Test-Path (Join-Path $dir "runtime")) { return $dir }
  }
  throw "未找到桌面 bundle（缺少 runtime 目录）。HUOKE_ROOT=$Root"
}

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

function Test-PortInUse([int]$Port) {
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return $true }
  } catch {}
  try {
    $matches = netstat -ano | Select-String -Pattern ":[ ]*$Port[ ].*LISTENING"
    return [bool]$matches
  } catch {}
  return $false
}

function Set-PortablePythonEnv {
  param([Parameter(Mandatory = $true)][string]$PythonExe)
  $pythonHome = Split-Path $PythonExe -Parent
  if ((Split-Path $pythonHome -Leaf) -eq "bin") {
    $pythonHome = Split-Path $pythonHome -Parent
  }
  $env:PYTHONHOME = $pythonHome
  $env:PYTHONUTF8 = "1"
}

$SourceBundleDir = Resolve-HuokeBundleDir
$BundleDir = Sync-HuokeBundleCache -SourceBundleDir $SourceBundleDir -DataDir $DataDir -Root $Root
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 18765 }
$StorageDir = Join-Path $DataDir "storage"
$EnvFile = Join-Path $DataDir ".env.desktop"
$DbFile = Join-Path $StorageDir "huoke_desktop.db"

New-Item -ItemType Directory -Force -Path $DataDir, $StorageDir, (Join-Path $StorageDir "douyin/profile") | Out-Null
Write-Log "desktop-run-backend root=$Root sourceBundle=$SourceBundleDir bundle=$BundleDir"

$ExampleEnv = Join-Path $Root ".env.desktop.example"
if (-not (Test-Path $ExampleEnv)) {
  $ExampleEnv = Join-Path $Root "resources/.env.desktop.example"
}
if (-not (Test-Path $EnvFile)) {
  if (Test-Path $ExampleEnv) {
    Copy-Item $ExampleEnv $EnvFile
    Add-Content $EnvFile "`nANTIBOT_FINGERPRINT_PLATFORM=win"
    Write-Log "已创建桌面配置: $EnvFile"
    Write-Host "已创建桌面配置: $EnvFile"
  } else {
    Write-Log "WARN: 未找到 .env.desktop.example，将使用默认环境变量。"
  }
}

$PortablePython = Find-PortablePythonExe -BundleDir $BundleDir
$VenvPython = Join-Path $BundleDir "runtime/.venv/Scripts/python.exe"
if ($PortablePython) {
  $BackendDir = Join-Path $BundleDir "backend"
  $Python = $PortablePython
} elseif (Test-Path $VenvPython) {
  $BackendDir = Join-Path $BundleDir "backend"
  $Python = $VenvPython
} else {
  . (Join-Path $ScriptDir "_python_win.ps1")
  $BackendDir = Join-Path $Root "backend"
  $DevVenv = Join-Path $BackendDir ".venv/Scripts/python.exe"
  if (Test-Path $DevVenv) {
    $Python = $DevVenv
  } else {
    $candidate = Find-HuokePython
    if ($candidate) {
      $Python = Resolve-HuokePythonExe $candidate
    }
  }
}

if (-not $Python -or -not (Test-Path $Python)) {
  throw "未找到可用的 Python 3.11+ 运行时 (bundle=$BundleDir)"
}

if ($PortablePython) {
  Set-PortablePythonEnv -PythonExe $Python
  Write-Log "Python: $Python (PYTHONHOME=$($env:PYTHONHOME))"
} else {
  Write-Log "Python: $Python"
}

if (Test-PortInUse $BackendPort) {
  throw "桌面版端口 $BackendPort 已被占用，无法启动内置后端。请关闭占用该端口的进程后重开应用。"
}

Set-Location $BackendDir

$env:DESKTOP_MODE = "true"
$FrontendDist = Join-Path $BundleDir "frontend-dist"
if (Test-Path $FrontendDist) {
  $env:FRONTEND_DIST_DIR = $FrontendDist
} else {
  $env:FRONTEND_DIST_DIR = Join-Path $Root "frontend/dist"
}
$env:STORAGE_ROOT = $StorageDir
$env:FRONTEND_ORIGIN = "http://127.0.0.1:$BackendPort"
$env:DATABASE_URL = "sqlite+pysqlite:///$($DbFile -replace '\\', '/')"
$env:DOUYIN_PROFILE_DIR = Join-Path $StorageDir "douyin/profile"
$env:PYTHONPATH = $BackendDir
$env:ANTIBOT_FINGERPRINT_PLATFORM = "win"

$PwBrowsers = Join-Path $BundleDir "runtime/playwright-browsers"
if (Test-Path $PwBrowsers) {
  $env:PLAYWRIGHT_BROWSERS_PATH = $PwBrowsers
  Write-Log "Playwright browsers: $PwBrowsers"
}

if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line -match "^([^=]+)=(.*)$") {
      $name = $matches[1].Trim()
      $value = $matches[2].Trim().Trim('"')
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

$env:DESKTOP_MODE = "true"
$env:FRONTEND_ORIGIN = "http://127.0.0.1:$BackendPort"
$env:ANTIBOT_FINGERPRINT_PLATFORM = "win"

$Chrome = Find-ChromePath
if (-not $Chrome) {
  Write-Log "未安装 Google Chrome，将使用内置 Playwright Chromium 执行浏览器自动化"
  $env:ANTIBOT_BROWSER_CHANNEL = ""
  $env:ANTIBOT_PLAYWRIGHT_FALLBACK = "true"
} else {
  Write-Log "Chrome: $Chrome"
}

Write-Log "初始化数据库..."
& $Python -c "from app.db.bootstrap import ensure_database_schema; ensure_database_schema(); print('数据库 schema 已就绪')"
if ($LASTEXITCODE -ne 0) { throw "数据库初始化失败" }

Write-Log "启动后端: $Python (port $BackendPort, SQLite)"
Write-Host "启动后端: $Python (port $BackendPort, SQLite)"
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort
