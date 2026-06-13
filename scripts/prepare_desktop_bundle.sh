#!/usr/bin/env bash
# 将 Python 后端与依赖打入 desktop/bundle，供 .app Resources 引用
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$ROOT/desktop/bundle"
BACKEND_SRC="$ROOT/backend"
RUNTIME_DIR="$BUNDLE_DIR/runtime"
VENV_DIR="$RUNTIME_DIR/.venv"
TARGET_BACKEND="$BUNDLE_DIR/backend"

PYTHON=""
for candidate in \
  /opt/homebrew/bin/python3.12 \
  /opt/homebrew/bin/python3.11 \
  /usr/local/bin/python3.12 \
  /usr/local/bin/python3.11 \
  python3.12 \
  python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    major="${ver%%.*}"
    minor="${ver#*.}"
    if (( major >= 3 && minor >= 11 )); then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "未找到 Python 3.11+，无法准备桌面 bundle" >&2
  exit 1
fi

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

if [[ -d "$ROOT/frontend/dist" ]]; then
  echo "复制前端静态资源..."
  rsync -a "$ROOT/frontend/dist/" "$BUNDLE_DIR/frontend-dist/"
fi

echo "创建虚拟环境 ($PYTHON)..."
"$PYTHON" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -U pip setuptools wheel
pip install -r "$TARGET_BACKEND/requirements.txt"

echo "bundle 就绪: $BUNDLE_DIR"
