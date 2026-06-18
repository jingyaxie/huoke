# Windows desktop: start bundled FastAPI backend (stdout-only logging for Rust parent)
$ErrorActionPreference = "Stop"

function Resolve-HuokeDataDir {
  if ($env:HUOKE_DATA_DIR) { return $env:HUOKE_DATA_DIR }
  $appData = [Environment]::GetFolderPath("ApplicationData")
  return Join-Path $appData "com.huoke.desktop"
}

function Write-Log {
  param([string]$Message)
  Write-Output ("[backend] [{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

function Invoke-PythonStep {
  param(
    [string]$Label,
    [string]$PythonExe,
    [string]$Code
  )
  Write-Log "preflight: $Label"
  $output = & $PythonExe -c $Code 2>&1
  if ($output) {
    foreach ($line in @($output)) {
      Write-Output "[backend] $line"
    }
  }
  if ($LASTEXITCODE -ne 0) {
    throw "preflight failed at '$Label' (exit $LASTEXITCODE)"
  }
}

function Resolve-HuokeBundleDir {
  if ($env:HUOKE_BUNDLE_DIR -and (Test-Path (Join-Path $env:HUOKE_BUNDLE_DIR "runtime"))) {
    return $env:HUOKE_BUNDLE_DIR
  }
  $candidates = @(
    (Join-Path $script:Root "desktop/bundle"),
    (Join-Path $script:Root "bundle")
  )
  foreach ($dir in $candidates) {
    if (Test-Path (Join-Path $dir "runtime")) { return $dir }
  }
  throw "bundle runtime not found under HUOKE_ROOT=$($script:Root)"
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

function Test-PortInUse {
  param([int]$Port)
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return $true }
  } catch {}
  try {
    $netstatMatches = netstat -ano | Select-String -Pattern ":[ ]*$Port[ ].*LISTENING"
    return [bool]$netstatMatches
  } catch {}
  return $false
}

function Set-PortablePythonEnv {
  param([string]$PythonExe)
  Set-PortablePythonHome -PythonExe $PythonExe
}

function Start-HuokeDesktopBackend {
  $DataDir = Resolve-HuokeDataDir
  $SourceBundleDir = Resolve-HuokeBundleDir
  $BundleDir = Sync-HuokeBundleCache -SourceBundleDir $SourceBundleDir -DataDir $DataDir -Root $script:Root
  $BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 18765 }
  $StorageDir = Join-Path $DataDir "storage"
  $EnvFile = Join-Path $DataDir ".env.desktop"
  $DbFile = Join-Path $StorageDir "huoke_desktop.db"

  New-Item -ItemType Directory -Force -Path $DataDir, $StorageDir, (Join-Path $StorageDir "douyin/profile") | Out-Null
  Write-Log "root=$($script:Root) sourceBundle=$SourceBundleDir bundle=$BundleDir"

  $ExampleEnv = Join-Path $script:Root ".env.desktop.example"
  if (-not (Test-Path $ExampleEnv)) {
    $ExampleEnv = Join-Path $script:Root "resources/.env.desktop.example"
  }
  if (-not (Test-Path $EnvFile)) {
    if (Test-Path $ExampleEnv) {
      Copy-Item $ExampleEnv $EnvFile
      Add-Content $EnvFile "`nANTIBOT_FINGERPRINT_PLATFORM=win"
      Write-Log "created desktop config: $EnvFile"
    } else {
      Write-Log "WARN: .env.desktop.example missing, using defaults"
    }
  }

  $PortablePython = Find-PortablePythonExe -BundleDir $BundleDir
  $VenvPython = Join-Path $BundleDir "runtime/.venv/Scripts/python.exe"
  $Python = $null
  $BackendDir = $null
  if ($PortablePython) {
    $BackendDir = Join-Path $BundleDir "backend"
    $Python = $PortablePython
  } elseif (Test-Path $VenvPython) {
    $BackendDir = Join-Path $BundleDir "backend"
    $Python = $VenvPython
  } else {
    . (Join-Path $script:ScriptDir "_python_win.ps1")
    $BackendDir = Join-Path $script:Root "backend"
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
    throw "Python runtime not found (bundle=$BundleDir)"
  }

  if ($PortablePython) {
    Set-PortablePythonEnv -PythonExe $Python
    Write-Log "Python: $Python (PYTHONHOME=$($env:PYTHONHOME))"
  } else {
    Write-Log "Python: $Python"
  }

  if (Test-PortInUse -Port $BackendPort) {
    throw "port $BackendPort is already in use"
  }

  Set-Location $BackendDir

  $env:DESKTOP_MODE = "true"
  $FrontendDist = Join-Path $BundleDir "frontend-dist"
  if (Test-Path $FrontendDist) {
    $env:FRONTEND_DIST_DIR = $FrontendDist
  } else {
    $env:FRONTEND_DIST_DIR = Join-Path $script:Root "frontend/dist"
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
      if ($line -and -not $line.StartsWith("#") -and $line -match '^([^=]+)=(.*)$') {
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
    Write-Log "Chrome not installed, using bundled Playwright Chromium"
    $env:ANTIBOT_BROWSER_CHANNEL = ""
    $env:ANTIBOT_PLAYWRIGHT_FALLBACK = "true"
  } else {
    Write-Log "Chrome: $Chrome"
  }

  Invoke-PythonStep -Label "python version" -PythonExe $Python -Code "import sys; print(sys.version)"
  Invoke-PythonStep -Label "import uvicorn" -PythonExe $Python -Code "import uvicorn; print('uvicorn ok')"
  Invoke-PythonStep -Label "import bootstrap" -PythonExe $Python -Code "from app.db.bootstrap import ensure_database_schema; print('bootstrap import ok')"
  Invoke-PythonStep -Label "import app.main" -PythonExe $Python -Code "from app.main import app; print('app.main ok')"
  Invoke-PythonStep -Label "ensure_database_schema" -PythonExe $Python -Code "from app.db.bootstrap import ensure_database_schema; ensure_database_schema(); print('database schema ready')"

  Write-Log "starting uvicorn on port $BackendPort"
  & $Python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort 2>&1 | ForEach-Object {
    Write-Output "[backend] $_"
  }
  if ($LASTEXITCODE -ne 0) {
    throw "uvicorn exited with code $LASTEXITCODE"
  }
}

$script:ScriptDir = $PSScriptRoot
$script:Root = if ($env:HUOKE_ROOT) { $env:HUOKE_ROOT } else { Split-Path -Parent $script:ScriptDir }
. (Join-Path $script:ScriptDir "desktop-bundle-cache.ps1")

try {
  Write-Log "desktop-run-backend starting"
  Start-HuokeDesktopBackend
} catch {
  Write-Log ("FATAL: {0}" -f $_.Exception.Message)
  if ($_.ScriptStackTrace) {
    Write-Log $_.ScriptStackTrace
  }
  exit 1
}
