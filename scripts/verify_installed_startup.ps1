# CI: simulate installed layout (ASCII + Unicode paths) and verify backend startup.
param(
  [Parameter(Mandatory = $true)][string]$RepoRoot,
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [int]$BackendPort = 18765
)

$ErrorActionPreference = "Stop"

function Copy-InstalledLayout {
  param(
    [string]$SourceRoot,
    [string]$TargetRoot
  )
  if (Test-Path $TargetRoot) {
    Remove-Item -Recurse -Force $TargetRoot
  }
  New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
  robocopy (Join-Path $SourceRoot "scripts") (Join-Path $TargetRoot "scripts") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "scripts copy failed ($LASTEXITCODE)" }
  robocopy (Join-Path $SourceRoot "desktop/bundle") (Join-Path $TargetRoot "desktop/bundle") /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "bundle copy failed ($LASTEXITCODE)" }
  $exampleEnv = Join-Path $SourceRoot ".env.desktop.example"
  if (Test-Path $exampleEnv) {
    Copy-Item $exampleEnv (Join-Path $TargetRoot ".env.desktop.example")
  }
}

function Wait-BackendHealth {
  param([int]$Port, [int]$TimeoutSec = 120)
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

Copy-InstalledLayout -SourceRoot $RepoRoot -TargetRoot $InstallRoot

$dataDir = Join-Path $env:TEMP "huoke-smoke-data-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$env:HUOKE_ROOT = $InstallRoot
$env:HUOKE_BUNDLE_DIR = Join-Path $InstallRoot "desktop/bundle"
$env:HUOKE_DATA_DIR = $dataDir
$env:BACKEND_PORT = "$BackendPort"

$proc = Start-Process -FilePath "powershell.exe" -PassThru -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", (Join-Path $InstallRoot "scripts/desktop-run-backend.ps1")
)

try {
  $deadline = (Get-Date).AddSeconds(120)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
      $logFile = Join-Path $dataDir "logs/desktop-backend.log"
      if (Test-Path $logFile) {
        Write-Host "--- desktop-backend.log ---"
        Get-Content $logFile -Tail 80 | ForEach-Object { Write-Host $_ }
      }
      throw "backend exited early with code $($proc.ExitCode) for install root: $InstallRoot"
    }
    try {
      Wait-BackendHealth -Port $BackendPort -TimeoutSec 2
      $healthy = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $healthy) {
    throw "backend startup timed out for install root: $InstallRoot"
  }
  Write-Host "startup smoke ok: $InstallRoot"
} finally {
  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path $dataDir) {
    Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
  }
}
