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
    [string]$Code,
    [switch]$AllowFailure
  )
  Write-Log "preflight: $Label"
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $output = & $PythonExe -c $Code 2>&1
    if ($output) {
      foreach ($line in @($output)) {
        Write-Output "[backend] $line"
      }
    }
    if ($LASTEXITCODE -ne 0) {
      if ($AllowFailure) {
        return $false
      }
      throw "preflight failed at '$Label' (exit $LASTEXITCODE)"
    }
    return $true
  } finally {
    $ErrorActionPreference = $prevEap
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

function Invoke-HuokeNativeDiagnostics {
  param(
    [string]$PythonExe,
    [string]$BundleDir
  )
  $diagScript = Join-Path $script:ScriptDir "diagnose_portable_python.py"
  if (-not (Test-Path $diagScript)) {
    Write-Log "WARN: diagnose_portable_python.py missing"
    return
  }
  $env:HUOKE_BUNDLE_DIR = $BundleDir
  $env:HUOKE_PYTHON_EXE = $PythonExe
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $output = & $PythonExe $diagScript 2>&1
    if ($output) {
      foreach ($line in @($output)) {
        Write-Output "[backend] $line"
      }
    }
  } finally {
    $ErrorActionPreference = $prevEap
  }
}

function Repair-HuokeNativeRuntime {
  param(
    [string]$PythonExe,
    [string]$BundleDir
  )
  $repairWheels = Join-Path $BundleDir "runtime/repair-wheels"
  if (-not (Test-Path $repairWheels)) {
    Write-Log "WARN: repair-wheels directory missing: $repairWheels"
    return $false
  }
  Write-Log "attempting offline native repair from $repairWheels"
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $output = & $PythonExe -m pip install --disable-pip-version-check `
      --no-index `
      --find-links $repairWheels `
      --force-reinstall `
      greenlet playwright cryptography pydantic-core 2>&1
    if ($output) {
      foreach ($line in @($output)) {
        Write-Output "[backend] $line"
      }
    }
    return ($LASTEXITCODE -eq 0)
  } finally {
    $ErrorActionPreference = $prevEap
  }
}

function Invoke-HuokePreflight {
  param(
    [string]$PythonExe,
    [string]$BundleDir,
    [switch]$AllowRepair
  )

  $steps = @(
    @{ Label = "python version"; Code = "import sys; print(sys.version)" },
    @{ Label = "import uvicorn"; Code = "import uvicorn; print('uvicorn ok')" },
    @{ Label = "import greenlet"; Code = "import greenlet; from greenlet._greenlet import _C_API; print('greenlet ok')" },
    @{ Label = "import cryptography"; Code = "import cryptography; print('cryptography ok')" },
    @{ Label = "import pydantic_core"; Code = "import pydantic_core; print('pydantic_core ok')" },
    @{ Label = "import bootstrap"; Code = "from app.db.bootstrap import ensure_database_schema; print('bootstrap import ok')" },
    @{ Label = "import playwright"; Code = "from playwright.async_api import async_playwright; print('playwright ok')" },
    @{ Label = "import app.main"; Code = "from app.main import app; print('app.main ok')" },
    @{ Label = "ensure_database_schema"; Code = "from app.db.bootstrap import ensure_database_schema; ensure_database_schema(); print('database schema ready')" }
  )

  foreach ($step in $steps) {
    $ok = Invoke-PythonStep -Label $step.Label -PythonExe $PythonExe -Code $step.Code -AllowFailure
    if ($ok) { continue }

    if ($step.Label -eq "import greenlet" -and $AllowRepair) {
      Invoke-HuokeNativeDiagnostics -PythonExe $PythonExe -BundleDir $BundleDir
      if (Repair-HuokeNativeRuntime -PythonExe $PythonExe -BundleDir $BundleDir) {
        Write-Log "native repair completed; retrying preflight"
        return $false
      }
    }

    Invoke-HuokeNativeDiagnostics -PythonExe $PythonExe -BundleDir $BundleDir
    throw "preflight failed at '$($step.Label)'"
  }
  return $true
}

