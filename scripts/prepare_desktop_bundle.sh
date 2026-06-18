#!/usr/bin/env bash
# Tauri 打包前准备：构建前端静态资源 + 打入完整 Python 后端 bundle（客户机无需预装 Python）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"
BUNDLE_DIR="$ROOT/desktop/bundle"
BACKEND_SRC="$ROOT/backend"
RUNTIME_DIR="$BUNDLE_DIR/runtime"
TARGET_BACKEND="$BUNDLE_DIR/backend"
PORTABLE_DIR="$RUNTIME_DIR/python"

echo "构建前端 (desktop /api 同源)..."
cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
fi
VITE_API_BASE_URL=/api npm run build

echo "清理旧 bundle..."
rm -rf "$BUNDLE_DIR"
mkdir -p "$TARGET_BACKEND" "$RUNTIME_DIR"

echo "复制后端代码..."
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'reports' \
  --exclude 'storage' \
  "$BACKEND_SRC/" "$TARGET_BACKEND/"

if [[ -d "$FRONTEND_DIR/dist" ]]; then
  echo "复制前端静态资源..."
  rsync -a "$FRONTEND_DIR/dist/" "$BUNDLE_DIR/frontend-dist/"
fi

bash "$ROOT/scripts/install_portable_python_unix.sh" "$PORTABLE_DIR" "$TARGET_BACKEND/requirements.txt"

PYTHON_BIN=""
for candidate in \
  "$PORTABLE_DIR/bin/python3.12" \
  "$PORTABLE_DIR/bin/python3"; do
  if [[ -x "$candidate" ]]; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "portable python binary missing under $PORTABLE_DIR" >&2
  exit 1
fi

echo "验证 portable Python 可加载后端..."
PYTHONPATH="$TARGET_BACKEND" "$PYTHON_BIN" -c "from app.db.bootstrap import ensure_database_schema; print('backend import ok')"

cat > "$BUNDLE_DIR/BUNDLE_MANIFEST.json" <<EOF
{
  "kind": "huoke-desktop-bundle",
  "python": "runtime/python",
  "backend": "backend",
  "frontend": "frontend-dist",
  "notes": "Self-contained desktop runtime. Customer only needs Google Chrome for browser automation."
}
EOF

echo "bundle 就绪: $BUNDLE_DIR"
