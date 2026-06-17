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

function Find-HuokePython {
  foreach ($candidate in @("py -3.12", "py -3.11", "python3.12", "python3.11", "python")) {
    try {
      $ver = Invoke-HuokePython $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
      if ($LASTEXITCODE -ne 0) { continue }
      $parts = $ver.Trim() -split "\."
      $major = [int]$parts[0]
      $minor = [int]$parts[1]
      if ($major -ge 3 -and $minor -ge 11) {
        return $candidate
      }
    } catch {}
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
