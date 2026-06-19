# CI: silently install NSIS package and verify backend startup from real install layout.
param(
  [Parameter(Mandatory = $true)][string]$InstallerPath,
  [string]$InstallRoot = "",
  [int]$BackendPort = 18768
)

$ErrorActionPreference = "Stop"

if (-not $InstallRoot) {
  $InstallRoot = Join-Path $env:TEMP "huoke-nsis-smoke-$([guid]::NewGuid().ToString('N'))"
}

function Wait-BackendHealth {
  param([int]$Port, [int]$TimeoutSec = 180)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 -UseBasicParsing
      if ($r.StatusCode -eq 200) { return }
    } catch {}
    Start-Sleep -Seconds 1
  }
  throw "health check timed out for port $Port"
}

function Show-SmokeFailureLogs {
  param([string]$StdoutFile, [string]$StderrFile)
  Write-Host "--- backend stdout ---"
  if (Test-Path $StdoutFile) {
    Get-Content $StdoutFile -Tail 120 | ForEach-Object { Write-Host $_ }
  }
  Write-Host "--- backend stderr ---"
  if (Test-Path $StderrFile) {
    Get-Content $StderrFile -Tail 120 | ForEach-Object { Write-Host $_ }
  }
}

if (-not (Test-Path $InstallerPath)) {
  throw "Installer not found: $InstallerPath"
}

if (Test-Path $InstallRoot) {
  Remove-Item -Recurse -Force $InstallRoot
}
New-Item -ItemType Directory -Force -Path (Split-Path $InstallRoot -Parent) | Out-Null

Write-Host "Silent installing: $InstallerPath -> $InstallRoot"
$installProc = Start-Process -FilePath $InstallerPath -PassThru -Wait -WindowStyle Hidden -ArgumentList @(
  "/S",
  "/D=$InstallRoot"
)
if ($installProc.ExitCode -ne 0) {
  throw "NSIS silent install failed with exit code $($installProc.ExitCode)"
}

$bundleDir = Join-Path $InstallRoot "desktop/bundle"
if (-not (Test-Path (Join-Path $bundleDir "runtime"))) {
  throw "Installed bundle missing runtime: $bundleDir"
}

. (Join-Path $PSScriptRoot "desktop-runtime-workdir.ps1")
$manifestCheck = Test-HuokeRuntimeManifest -BundleDir $bundleDir
if (-not $manifestCheck.Ok) {
  throw ("Installed bundle manifest failed:`n" + ($manifestCheck.Issues -join "`n"))
}

$dataDir = Join-Path $env:TEMP "huoke-nsis-data-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$stdoutFile = Join-Path $env:TEMP "huoke-nsis-stdout-$BackendPort.log"
$stderrFile = Join-Path $env:TEMP "huoke-nsis-stderr-$BackendPort.log"
if (Test-Path $stdoutFile) { Remove-Item $stdoutFile -Force }
if (Test-Path $stderrFile) { Remove-Item $stderrFile -Force }

$backendScript = Join-Path $InstallRoot "scripts/desktop-run-backend.ps1"
if (-not (Test-Path $backendScript)) {
  throw "Installed backend script missing: $backendScript"
}

$proc = Start-Process -FilePath "powershell.exe" -PassThru -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $backendScript
) -WorkingDirectory $InstallRoot -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -Environment @{
  HUOKE_ROOT = $InstallRoot
  HUOKE_BUNDLE_DIR = $bundleDir
  HUOKE_DATA_DIR = $dataDir
  BACKEND_PORT = "$BackendPort"
}

try {
  $deadline = (Get-Date).AddSeconds(180)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) { break }
    try {
      Wait-BackendHealth -Port $BackendPort -TimeoutSec 2
      $healthy = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }

  if (-not $healthy) {
    Show-SmokeFailureLogs -StdoutFile $stdoutFile -StderrFile $stderrFile
    if ($proc.HasExited) {
      throw "NSIS-installed backend exited early with code $($proc.ExitCode)"
    }
    throw "NSIS-installed backend startup timed out"
  }

  $stdoutText = if (Test-Path $stdoutFile) { Get-Content $stdoutFile -Raw } else { "" }
  foreach ($needle in @("greenlet ok", "app.main ok", "runtime-work")) {
    if ($stdoutText -notmatch [regex]::Escape($needle)) {
      Show-SmokeFailureLogs -StdoutFile $stdoutFile -StderrFile $stderrFile
      throw "NSIS smoke missing expected log line: $needle"
    }
  }

  Write-Host "NSIS installed startup smoke ok: $InstallRoot"
} finally {
  if (-not $proc.HasExited) {
    try {
      & taskkill.exe /PID $proc.Id /T /F | Out-Null
    } catch {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Start-Sleep -Seconds 1

  $uninstaller = Join-Path $InstallRoot "uninstall.exe"
  if (Test-Path $uninstaller) {
    try {
      Start-Process -FilePath $uninstaller -ArgumentList "/S" -Wait -WindowStyle Hidden | Out-Null
    } catch {}
  }
  if (Test-Path $InstallRoot) {
    Remove-Item -Recurse -Force $InstallRoot -ErrorAction SilentlyContinue
  }
  if (Test-Path $dataDir) {
    Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
  }
}

exit 0
