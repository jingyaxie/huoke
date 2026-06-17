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
DB_FILE="$STORAGE_DIR/huoke_desktop.db"

mkdir -p "$DATA_DIR" "$STORAGE_DIR" "$STORAGE_DIR/douyin/profile" "$DATA_DIR/logs"
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
export DATABASE_URL="sqlite+pysqlite:///${DB_FILE}"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"
export PYTHONPATH="$BACKEND_DIR"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export DATABASE_URL="sqlite+pysqlite:///${DB_FILE}"
export STORAGE_ROOT="$STORAGE_DIR"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"

echo "初始化数据库..."
"$PYTHON" - <<'PY'
from app.db.bootstrap import ensure_database_schema
ensure_database_schema()
print("数据库 schema 已就绪")
PY

echo "启动后端: $PYTHON (port ${BACKEND_PORT}, SQLite)"
exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}"
