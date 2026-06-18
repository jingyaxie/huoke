# 为 Windows 桌面安装包准备可移植 Python（python-build-standalone），客户机无需预装 Python。
$ErrorActionPreference = "Stop"

function Find-PortablePythonExe {
  param([Parameter(Mandatory = $true)][string]$Root)
  $candidates = @(
    (Join-Path $Root "python.exe"),
    (Join-Path $Root "bin\python.exe"),
    (Join-Path $Root "bin\python3.exe"),
    (Join-Path $Root "bin\python3.12.exe")
  )
  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }
  $found = Get-ChildItem -Path $Root -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\venv\\' } |
    Select-Object -First 1
  if ($found) { return $found.FullName }
  return $null
}

function Write-PortablePythonSitecustomize {
  param([Parameter(Mandatory = $true)][string]$PythonRoot)
  $sitecustomize = Join-Path $PythonRoot "Lib\sitecustomize.py"
  @'
"""Huoke portable Python: register DLL directories for native extensions on Windows."""
import os
import sys


def _register_windows_dll_dirs() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    base = os.path.dirname(os.path.abspath(sys.executable))
    for name in ("", "DLLs"):
        candidate = os.path.join(base, name) if name else base
        if os.path.isdir(candidate):
            try:
                os.add_dll_directory(candidate)
            except OSError:
                pass


_register_windows_dll_dirs()
'@ | Set-Content -Path $sitecustomize -Encoding UTF8
}

function Set-PortablePythonEnvForExe {
  param([Parameter(Mandatory = $true)][string]$PythonExe)
  $pythonRoot = Split-Path $PythonExe -Parent
  if ((Split-Path $pythonRoot -Leaf) -eq "bin") {
    $pythonRoot = Split-Path $pythonRoot -Parent
  }
  Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
  $env:PYTHONUTF8 = "1"
  $dllDirs = @($pythonRoot, (Join-Path $pythonRoot "DLLs"))
  $prefix = (($dllDirs | Where-Object { Test-Path $_ }) -join ";")
  if ($prefix) {
    $env:PATH = "$prefix;$env:PATH"
  }
  return $pythonRoot
}

function Install-HuokePortablePython {
  param(
    [Parameter(Mandatory = $true)][string]$TargetDir,
    [Parameter(Mandatory = $true)][string]$RequirementsFile,
    [string]$PythonVersion = "3.12.9",
    [string]$ReleaseTag = "20250205"
  )

  if (-not (Test-Path $RequirementsFile)) {
    throw "Requirements file not found: $RequirementsFile"
  }

  $tarball = "cpython-$PythonVersion+$ReleaseTag-x86_64-pc-windows-msvc-install_only.tar.gz"
  $url = "https://github.com/astral-sh/python-build-standalone/releases/download/$ReleaseTag/$tarball"
  $tmpTar = Join-Path ([System.IO.Path]::GetTempPath()) "huoke-$tarball"
  $stage = Join-Path ([System.IO.Path]::GetTempPath()) "huoke-python-stage"

  if (Test-Path $stage) {
    Remove-Item -Recurse -Force $stage
  }
  if (Test-Path $TargetDir) {
    Remove-Item -Recurse -Force $TargetDir
  }
  New-Item -ItemType Directory -Force -Path $stage, $TargetDir | Out-Null

  Write-Host "Downloading portable Python $PythonVersion (x86_64-pc-windows-msvc)..."
  Invoke-WebRequest -Uri $url -OutFile $tmpTar -UseBasicParsing
  tar -xzf $tmpTar -C $stage
  Remove-Item $tmpTar -ErrorAction SilentlyContinue

  $pythonExe = Find-PortablePythonExe -Root $stage
  if (-not $pythonExe) {
    throw "python.exe not found in standalone archive"
  }

  $runtimeHome = Split-Path $pythonExe -Parent
  if ((Split-Path $runtimeHome -Leaf) -eq "bin") {
    $runtimeHome = Split-Path $runtimeHome -Parent
  }

  Write-Host "Staging portable Python from $runtimeHome"
  robocopy $runtimeHome $TargetDir /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "Failed to stage portable Python (robocopy $LASTEXITCODE)" }
  Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

  $pythonExe = Find-PortablePythonExe -Root $TargetDir
  if (-not $pythonExe) {
    throw "python.exe missing after staging: $TargetDir"
  }

  $pythonRoot = Split-Path $pythonExe -Parent
  if ((Split-Path $pythonRoot -Leaf) -eq "bin") {
    $pythonRoot = Split-Path $pythonRoot -Parent
  }
  Write-PortablePythonSitecustomize -PythonRoot $pythonRoot

  Write-Host "Installing pip + backend requirements..."
  # Pipe subprocess stdout away from the success stream so callers can safely capture the return path.
  & $pythonExe -m ensurepip --upgrade 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "ensurepip failed with exit code $LASTEXITCODE" }
  & $pythonExe -m pip install --disable-pip-version-check -U pip setuptools wheel 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }
  & $pythonExe -m pip install --disable-pip-version-check -r $RequirementsFile 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed with exit code $LASTEXITCODE" }

  $BrowsersDir = Join-Path (Split-Path $TargetDir -Parent) "playwright-browsers"
  if (Test-Path $BrowsersDir) {
    Remove-Item -Recurse -Force $BrowsersDir
  }
  New-Item -ItemType Directory -Force -Path $BrowsersDir | Out-Null
  $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir

  Write-Host "Installing Playwright Chromium into $BrowsersDir..."
  Write-Host "  - full browser (--no-shell) for headed desktop automation"
  & $pythonExe -m playwright install chromium --no-shell 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright install chromium --no-shell failed with exit code $LASTEXITCODE" }
  Write-Host "  - headless shell (required by Playwright 1.6x for headless launch)"
  & $pythonExe -m playwright install chromium-headless-shell 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright install chromium-headless-shell failed with exit code $LASTEXITCODE" }

  $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir
  $verifyScript = Join-Path $PSScriptRoot "verify_playwright_bundle.py"
  & $pythonExe $verifyScript 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright chromium launch smoke test failed" }

  Set-PortablePythonEnvForExe -PythonExe $pythonExe | Out-Null
  & $pythonExe -c "import greenlet; from greenlet._greenlet import _C_API; print('greenlet native ok')" 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "greenlet native extension smoke test failed" }

  & $pythonExe -c "import uvicorn, fastapi, sqlalchemy, playwright; print('portable python smoke test ok')" 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "portable python import smoke test failed" }

  Write-Host "Portable Python ready: $pythonExe"
  return $pythonExe
}
