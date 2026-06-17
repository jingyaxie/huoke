#!/usr/bin/env bash
# 本地 Mac 开发（无 Docker）：SQLite + 系统 Chrome + 热更新后端
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
STORAGE_DIR="${STORAGE_DIR:-$ROOT/storage/sidecar-dev}"

if [[ ! -f "$ROOT/.env.local" ]]; then
  echo "请先复制配置: cp .env.local.example .env.local" >&2
  echo "或使用项目根目录已有的 .env.local 模板。" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "dev-native.sh 面向 macOS；Linux 请安装本地 MySQL 或改用 SQLite 后手动启动 uvicorn。" >&2
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "未找到系统 Chrome: $CHROME" >&2
  echo "请安装 Google Chrome，或在 .env.local 中设置 ANTIBOT_PLAYWRIGHT_FALLBACK=true。" >&2
  exit 1
fi
echo "Chrome: $("$CHROME" --version 2>/dev/null || true)"

if lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "端口 ${BACKEND_PORT} 已被占用:" >&2
  lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null || true
  echo "请先停止占用进程，或 BACKEND_PORT=8001 $0" >&2
  exit 1
fi

cd "$BACKEND_DIR"

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
  echo "未找到 Python 3.11+，请安装: brew install python@3.11" >&2
  exit 1
fi
echo "Python: $("$PYTHON" --version)"

need_recreate_venv=false
if [[ -d .venv ]]; then
  venv_py="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
  venv_major="${venv_py%%.*}"
  venv_minor="${venv_py#*.}"
  if (( venv_major < 3 || venv_minor < 11 )); then
    echo "删除旧 venv (Python ${venv_py})，重建为 3.11+..."
    rm -rf .venv
    need_recreate_venv=true
  fi
fi

if [[ ! -d .venv ]]; then
  echo "创建 Python 虚拟环境..."
  "$PYTHON" -m venv .venv
  need_recreate_venv=true
fi

# shellcheck disable=SC1091
source .venv/bin/activate
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"

if [[ "$need_recreate_venv" == true ]]; then
  pip install -U pip setuptools wheel
  pip install -r requirements.txt
  echo "安装 Playwright Chromium（备用，首次较慢）..."
  "$VENV_PYTHON" -m playwright install chromium
fi

mkdir -p "$STORAGE_DIR" "$STORAGE_DIR/douyin/profile"

set -a
# shellcheck disable=SC1091
source "$ROOT/.env.local"
set +a

export DATABASE_URL="sqlite+pysqlite:///${STORAGE_DIR}/huoke_sidecar.db"
export STORAGE_ROOT="$STORAGE_DIR"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"
export PYTHONPATH="$BACKEND_DIR"

echo "等待数据库就绪..."
"$VENV_PYTHON" - <<'PY'
from app.db.bootstrap import ensure_database_schema
ensure_database_schema()
print("数据库 schema 已就绪")
PY

echo ""
echo "启动后端 (无 Docker, SQLite, 端口 ${BACKEND_PORT})"
echo "前端: http://localhost:${FRONTEND_PORT:-5173}  (另开终端: cd frontend && npm run dev)"
echo "API:  http://localhost:${BACKEND_PORT}/docs"
echo ""

exec "$VENV_PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}"