function Start-HuokeDesktopBackend {
  $DataDir = Resolve-HuokeDataDir
  $SourceBundleDir = Resolve-HuokeBundleDir
  $CachedBundleDir = Sync-HuokeBundleCache -SourceBundleDir $SourceBundleDir -DataDir $DataDir -Root $script:Root
  $BundleDir = Sync-HuokeRuntimeWorkdir -SourceBundleDir $CachedBundleDir -DataDir $DataDir
  $BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 18765 }
  $StorageDir = Join-Path $DataDir "storage"
  $EnvFile = Join-Path $DataDir ".env.desktop"
  $DbFile = Join-Path $StorageDir "huoke_desktop.db"

  New-Item -ItemType Directory -Force -Path $DataDir, $StorageDir, (Join-Path $StorageDir "douyin/profile") | Out-Null
  Write-Log "root=$($script:Root) sourceBundle=$SourceBundleDir cachedBundle=$CachedBundleDir workBundle=$BundleDir"

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
    Write-Log "Python: $Python (portable root=$(Get-PortablePythonRoot -PythonExe $Python))"
  } else {
    Write-Log "Python: $Python"
  }

  if (Test-PortInUse -Port $BackendPort) {
    throw "port $BackendPort is already in use"
  }

  Set-Location $BackendDir

  $env:DESKTOP_MODE = "true"
  $env:HUOKE_BUNDLE_DIR = $BundleDir
  $env:HUOKE_PYTHON_EXE = $Python
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

  $preflightOk = Invoke-HuokePreflight -PythonExe $Python -BundleDir $BundleDir -AllowRepair
  if (-not $preflightOk) {
    $BundleDir = Sync-HuokeRuntimeWorkdir -SourceBundleDir $CachedBundleDir -DataDir $DataDir -Force
    $PortablePython = Find-PortablePythonExe -BundleDir $BundleDir
    if ($PortablePython) {
      $Python = $PortablePython
      Set-PortablePythonEnv -PythonExe $Python
      $env:HUOKE_BUNDLE_DIR = $BundleDir
      $env:HUOKE_PYTHON_EXE = $Python
      $PwBrowsers = Join-Path $BundleDir "runtime/playwright-browsers"
      if (Test-Path $PwBrowsers) {
        $env:PLAYWRIGHT_BROWSERS_PATH = $PwBrowsers
      }
    }
    $null = Invoke-HuokePreflight -PythonExe $Python -BundleDir $BundleDir
  }

  Write-Log "starting uvicorn on port $BackendPort"
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort
    if ($LASTEXITCODE -ne 0) {
      throw "uvicorn exited with code $LASTEXITCODE"
    }
  } finally {
    $ErrorActionPreference = $prevEap
  }
}

$script:ScriptDir = $PSScriptRoot
$script:Root = if ($env:HUOKE_ROOT) { $env:HUOKE_ROOT } else { Split-Path -Parent $script:ScriptDir }
. (Join-Path $script:ScriptDir "desktop-bundle-cache.ps1")
. (Join-Path $script:ScriptDir "desktop-runtime-workdir.ps1")

try {
  Write-Log "desktop-run-backend starting"
  Start-HuokeDesktopBackend
} catch {
  $msg = $_.Exception.Message
  if ($msg -match 'greenlet|native|DLL|vcruntime') {
    $msg = "$msg`n`nSuggestions: 1) Add install dir to antivirus allowlist 2) Fully uninstall and reinstall 3) If vcruntime is missing, install VC++ 2015-2022 x64: https://aka.ms/vs/17/release/vc_redist.x64.exe"
  }
  Write-Log ("FATAL: {0}" -f $msg)
  if ($_.ScriptStackTrace) {
    Write-Log $_.ScriptStackTrace
  }
  exit 1
}
