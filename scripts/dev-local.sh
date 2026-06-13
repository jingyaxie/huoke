#!/usr/bin/env bash
# 本地 Mac 开发：MySQL 走 Docker，后端在宿主机运行，浏览器使用系统 Chrome。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/.env.local" ]]; then
  echo "请先复制配置: cp .env.local.example .env.local" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "dev-local.sh 面向 macOS 宿主机 + 系统 Chrome；Linux 请用 docker compose 全栈部署。" >&2
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "未找到系统 Chrome: $CHROME" >&2
  echo "请安装 Google Chrome，或在 .env.local 中调整 ANTIBOT_BROWSER_CHANNEL。" >&2
  exit 1
fi

echo "Chrome: $("$CHROME" --version 2>/dev/null || true)"

BACKEND_PORT="${BACKEND_PORT:-8000}"

# 避免 Docker backend 占用 8000
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx douyin_backend; then
  echo "停止 Docker backend（本地后端需独占 ${BACKEND_PORT} 端口）..."
  docker compose stop backend >/dev/null 2>&1 || true
fi

if lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "端口 ${BACKEND_PORT} 已被占用:" >&2
  lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null || true
  echo "请先释放端口，或设置 BACKEND_PORT=8001 ./scripts/dev-local.sh" >&2
  exit 1
fi

docker compose -f docker-compose.local.yml up -d mysql

BACKEND_DIR="$ROOT/backend"
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

if [[ "$need_recreate_venv" == true ]]; then
  pip install -U pip setuptools wheel
fi

echo "安装依赖..."
pip install -r requirements.txt

echo "等待 MySQL 就绪..."
for _ in $(seq 1 45); do
  if docker compose -f "$ROOT/docker-compose.local.yml" exec -T mysql \
    mysqladmin ping -h localhost -udouyin -pdouyin --silent 2>/dev/null; then
    break
  fi
  sleep 1
done

alembic upgrade head

echo ""
echo "启动后端 (系统 Chrome, 端口 ${BACKEND_PORT})..."
echo "前端: http://localhost:${FRONTEND_PORT:-5173}"
echo "API:  http://localhost:${BACKEND_PORT}/docs"
echo ""

exec uvicorn app.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT}"
