#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$ROOT/desktop"

if ! command -v docker >/dev/null 2>&1; then
  echo "需要 Docker Desktop。" >&2
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "需要安装 Google Chrome。" >&2
  exit 1
fi

echo "==> 1/3 构建前端 + Python bundle"
"$ROOT/scripts/desktop-prebuild.sh"

echo "==> 2/3 安装 Tauri CLI 依赖"
cd "$DESKTOP_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi

echo "==> 3/3 打包 macOS 原生应用 (.app / .dmg)"
npm run build

echo ""
echo "构建完成。产物目录:"
echo "  $DESKTOP_DIR/src-tauri/target/release/bundle/macos/"
