#!/usr/bin/env bash
# macOS 本地开发：轻量 Huoke Sidecar（127.0.0.1:18000，有头 Chrome 扫码）
# 不依赖 Docker MySQL，使用 SQLite + 系统 Chrome。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
SIDECAR_PORT="${SIDECAR_PORT:-18000}"
STORAGE_DIR="${STORAGE_DIR:-$ROOT/storage/sidecar-dev}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "dev-sidecar-macos.sh 仅面向 macOS；Windows 请用 scripts/windows/run-engine.ps1" >&2
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "未找到系统 Chrome: $CHROME" >&2
  echo "请安装 Google Chrome，或设置 ANTIBOT_BROWSER_CHANNEL= 使用 Playwright Chromium。" >&2
  exit 1
fi
echo "Chrome: $("$CHROME" --version 2>/dev/null || true)"

if lsof -iTCP:"${SIDECAR_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "端口 ${SIDECAR_PORT} 已被占用:" >&2
  lsof -iTCP:"${SIDECAR_PORT}" -sTCP:LISTEN -P -n 2>/dev/null || true
  echo "请先停止占用进程，或 SIDECAR_PORT=18001 $0" >&2
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
  echo "创建 Python 虚拟环境 (.venv)..."
  "$PYTHON" -m venv .venv
  need_recreate_venv=true
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ "$need_recreate_venv" == true ]]; then
  pip install -U pip setuptools wheel
  pip install -r requirements.txt
  echo "安装 Playwright Chromium（首次较慢）..."
  python -m playwright install chromium
fi

mkdir -p "$STORAGE_DIR" "$STORAGE_DIR/douyin/profile"
# PC 客户端传入 STORAGE_DIR 时，与安装包一致使用用户目录下的 .env.sidecar（含已保存的 API Key）
ENV_SIDECAR="${STORAGE_DIR}/.env.sidecar"
if [[ ! -f "$ENV_SIDECAR" ]]; then
  ENV_SIDECAR="$ROOT/.env.sidecar"
  if [[ ! -f "$ENV_SIDECAR" ]]; then
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
    echo "已生成 $ENV_SIDECAR"
  fi
fi
export HUOKE_ENV_SIDECAR_PATH="$ENV_SIDECAR"

# 加载 bridge secret 等；下方 export 仍覆盖 Docker .env 中的 DATABASE_URL / STORAGE_ROOT
set -a
# shellcheck disable=SC1090
source "$ENV_SIDECAR"
set +a

# 父 shell 若 export 了空 HUOKE_BRIDGE_SECRET，会盖掉 .env.sidecar；Sidecar dev 强制回落
if [[ -z "${HUOKE_BRIDGE_SECRET//[[:space:]]/}" ]]; then
  export HUOKE_BRIDGE_SECRET=dev-bridge-secret
fi

# 覆盖 projects/huoke/.env 中 Docker 路径（/app/...），Sidecar dev 使用本机 SQLite
export DATABASE_URL="sqlite+pysqlite:///${STORAGE_DIR}/huoke_sidecar.db"
export STORAGE_ROOT="$STORAGE_DIR"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"
export DOUYIN_HEADLESS=false
export XHS_HEADLESS=false
export ANTIBOT_BROWSER_CHANNEL=chrome
export PYTHONPATH="$BACKEND_DIR"

echo ""
echo "启动 Huoke Sidecar: http://127.0.0.1:${SIDECAR_PORT}"
echo "健康检查: curl -sS http://127.0.0.1:${SIDECAR_PORT}/api/health"
echo "API 文档: http://127.0.0.1:${SIDECAR_PORT}/docs"
echo "有头浏览器扫码需保持本终端运行；Ctrl+C 停止。"
echo ""

exec uvicorn app.main:app --host 127.0.0.1 --port "${SIDECAR_PORT}"
