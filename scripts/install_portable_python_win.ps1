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
  param(
    [Parameter(Mandatory = $true)][string]$PythonRoot,
    [Parameter(Mandatory = $true)][string]$RuntimeDir
  )
  $sitecustomize = Join-Path $PythonRoot "Lib\sitecustomize.py"
  $msvcRel = "../msvc"
  if (Test-Path (Join-Path $RuntimeDir "msvc")) {
    $msvcRel = "../msvc"
  }
  @"
"""Huoke portable Python: register DLL directories for native extensions on Windows."""
import glob
import os
import sys


def _safe_add_dll_directory(path: str) -> None:
    if not path or not os.path.isdir(path):
        return
    if not hasattr(os, "add_dll_directory"):
        return
    try:
        os.add_dll_directory(path)
    except OSError:
        pass


def _register_windows_dll_dirs() -> None:
    if os.name != "nt":
        return
    base = os.path.dirname(os.path.abspath(sys.executable))
    runtime_root = os.path.dirname(base)
    for candidate in (
        base,
        os.path.join(base, "DLLs"),
        os.path.normpath(os.path.join(base, "$msvcRel")),
        os.path.normpath(os.path.join(runtime_root, "msvc")),
    ):
        _safe_add_dll_directory(candidate)

    site_packages = os.path.join(base, "Lib", "site-packages")
    if os.path.isdir(site_packages):
        for name in os.listdir(site_packages):
            pkg_dir = os.path.join(site_packages, name)
            if not os.path.isdir(pkg_dir):
                continue
            try:
                if any(entry.lower().endswith(".pyd") for entry in os.listdir(pkg_dir)):
                    _safe_add_dll_directory(pkg_dir)
            except OSError:
                pass
        for pyd in glob.glob(os.path.join(site_packages, "**", "*.pyd"), recursive=True):
            _safe_add_dll_directory(os.path.dirname(pyd))


_register_windows_dll_dirs()
"@ | Set-Content -Path $sitecustomize -Encoding UTF8
}

function Copy-HuokeMsvcRuntime {
  param(
    [Parameter(Mandatory = $true)][string]$PythonRoot,
    [Parameter(Mandatory = $true)][string]$RuntimeDir
  )
  $msvcDir = Join-Path $RuntimeDir "msvc"
  New-Item -ItemType Directory -Force -Path $msvcDir | Out-Null
  foreach ($name in @("vcruntime140.dll", "vcruntime140_1.dll")) {
    foreach ($srcDir in @($PythonRoot, (Join-Path $PythonRoot "DLLs"))) {
      $src = Join-Path $srcDir $name
      if (Test-Path $src) {
        Copy-Item $src (Join-Path $msvcDir $name) -Force
        break
      }
    }
  }
}

function Set-PortablePythonEnvForExe {
  param([Parameter(Mandatory = $true)][string]$PythonExe)
  $pythonRoot = Split-Path $PythonExe -Parent
  if ((Split-Path $pythonRoot -Leaf) -eq "bin") {
    $pythonRoot = Split-Path $pythonRoot -Parent
  }
  Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
  $env:PYTHONUTF8 = "1"
  $runtimeRoot = Split-Path $pythonRoot -Parent
  $dllDirs = @(
    $pythonRoot,
    (Join-Path $pythonRoot "DLLs"),
    (Join-Path $runtimeRoot "msvc")
  )
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

  $RuntimeDir = Split-Path $TargetDir -Parent
  $RepairWheelsDir = Join-Path $RuntimeDir "repair-wheels"

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
  New-Item -ItemType Directory -Force -Path $stage, $TargetDir, $RepairWheelsDir | Out-Null

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

  Copy-HuokeMsvcRuntime -PythonRoot $pythonRoot -RuntimeDir $RuntimeDir
  Write-PortablePythonSitecustomize -PythonRoot $pythonRoot -RuntimeDir $RuntimeDir

  Write-Host "Installing pip + backend requirements..."
  & $pythonExe -m ensurepip --upgrade 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "ensurepip failed with exit code $LASTEXITCODE" }
  & $pythonExe -m pip install --disable-pip-version-check -U pip setuptools wheel 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }

  Write-Host "Downloading offline repair wheels..."
  if (Test-Path $RepairWheelsDir) {
    Remove-Item -Recurse -Force $RepairWheelsDir
  }
  New-Item -ItemType Directory -Force -Path $RepairWheelsDir | Out-Null
  & $pythonExe -m pip download --disable-pip-version-check `
    -r $RequirementsFile `
    -d $RepairWheelsDir `
    --only-binary=:all: `
    --platform win_amd64 `
    --python-version 312 `
    --implementation cp 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: pip download --only-binary failed; retrying without binary-only constraint"
    & $pythonExe -m pip download --disable-pip-version-check `
      -r $RequirementsFile `
      -d $RepairWheelsDir 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "pip download repair wheels failed" }
  }

  Write-Host "Installing requirements from offline wheels..."
  & $pythonExe -m pip install --disable-pip-version-check `
    --no-index `
    --find-links $RepairWheelsDir `
    -r $RequirementsFile 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "offline pip install requirements failed with exit code $LASTEXITCODE" }

  $BrowsersDir = Join-Path $RuntimeDir "playwright-browsers"
  if (Test-Path $BrowsersDir) {
    Remove-Item -Recurse -Force $BrowsersDir
  }
  New-Item -ItemType Directory -Force -Path $BrowsersDir | Out-Null
  $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir

  Write-Host "Installing Playwright Chromium into $BrowsersDir..."
  & $pythonExe -m playwright install chromium --no-shell 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright install chromium --no-shell failed with exit code $LASTEXITCODE" }
  & $pythonExe -m playwright install chromium-headless-shell 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright install chromium-headless-shell failed with exit code $LASTEXITCODE" }

  $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir
  $verifyScript = Join-Path $PSScriptRoot "verify_playwright_bundle.py"
  & $pythonExe $verifyScript 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "playwright chromium launch smoke test failed" }

  Set-PortablePythonEnvForExe -PythonExe $pythonExe | Out-Null
  $nativeSmoke = @"
import greenlet
from greenlet._greenlet import _C_API
import cryptography
import pydantic_core
from playwright.async_api import async_playwright
print('native extensions ok')
"@
  & $pythonExe -c $nativeSmoke 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "native extension smoke test failed" }

  & $pythonExe -c "import uvicorn, fastapi, sqlalchemy, playwright; print('portable python smoke test ok')" 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "portable python import smoke test failed" }

  Write-Host "Portable Python ready: $pythonExe"
  return $pythonExe
}
