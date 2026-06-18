# Fast local/CI validation for Windows desktop packaging scripts.
# Run on Windows before pushing tags: pwsh ./scripts/validate_desktop_scripts.ps1
$ErrorActionPreference = "Stop"

function Test-PowerShellScriptSyntax {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    throw "missing script: $Path"
  }
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $Path),
    [ref]$tokens,
    [ref]$errors
  )
  if ($errors -and $errors.Count -gt 0) {
    $details = ($errors | ForEach-Object { $_.ToString() }) -join "`n"
    throw "PowerShell syntax error in ${Path}:`n$details"
  }
  Write-Host "syntax ok: $Path"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
  foreach ($script in @(
      "scripts/desktop-run-backend.ps1",
      "scripts/desktop-bundle-cache.ps1",
      "scripts/verify_installed_startup.ps1",
      "scripts/_python_win.ps1"
    )) {
    Test-PowerShellScriptSyntax -Path $script
  }

  $config = Get-Content "desktop/src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json
  if ($config.app.windows[0].url -ne "about:blank") {
    throw "main window must start at about:blank, got: $($config.app.windows[0].url)"
  }
  Write-Host "tauri.conf.json ok"

  if (Test-Path "desktop/bundle/runtime") {
    Write-Host "bundle present, running installed-layout smoke (ASCII)..."
    $asciiRoot = Join-Path $env:TEMP "huoke-validate-ascii"
    & (Join-Path $repoRoot "scripts/verify_installed_startup.ps1") `
      -RepoRoot $repoRoot `
      -InstallRoot $asciiRoot `
      -BackendPort 18766
    Write-Host "installed-layout smoke ok"
  } else {
    Write-Host "desktop/bundle missing; syntax-only validation passed (run prepare_desktop_bundle.ps1 for full smoke)"
  }

  Write-Host "validate_desktop_scripts: all checks passed"
} finally {
  Pop-Location
}
