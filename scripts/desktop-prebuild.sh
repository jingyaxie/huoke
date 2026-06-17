#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"

echo "构建前端 (desktop /api 同源)..."
cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi
VITE_API_BASE_URL=/api npm run build

echo "准备桌面运行时 bundle..."
"$ROOT/scripts/prepare_desktop_bundle.sh"
