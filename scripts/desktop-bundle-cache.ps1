# Sync desktop bundle to an ASCII-only cache when Unicode install paths break portable Python.
$ErrorActionPreference = "Stop"

function Test-HuokePathHasNonAscii {
  param([string]$Path)
  if (-not $Path) { return $false }
  foreach ($ch in $Path.ToCharArray()) {
    if ([int][char]$ch -gt 127) { return $true }
  }
  return $false
}

function Find-PortablePythonExe {
  param([Parameter(Mandatory = $true)][string]$BundleDir)
  foreach ($candidate in @(
      (Join-Path $BundleDir "runtime/python/python.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python3.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python3.12.exe")
    )) {
    if (Test-Path $candidate) { return $candidate }
  }
  return $null
}

function Test-PortablePythonRunnable {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$BackendDir
  )
  if (-not (Test-Path $PythonExe)) { return $false }
  if (-not (Test-Path $BackendDir)) { return $false }
  $prevPythonPath = $env:PYTHONPATH
  $env:PYTHONPATH = $BackendDir
  try {
    & $PythonExe -c "import uvicorn; print('portable python probe ok')" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
  } finally {
    if ($null -eq $prevPythonPath) {
      Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
      $env:PYTHONPATH = $prevPythonPath
    }
  }
}

function Get-HuokeBundleFingerprint {
  param([Parameter(Mandatory = $true)][string]$BundleDir)
  $manifest = Join-Path $BundleDir "BUNDLE_MANIFEST.json"
  if (Test-Path $manifest) {
    return (Get-FileHash -Algorithm SHA256 -Path $manifest).Hash
  }
  return (Get-Item $BundleDir).LastWriteTimeUtc.Ticks.ToString()
}

function Sync-HuokeBundleCache {
  param(
    [Parameter(Mandatory = $true)][string]$SourceBundleDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$Root = ""
  )

  if (-not (Test-Path (Join-Path $SourceBundleDir "runtime"))) {
    throw "Source bundle missing runtime: $SourceBundleDir"
  }

  $backendDir = Join-Path $SourceBundleDir "backend"
  $pythonExe = Find-PortablePythonExe -BundleDir $SourceBundleDir
  $needsCache = (Test-HuokePathHasNonAscii $Root) -or (Test-HuokePathHasNonAscii $SourceBundleDir)
  if (-not $needsCache) {
    $needsCache = -not (Test-PortablePythonRunnable -PythonExe $pythonExe -BackendDir $backendDir)
  }

  if (-not $needsCache) {
    return $SourceBundleDir
  }

  $cacheRoot = Join-Path $DataDir "bundle-cache"
  $cacheBundle = Join-Path $cacheRoot "current"
  $manifestFile = Join-Path $cacheRoot "CACHE_MANIFEST.json"
  $fingerprint = Get-HuokeBundleFingerprint -BundleDir $SourceBundleDir

  $reuse = $false
  if (Test-Path $manifestFile) {
    try {
      $existing = Get-Content $manifestFile -Raw | ConvertFrom-Json
      if ($existing.fingerprint -eq $fingerprint -and (Test-Path (Join-Path $cacheBundle "runtime"))) {
        $cachedPython = Find-PortablePythonExe -BundleDir $cacheBundle
        if (Test-PortablePythonRunnable -PythonExe $cachedPython -BackendDir (Join-Path $cacheBundle "backend")) {
          $reuse = $true
        }
      }
    } catch {}
  }

  if ($reuse) {
    return $cacheBundle
  }

  Write-Host "Syncing bundle cache to ASCII path: $cacheBundle"
  if (Test-Path $cacheBundle) {
    Remove-Item -Recurse -Force $cacheBundle
  }
  New-Item -ItemType Directory -Force -Path $cacheBundle | Out-Null

  foreach ($name in @("runtime", "backend", "frontend-dist")) {
    $src = Join-Path $SourceBundleDir $name
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $cacheBundle $name
    robocopy $src $dst /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
      throw "Failed to cache bundle component '$name' (robocopy exit $LASTEXITCODE)"
    }
  }

  Copy-Item (Join-Path $SourceBundleDir "BUNDLE_MANIFEST.json") (Join-Path $cacheBundle "BUNDLE_MANIFEST.json") -ErrorAction SilentlyContinue
  @{
    fingerprint = $fingerprint
    source = $SourceBundleDir
    cached_at = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json | Set-Content -Path $manifestFile -Encoding UTF8

  $cachedPython = Find-PortablePythonExe -BundleDir $cacheBundle
  if (-not (Test-PortablePythonRunnable -PythonExe $cachedPython -BackendDir (Join-Path $cacheBundle "backend"))) {
    throw "Bundle cache sync completed but portable Python still cannot import uvicorn"
  }

  return $cacheBundle
}
