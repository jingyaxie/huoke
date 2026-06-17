# 使用 NSSM 注册 Windows Service：YingXiaoYi-Huoke
param(
    [string]$InstallRoot = "$PSScriptRoot\..\..\dist-sidecar",
    [string]$ServiceName = "YingXiaoYi-Huoke",
    [string]$NssmPath = "nssm"
)

$ErrorActionPreference = "Stop"
$RunScript = Join-Path $PSScriptRoot "run-engine.ps1"
$Pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $Pwsh) { $Pwsh = (Get-Command powershell).Source }

Write-Host "[service] 注册 $ServiceName ..." -ForegroundColor Cyan
& $NssmPath install $ServiceName $Pwsh "-ExecutionPolicy Bypass -File `"$RunScript`" -InstallRoot `"$InstallRoot`""
& $NssmPath set $ServiceName AppDirectory (Resolve-Path $InstallRoot)
& $NssmPath set $ServiceName DisplayName "盈小蚁 Huoke Sidecar"
& $NssmPath set $ServiceName Description "Huoke 获客引擎 Sidecar (127.0.0.1:18000)"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
Write-Host "[service] 启动: sc.exe start $ServiceName" -ForegroundColor Green
