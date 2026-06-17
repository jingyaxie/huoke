function Invoke-HuokePython {
  param(
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs
  )
  if ($Candidate -match "^py\s+-(\d+\.\d+)$") {
    $ver = $Matches[1]
    & py "-$ver" @PythonArgs
  } elseif ($Candidate -match "^py\s+(-\S+)$") {
    $flag = $Matches[1]
    & py $flag @PythonArgs
  } else {
    & $Candidate @PythonArgs
  }
}

function Test-WindowsPythonStub {
  param([string]$Path)
  if (-not $Path) { return $false }
  return $Path -match "(\\|/)WindowsApps(\\|/)python(\.exe)?$"
}

function Get-HuokePythonVersionText {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  $output = Invoke-HuokePython $Candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($LASTEXITCODE -ne 0) { return $null }
  $text = ($output | Out-String).Trim()
  if (-not $text) { return $null }
  return $text
}

function Test-HuokePythonCandidate {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  if (Test-WindowsPythonStub $Candidate) { return $null }
  try {
    $ver = Get-HuokePythonVersionText $Candidate
    if (-not $ver) { return $null }
    $parts = $ver -split "\."
    if ($parts.Count -lt 2) { return $null }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -ge 3 -and $minor -ge 11) {
      return $Candidate
    }
  } catch {}
  return $null
}

function Find-HuokePython {
  $preferred = @()
  if ($env:HUOKE_PYTHON) { $preferred += $env:HUOKE_PYTHON }
  if ($env:PYTHON) { $preferred += $env:PYTHON }
  if ($env:pythonLocation) {
    $preferred += (Join-Path $env:pythonLocation "python.exe")
  }
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd -and $pythonCmd.Source) {
    $preferred += $pythonCmd.Source
  }

  $seen = @{}
  foreach ($candidate in $preferred) {
    if (-not $candidate -or $seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    $found = Test-HuokePythonCandidate $candidate
    if ($found) { return $found }
  }

  foreach ($candidate in @("py -3.12", "py -3.11", "python3.12", "python3.11", "python")) {
    if ($seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    $found = Test-HuokePythonCandidate $candidate
    if ($found) { return $found }
  }
  return $null
}

function Resolve-HuokePythonExe {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  if ($Candidate -match "^py\s") {
    $exe = Invoke-HuokePython $Candidate -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($exe | Out-String).Trim()
  }
  return $Candidate
}

function Set-HuokePythonEnv {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  $exe = Resolve-HuokePythonExe $Candidate
  if (-not $exe -or -not (Test-Path $exe)) {
    throw "Failed to resolve Python executable from candidate: $Candidate"
  }
  $env:HUOKE_PYTHON = $exe
  $env:PYTHON = $exe
  return $exe
}

function Write-HuokePythonDiagnostics {
  Write-Host "Python diagnostics:"
  Write-Host "  HUOKE_PYTHON=$($env:HUOKE_PYTHON)"
  Write-Host "  PYTHON=$($env:PYTHON)"
  Write-Host "  pythonLocation=$($env:pythonLocation)"
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    Write-Host "  Get-Command python -> $($cmd.Source)"
  } else {
    Write-Host "  Get-Command python -> (not found)"
  }
}
