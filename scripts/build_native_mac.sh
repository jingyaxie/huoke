#!/usr/bin/env bash
# macOS 原生桌面应用一键打包（Tauri beforeBuildCommand 会自动执行 prepare_desktop_bundle.sh）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$ROOT/desktop"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "需要安装 Google Chrome。" >&2
  exit 1
fi

cd "$DESKTOP_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi

echo "打包 macOS 原生应用 (.app / .dmg)..."
npm run build

echo ""
echo "构建完成。产物目录:"
echo "  $DESKTOP_DIR/src-tauri/target/release/bundle/macos/"
