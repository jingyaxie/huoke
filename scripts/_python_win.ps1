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

function Test-HuokePythonCandidate {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  try {
    $ver = Invoke-HuokePython $Candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) { return $null }
    $parts = $ver.Trim() -split "\."
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
  if ($env:PYTHON) { $preferred += $env:PYTHON }
  if ($env:pythonLocation) {
    $preferred += (Join-Path $env:pythonLocation "python.exe")
  }
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd -and $pythonCmd.Source) {
    $preferred += $pythonCmd.Source
  }

  foreach ($candidate in $preferred) {
    $found = Test-HuokePythonCandidate $candidate
    if ($found) { return $found }
  }

  foreach ($candidate in @("py -3.12", "py -3.11", "python3.12", "python3.11", "python")) {
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
    return $exe.Trim()
  }
  return $Candidate
}
