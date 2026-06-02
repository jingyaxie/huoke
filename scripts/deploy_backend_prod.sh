#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/load_deploy_env.sh
source "$ROOT_DIR/scripts/lib/load_deploy_env.sh"
# shellcheck source=lib/deploy_build_detect.sh
source "$ROOT_DIR/scripts/lib/deploy_build_detect.sh"

usage() {
  cat <<'EOF'
用法: ./scripts/deploy_backend_prod.sh [选项] [PROD_HOST]

发布 huoke 到生产服务器（默认自动判断是否重建 Docker 镜像）。

选项:
  --fast, fast    快速发布：上传代码并重启，不执行 docker build（约 1–3 分钟）
  --full, full    全量发布：重建 backend 镜像（apt/pip/playwright，约 10–30 分钟）
  --auto, auto    自动判断（默认）：仅当 Dockerfile/requirements 等变更时才 build
  -h, --help      显示帮助

环境变量（兼容旧用法）:
  SKIP_BUILD=1    等同 --fast
  SKIP_BUILD=0    等同 --full

示例:
  ./scripts/deploy_backend_prod.sh              # 自动
  ./scripts/deploy_backend_prod.sh --fast       # 只改 Python/Vue 时用
  ./scripts/deploy_backend_prod.sh --full       # 改了依赖或 Dockerfile 时用
EOF
}

DEPLOY_MODE="auto"
PROD_HOST_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast|fast) DEPLOY_MODE="fast" ;;
    --full|full) DEPLOY_MODE="full" ;;
    --auto|auto) DEPLOY_MODE="auto" ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "未知选项: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      PROD_HOST_ARG="$1"
      ;;
  esac
  shift
done

PROD_HOST="${PROD_HOST_ARG:-$PROD_HOST}"
PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
REMOTE_TMP="${REMOTE_TMP:-/tmp/huoke-deploy.tgz}"
LOCAL_TMP="${LOCAL_TMP:-/tmp/huoke-deploy.tgz}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
VNC_PORT="${VNC_PORT:-6080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_PROD_PORT="${FRONTEND_PROD_PORT:-5174}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
BUILD_FRONTEND="${BUILD_FRONTEND:-0}"

NEED_BUILD="$(deploy_needs_image_build "$DEPLOY_MODE")"
if [[ "$NEED_BUILD" == "1" ]]; then
  SKIP_BUILD=0
  DID_BUILD=1
else
  SKIP_BUILD=1
  DID_BUILD=0
fi

echo "Deploy target: $PROD_HOST"
echo "Remote root: $PROD_ROOT"
echo "Compose project: $PROD_PROJECT_NAME"
echo "Health URL: $HEALTH_URL"
echo "Deploy mode: $DEPLOY_MODE → SKIP_BUILD=$SKIP_BUILD"

cd "$ROOT_DIR"

export COPYFILE_DISABLE=1
tar -czf "$LOCAL_TMP" \
  --exclude="._*" \
  --exclude="**/._*" \
  --exclude=".DS_Store" \
  --exclude="**/.DS_Store" \
  --exclude=".git" \
  --exclude=".venv" \
  --exclude=".env.deploy.local" \
  --exclude="frontend/node_modules" \
  --exclude="frontend/dist" \
  --exclude="mysql/data" \
  --exclude="storage" \
  --exclude="reports" \
  --exclude="scripts/.deploy-state" \
  .

prod_ssh "mkdir -p '$PROD_ROOT'"
prod_scp "$LOCAL_TMP" "$PROD_HOST:$REMOTE_TMP"

REMOTE_CMD=$(cat <<'EOF'
set -euo pipefail
mkdir -p "$PROD_ROOT"
tar -xzf "$REMOTE_TMP" -C "$PROD_ROOT"
find "$PROD_ROOT" -name '._*' -type f -delete || true
find "$PROD_ROOT" -name '.DS_Store' -type f -delete || true
cd "$PROD_ROOT"

if [ "$SKIP_BUILD" != "1" ]; then
  echo "--- docker build backend (全量，含系统依赖与 Playwright) ---"
  docker compose -p "$PROD_PROJECT_NAME" build backend
else
  echo "--- 跳过 docker build（代码经 volume 挂载，重启即生效）---"
fi

docker compose -p "$PROD_PROJECT_NAME" up -d mysql
docker compose -p "$PROD_PROJECT_NAME" up -d --no-deps backend

echo "--- 等待 backend 启动（字体/MySQL/迁移）---"
ok=0
for i in $(seq 1 45); do
  if curl -sS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [ "$BUILD_FRONTEND" = "1" ]; then
  echo "--- docker build frontend_prod ---"
  docker compose -p "$PROD_PROJECT_NAME" --profile prod up -d --build frontend_prod
fi

echo "--- containers ---"
docker compose -p "$PROD_PROJECT_NAME" ps backend

echo "--- health ---"
if [ "$ok" != "1" ]; then
  for i in $(seq 1 10); do
    if curl -sS -m 8 "$HEALTH_URL"; then
      echo
      ok=1
      break
    fi
    sleep 2
  done
fi
if [ "$ok" != "1" ]; then
  echo "health check failed: $HEALTH_URL" >&2
  docker compose -p "$PROD_PROJECT_NAME" logs backend --tail 40 >&2 || true
  exit 56
fi
EOF
)

prod_ssh "export PROD_ROOT='$PROD_ROOT' PROD_PROJECT_NAME='$PROD_PROJECT_NAME' REMOTE_TMP='$REMOTE_TMP' HEALTH_URL='$HEALTH_URL' SKIP_BUILD='$SKIP_BUILD' BUILD_FRONTEND='$BUILD_FRONTEND' BACKEND_PORT='$BACKEND_PORT' VNC_PORT='$VNC_PORT' FRONTEND_PORT='$FRONTEND_PORT' FRONTEND_PROD_PORT='$FRONTEND_PROD_PORT' MYSQL_PORT='$MYSQL_PORT'; bash -lc '$REMOTE_CMD'"

rm -f "$LOCAL_TMP"
deploy_record_success "$DID_BUILD"
echo "Deploy finished."
