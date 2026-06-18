# Windows 桌面版：启动内置 FastAPI 后端
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$ScriptDir = $PSScriptRoot
$Root = if ($env:HUOKE_ROOT) { $env:HUOKE_ROOT } else { Split-Path -Parent $ScriptDir }

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
  return $Root
}

function Resolve-HuokeDataDir {
  if ($env:HUOKE_DATA_DIR) { return $env:HUOKE_DATA_DIR }
  $appData = [Environment]::GetFolderPath("ApplicationData")
  return Join-Path $appData "com.huoke.desktop"
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
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return [bool]$conn
}

$BundleDir = Resolve-HuokeBundleDir
$DataDir = Resolve-HuokeDataDir
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 18765 }
$StorageDir = Join-Path $DataDir "storage"
$EnvFile = Join-Path $DataDir ".env.desktop"
$LogFile = Join-Path $DataDir "logs/desktop-backend.log"
$DbFile = Join-Path $StorageDir "huoke_desktop.db"

New-Item -ItemType Directory -Force -Path $DataDir, $StorageDir, (Join-Path $StorageDir "douyin/profile"), (Join-Path $DataDir "logs") | Out-Null

function Write-Log([string]$Message) {
  $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
  Add-Content -Path $LogFile -Value $line
  Write-Output $line
}

Write-Log "desktop-run-backend root=$Root bundle=$BundleDir"

$ExampleEnv = Join-Path $Root ".env.desktop.example"
if (-not (Test-Path $ExampleEnv)) {
  $ExampleEnv = Join-Path $Root "resources/.env.desktop.example"
}
if (-not (Test-Path $EnvFile)) {
  if (Test-Path $ExampleEnv) {
    Copy-Item $ExampleEnv $EnvFile
    Add-Content $EnvFile "`nANTIBOT_FINGERPRINT_PLATFORM=win"
    Write-Host "已创建桌面配置: $EnvFile"
    Write-Host "请按需编辑 API Key 后重启应用。"
  } else {
    Write-Warning "未找到 .env.desktop.example，将使用默认环境变量。"
  }
}

$PortablePython = ""
foreach ($candidate in @(
    (Join-Path $BundleDir "runtime/python/python.exe"),
    (Join-Path $BundleDir "runtime/python/bin/python.exe"),
    (Join-Path $BundleDir "runtime/python/bin/python3.exe"),
    (Join-Path $BundleDir "runtime/python/bin/python3.12.exe")
  )) {
  if (Test-Path $candidate) {
    $PortablePython = $candidate
    break
  }
}

$VenvPython = Join-Path $BundleDir "runtime/.venv/Scripts/python.exe"
if ($PortablePython) {
  $BackendDir = Join-Path $BundleDir "backend"
  $Python = $PortablePython
} elseif (Test-Path $VenvPython) {
  $BackendDir = Join-Path $BundleDir "backend"
  $Python = $VenvPython
} else {
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
  Write-Error "未找到可用的 Python 3.11+ 运行时"
}

if (Test-PortInUse $BackendPort) {
  Write-Error "桌面版端口 $BackendPort 已被占用，无法启动内置后端。请关闭占用该端口的进程后重开应用。"
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

Write-Host "初始化数据库..."
& $Python -c "from app.db.bootstrap import ensure_database_schema; ensure_database_schema(); print('数据库 schema 已就绪')"
if ($LASTEXITCODE -ne 0) { throw "数据库初始化失败" }

Write-Host "启动后端: $Python (port $BackendPort, SQLite)"
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort
