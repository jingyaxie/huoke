#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/desktop-common.sh
source "$ROOT/scripts/desktop-common.sh"
HUOKE_ROOT="$ROOT"
ensure_desktop_path

BUNDLE_DIR="$(resolve_huoke_bundle_dir)"
DATA_DIR="$(resolve_huoke_data_dir)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
STORAGE_DIR="$DATA_DIR/storage"
ENV_FILE="$DATA_DIR/.env.desktop"
LOG_FILE="$DATA_DIR/logs/desktop-backend.log"

mkdir -p "$DATA_DIR" "$STORAGE_DIR" "$DATA_DIR/logs"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[$(date '+%F %T')] desktop-run-backend root=$ROOT bundle=$BUNDLE_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.desktop.example" "$ENV_FILE"
  echo "已创建桌面配置: $ENV_FILE"
  echo "请按需编辑 API Key 后重启应用。"
fi

if [[ -d "$BUNDLE_DIR/runtime/.venv" ]]; then
  BACKEND_DIR="$BUNDLE_DIR/backend"
  PYTHON="$BUNDLE_DIR/runtime/.venv/bin/python"
else
  BACKEND_DIR="$ROOT/backend"
  if [[ -d "$BACKEND_DIR/.venv" ]]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
  else
    PYTHON=""
    for candidate in python3.12 python3.11 python3; do
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
  fi
fi

if [[ -z "${PYTHON:-}" || ! -x "$PYTHON" ]]; then
  echo "未找到可用的 Python 3.11+ 运行时" >&2
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "未找到 Google Chrome: $CHROME" >&2
  echo "桌面版依赖系统 Chrome 驱动 Playwright。" >&2
  exit 1
fi

if lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "端口 ${BACKEND_PORT} 已被占用，跳过后端启动。" >&2
  exit 0
fi

cd "$BACKEND_DIR"
export DESKTOP_MODE=true
if [[ -d "$BUNDLE_DIR/frontend-dist" ]]; then
  export FRONTEND_DIST_DIR="$BUNDLE_DIR/frontend-dist"
else
  export FRONTEND_DIST_DIR="$ROOT/frontend/dist"
fi
export STORAGE_ROOT="$STORAGE_DIR"
export FRONTEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "执行数据库迁移..."
run_alembic() {
  "$PYTHON" -m alembic upgrade head
}

if ! run_alembic; then
  echo "数据库迁移失败，桌面模式将重置本地库后重试..." >&2
  if docker exec huoke_desktop_mysql mysql -uroot -proot -e \
    "DROP DATABASE IF EXISTS douyin_hot; CREATE DATABASE douyin_hot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON douyin_hot.* TO 'douyin'@'%'; FLUSH PRIVILEGES;" 2>/dev/null; then
    run_alembic
  else
    echo "数据库修复失败，请查看 $LOG_FILE" >&2
    exit 1
  fi
fi

echo "启动后端: $PYTHON (port ${BACKEND_PORT})"
exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}"
