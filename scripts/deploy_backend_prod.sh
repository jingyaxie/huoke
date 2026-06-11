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

发布 huoke 到生产服务器：
  1. rsync 上传源码到服务器
  2. docker compose up（镜像可在本地构建后上传，或在服务器构建）
  3. 配置宿主机 Nginx 对外提供 API / 前端访问

选项:
  --local-images  推荐：本地构建镜像并上传，服务器只启动（避免服务器慢速打包）
  --fast, fast    快速发布：上传代码并重启，不执行 docker build（约 1–3 分钟）
  --full, full    全量发布：在服务器重建 backend 镜像（约 10–30 分钟）
  --auto, auto    自动判断（默认）：仅当 Dockerfile/requirements 等变更时才 build
  -h, --help      显示帮助

环境变量:
  SKIP_BUILD=1         等同 --fast
  SKIP_BUILD=0         等同 --full
  BUILD_FRONTEND=1     在服务器构建 frontend_prod（默认 1；--local-images 时为 0）
  SETUP_NGINX=1        安装/更新宿主机 Nginx（默认 1）
  NGINX_SERVER_NAME    Nginx server_name（默认 _，匹配 IP 访问）
  IMAGE_PUSH_TARGET    --local-images 时上传哪些镜像：all|backend|frontend

示例:
  ./scripts/deploy_local_images.sh
  ./scripts/deploy_backend_prod.sh --local-images
  ./scripts/deploy_backend_prod.sh --fast
  ./scripts/deploy_backend_prod.sh --full
EOF
}

DEPLOY_MODE="auto"
LOCAL_IMAGES=0
IMAGE_PUSH_TARGET="${IMAGE_PUSH_TARGET:-all}"
PROD_HOST_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-images|local-images) LOCAL_IMAGES=1; DEPLOY_MODE="fast" ;;
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

PROD_HOST="${PROD_HOST_ARG:-${PROD_HOST:-}}"
PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
VNC_PORT="${VNC_PORT:-6080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_PROD_PORT="${FRONTEND_PROD_PORT:-5174}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
BUILD_FRONTEND="${BUILD_FRONTEND:-1}"
SETUP_NGINX="${SETUP_NGINX:-1}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"

if [[ "$LOCAL_IMAGES" == "1" ]]; then
  SKIP_BUILD=1
  BUILD_FRONTEND=0
  UP_FRONTEND_PROD=1
  DID_BUILD=1
else
  NEED_BUILD="$(deploy_needs_image_build "$DEPLOY_MODE")"
  if [[ "$NEED_BUILD" == "1" ]]; then
    SKIP_BUILD=0
    DID_BUILD=1
  else
    SKIP_BUILD=1
    DID_BUILD=0
  fi
  UP_FRONTEND_PROD="${UP_FRONTEND_PROD:-$BUILD_FRONTEND}"
fi

echo "Deploy target: $PROD_HOST"
echo "Remote root: $PROD_ROOT"
echo "Compose project: $PROD_PROJECT_NAME"
echo "Health URL: $HEALTH_URL"
if [[ "$LOCAL_IMAGES" == "1" ]]; then
  echo "Deploy mode: local-images（本地构建并上传镜像，服务器仅启动）"
else
  echo "Deploy mode: $DEPLOY_MODE → SKIP_BUILD=$SKIP_BUILD"
fi
echo "BUILD_FRONTEND=$BUILD_FRONTEND UP_FRONTEND_PROD=${UP_FRONTEND_PROD:-0} SETUP_NGINX=$SETUP_NGINX"

cd "$ROOT_DIR"

if [[ "$LOCAL_IMAGES" == "1" ]]; then
  # shellcheck source=lib/docker_images.sh
  source "$ROOT_DIR/scripts/lib/docker_images.sh"
  build_prod_images_local "$IMAGE_PUSH_TARGET"
  push_prod_images_to_server "$IMAGE_PUSH_TARGET"
fi

echo "--- rsync 上传源码到服务器 ---"
prod_rsync "$ROOT_DIR/"

prod_ssh "chmod +x '$PROD_ROOT/scripts/remote_deploy.sh' '$PROD_ROOT/scripts/setup_host_nginx.sh' '$PROD_ROOT/scripts/build_prod_images_local.sh' '$PROD_ROOT/scripts/push_prod_images.sh' '$PROD_ROOT/scripts/deploy_local_images.sh' 2>/dev/null || true"

prod_ssh "export PROD_ROOT='$PROD_ROOT' PROD_PROJECT_NAME='$PROD_PROJECT_NAME' HEALTH_URL='$HEALTH_URL' SKIP_BUILD='$SKIP_BUILD' BUILD_FRONTEND='$BUILD_FRONTEND' UP_FRONTEND_PROD='${UP_FRONTEND_PROD:-0}' SETUP_NGINX='$SETUP_NGINX' NGINX_SERVER_NAME='$NGINX_SERVER_NAME' BACKEND_PORT='$BACKEND_PORT' VNC_PORT='$VNC_PORT' FRONTEND_PORT='$FRONTEND_PORT' FRONTEND_PROD_PORT='$FRONTEND_PROD_PORT' MYSQL_PORT='$MYSQL_PORT'; bash '$PROD_ROOT/scripts/remote_deploy.sh'"

deploy_record_success "$DID_BUILD"
echo "Deploy finished."
echo "访问: http://${PROD_SSH_HOST:-$PROD_HOST}/  （前端）"
echo "API:  http://${PROD_SSH_HOST:-$PROD_HOST}/api/health"
echo "文档: http://${PROD_SSH_HOST:-$PROD_HOST}/docs"
