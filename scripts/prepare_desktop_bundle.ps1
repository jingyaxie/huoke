# Tauri 打包前准备：构建前端静态资源 + 打入 Python 后端 bundle（Windows）
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$BundleDir = Join-Path $Root "desktop/bundle"
$BackendSrc = Join-Path $Root "backend"
$RuntimeDir = Join-Path $BundleDir "runtime"
$VenvDir = Join-Path $RuntimeDir ".venv"
$TargetBackend = Join-Path $BundleDir "backend"

Write-Host "构建前端 (desktop /api 同源)..."
Push-Location $FrontendDir
if (-not (Test-Path "node_modules")) {
  npm install
}
$env:VITE_API_BASE_URL = "/api"
npm run build
Pop-Location

$Python = Find-HuokePython
if (-not $Python) {
  Write-Error "未找到 Python 3.11+，无法准备桌面 bundle。请安装 Python 3.11 或 3.12。"
}

Write-Host "清理旧 bundle..."
if (Test-Path $BundleDir) {
  Remove-Item -Recurse -Force $BundleDir
}
New-Item -ItemType Directory -Force -Path $TargetBackend, $RuntimeDir | Out-Null

Write-Host "复制后端代码..."
$exclude = @(".venv", "__pycache__", ".pytest_cache", "reports", "storage")
robocopy $BackendSrc $TargetBackend /E /NFL /NDL /NJH /NJS /nc /ns /np `
  /XD $exclude | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制后端失败 (robocopy exit $LASTEXITCODE)" }

$FrontendDist = Join-Path $FrontendDir "dist"
if (Test-Path $FrontendDist) {
  Write-Host "复制前端静态资源..."
  $TargetFrontend = Join-Path $BundleDir "frontend-dist"
  robocopy $FrontendDist $TargetFrontend /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "复制前端 dist 失败" }
}

Write-Host "创建虚拟环境 ($Python)..."
Invoke-HuokePython $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "创建 venv 失败" }

$PipPython = Join-Path $VenvDir "Scripts/python.exe"
& $PipPython -m pip install -U pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }
& $PipPython -m pip install -r (Join-Path $TargetBackend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "安装 Python 依赖失败" }

Write-Host "bundle 就绪: $BundleDir"
