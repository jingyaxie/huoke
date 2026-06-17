# Windows 原生桌面应用一键打包（Tauri NSIS 安装包，内置 Python 后端，无需用户安装依赖）
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $Root "desktop"

function Find-ChromePath {
  $paths = @(
    (Join-Path ${env:ProgramFiles} "Google/Chrome/Application/chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google/Chrome/Application/chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google/Chrome/Application/chrome.exe")
  )
  foreach ($p in $paths) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

$Chrome = Find-ChromePath
if (-not $Chrome) {
  Write-Warning "未检测到 Google Chrome。打包可继续，但客户机器需安装 Chrome 才能使用浏览器自动化功能。"
} else {
  Write-Host "检测到 Chrome: $Chrome"
}

# 检查 Python（bundle 准备需要）
$Python = Find-HuokePython
if (-not $Python) {
  Write-Error "需要 Python 3.11+ 才能打包（用于创建内置运行时）。请从 https://www.python.org/downloads/ 安装。"
}
Write-Host "检测到 Python: $Python"

# 检查 Rust
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
  Write-Error "需要 Rust 工具链。请安装: https://rustup.rs/ 并确保已安装 MSVC 构建工具。"
}

Push-Location $DesktopDir
if (-not (Test-Path "node_modules")) {
  npm install
}

Write-Host ""
Write-Host "打包 Windows 安装程序 (NSIS .exe)..."
Write-Host "首次构建可能需 10–20 分钟（下载依赖 + 编译 Rust + 安装 Python 包）..."
Write-Host ""

npm run build

Pop-Location

$BundleDir = Join-Path $DesktopDir "src-tauri/target/release/bundle/nsis"
Write-Host ""
Write-Host "构建完成。产物目录:"
Write-Host "  $BundleDir"
if (Test-Path $BundleDir) {
  Get-ChildItem $BundleDir -Filter "*.exe" | ForEach-Object {
    Write-Host "  安装包: $($_.FullName)"
  }
}
