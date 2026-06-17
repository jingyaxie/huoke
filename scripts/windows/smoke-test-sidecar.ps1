# Verify bundled sidecar python can import native deps before packaging exe.
param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\dist-sidecar"
)

$ErrorActionPreference = "Stop"
$Py = Join-Path $InstallRoot "python-runtime\python.exe"
if (-not (Test-Path $Py)) {
    throw "[smoke] python-runtime missing: $Py"
}

Write-Host "[smoke] python: $Py" -ForegroundColor Cyan
& $Py -c "import sys; print('exe=', sys.executable); print('prefix=', sys.prefix)"
& $Py -c "import greenlet; print('greenlet=', greenlet.__version__)"
& $Py -c "import playwright; print('playwright=', playwright.__version__)"
& $Py -c "import uvicorn; print('uvicorn ok')"

# Ensure MSVC runtime DLLs are bundled next to python.exe (required on clean machines).
$RuntimeRoot = Join-Path $InstallRoot "python-runtime"
$requiredDlls = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
foreach ($d in $requiredDlls) {
    $p = Join-Path $RuntimeRoot $d
    if (-not (Test-Path $p)) {
        throw "[smoke] bundled VC runtime missing: $p (install-sidecar.ps1 must copy it)"
    }
    Write-Host "[smoke] VC runtime present: $d" -ForegroundColor Cyan
}

# Simulate packaged install: copy bundle to temp work dir and verify imports (robocopy path).
$work = Join-Path $env:TEMP ("huoke-sidecar-work-smoke-" + [guid]::NewGuid().ToString("n"))
Write-Host "[smoke] sync simulation -> $work" -ForegroundColor Cyan
& "$PSScriptRoot\sync-sidecar-work.ps1" -BundledRoot $InstallRoot -WorkRoot $work
if ($LASTEXITCODE -ne 0) { throw "[smoke] sync-sidecar-work failed" }
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue

Write-Host "[smoke] sidecar runtime imports OK" -ForegroundColor Green
