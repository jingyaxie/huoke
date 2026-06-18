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

  Write-Host "Installing pip + backend requirements..."
  & $pythonExe -m ensurepip --upgrade
  if ($LASTEXITCODE -ne 0) { throw "ensurepip failed with exit code $LASTEXITCODE" }
  & $pythonExe -m pip install --disable-pip-version-check -U pip setuptools wheel
  if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed with exit code $LASTEXITCODE" }
  & $pythonExe -m pip install --disable-pip-version-check -r $RequirementsFile
  if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed with exit code $LASTEXITCODE" }

  & $pythonExe -c "import uvicorn, fastapi, sqlalchemy, playwright; print('portable python smoke test ok')"
  if ($LASTEXITCODE -ne 0) { throw "portable python import smoke test failed" }

  Write-Host "Portable Python ready: $pythonExe"
  return $pythonExe
}
