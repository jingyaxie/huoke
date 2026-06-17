#!/usr/bin/env bash
# 打包 Sidecar 分发目录（供 electron-builder extraResources 引用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_SRC="$ROOT/backend"
OUTPUT_ROOT="${1:-$ROOT/dist-sidecar}"
VENV_DIR="$OUTPUT_ROOT/venv"
TARGET_BACKEND="$OUTPUT_ROOT/backend"
STORAGE_DIR="$OUTPUT_ROOT/storage"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build-sidecar-macos.sh 仅面向 macOS" >&2
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "需要安装 Google Chrome（Playwright 扫码登录）" >&2
  exit 1
fi

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
  echo "未找到 Python 3.11+" >&2
  exit 1
fi

echo "[sidecar] 输出目录: $OUTPUT_ROOT"
rm -rf "$OUTPUT_ROOT"
mkdir -p "$TARGET_BACKEND" "$STORAGE_DIR"

echo "[sidecar] 复制后端..."
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'reports' \
  --exclude 'storage' \
  "$BACKEND_SRC/" "$TARGET_BACKEND/"

echo "[sidecar] 复制内置 skills/rules（builtin 技能定义，不含租户数据）..."
mkdir -p "$TARGET_BACKEND/storage/skills" "$TARGET_BACKEND/storage/rules" "$STORAGE_DIR/skills" "$STORAGE_DIR/rules"
if [[ -f "$BACKEND_SRC/storage/skills/global.json" ]]; then
  cp "$BACKEND_SRC/storage/skills/global.json" "$TARGET_BACKEND/storage/skills/global.json"
  cp "$BACKEND_SRC/storage/skills/global.json" "$STORAGE_DIR/skills/global.json"
fi
if [[ -f "$BACKEND_SRC/storage/rules/global.json" ]]; then
  cp "$BACKEND_SRC/storage/rules/global.json" "$TARGET_BACKEND/storage/rules/global.json"
  cp "$BACKEND_SRC/storage/rules/global.json" "$STORAGE_DIR/rules/global.json"
fi

echo "[sidecar] 创建 venv ($PYTHON)..."
"$PYTHON" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -U pip setuptools wheel
pip install -r "$TARGET_BACKEND/requirements.txt"

echo "[sidecar] 安装 Playwright Chromium..."
python -m playwright install chromium

FRONTEND_DIST="$OUTPUT_ROOT/frontend-dist"
echo "[sidecar] 构建管理台前端..."
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
VITE_API_BASE_URL=/api npm run build
rm -rf "$FRONTEND_DIST"
cp -R dist "$FRONTEND_DIST"
echo "[sidecar] 前端输出: $FRONTEND_DIST"

ENV_SIDECAR="$OUTPUT_ROOT/.env.sidecar"
if [[ -f "$ROOT/.env.sidecar.example" ]]; then
  cp "$ROOT/.env.sidecar.example" "$ENV_SIDECAR"
else
  cat >"$ENV_SIDECAR" <<'EOF'
APP_NAME="Huoke Sidecar"
DEBUG=false
HUOKE_BRIDGE_SECRET=dev-bridge-secret
COMPAT_ENABLED=true
COMPAT_MAX_CONCURRENT=3
DOUYIN_HEADLESS=false
XHS_HEADLESS=false
FRONTEND_ORIGIN=http://127.0.0.1:15174
EOF
fi

cat >>"$ENV_SIDECAR" <<EOF
STORAGE_ROOT=$STORAGE_DIR
DATABASE_URL=sqlite+pysqlite:///$STORAGE_DIR/huoke_sidecar.db
ANTIBOT_BROWSER_CHANNEL=chrome
EOF

echo "[sidecar] 清理 __pycache__ ..."
find "$OUTPUT_ROOT" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

echo "[sidecar] 完成: $OUTPUT_ROOT"
