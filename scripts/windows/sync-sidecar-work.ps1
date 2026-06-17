# Sync bundled huoke-sidecar (read-only install dir) to userData work dir.
param(
    [Parameter(Mandatory = $true)][string]$BundledRoot,
    [Parameter(Mandatory = $true)][string]$WorkRoot
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $BundledRoot "python-runtime\python.exe"))) {
    throw "[sync] bundled python-runtime missing: $BundledRoot"
}

Write-Host "[sync] bundled -> work" -ForegroundColor Cyan
Write-Host "[sync] from: $BundledRoot"
Write-Host "[sync] to:   $WorkRoot"

if (Test-Path $WorkRoot) {
    Remove-Item -Recurse -Force $WorkRoot
}
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null

# robocopy exit codes 0-7 are success; >=8 is failure
& robocopy $BundledRoot $WorkRoot /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
$roboCode = $LASTEXITCODE
if ($roboCode -ge 8) {
    throw "[sync] robocopy failed with exit code $roboCode"
}

$marker = Join-Path $BundledRoot "bundle-version.json"
if (Test-Path $marker) {
    Copy-Item -Force $marker (Join-Path $WorkRoot "bundle-version.json")
}

$Py = Join-Path $WorkRoot "python-runtime\python.exe"
$RuntimeRoot = Join-Path $WorkRoot "python-runtime"
$prevPath = $env:PATH
try {
    $env:PATH = "$RuntimeRoot;$RuntimeRoot\DLLs;$RuntimeRoot\Scripts;$env:PATH"
    Remove-Item env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item env:PYTHONPATH -ErrorAction SilentlyContinue

    Write-Host "[sync] verifying python imports ..." -ForegroundColor Cyan
    & $Py -c "import sys; print('exe=', sys.executable)"
    & $Py -c "import greenlet; print('greenlet=', greenlet.__version__)"
    & $Py -c "import uvicorn; print('uvicorn ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "[sync] uvicorn import failed"
    }
} finally {
    $env:PATH = $prevPath
}

Write-Host "[sync] work sidecar ready: $WorkRoot" -ForegroundColor Green
