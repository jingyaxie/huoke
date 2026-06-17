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
  --local-images  可选：本地打镜像并上传（仅依赖变更或首次部署时用）
  --fast, fast    默认推荐：rsync 代码 + 重启，不 build、不上传镜像（约 1–3 分钟）
  --full, full    全量：在服务器重建镜像（改 Dockerfile/requirements 后）
  --auto, auto    自动判断：业务代码 → 同 --fast；依赖变更 → 服务器 build
  -h, --help      显示帮助

环境变量:
  SKIP_BUILD=1         等同 --fast
  SKIP_BUILD=0         等同 --full
  BUILD_FRONTEND=1     在服务器构建 frontend_prod（默认 1；--local-images 时为 0）
  SETUP_NGINX=1        安装/更新宿主机 Nginx（默认 1）
  NGINX_SERVER_NAME    Nginx server_name（默认 _，匹配 IP 访问）
  IMAGE_PUSH_TARGET    --local-images 时上传哪些镜像：all|backend|frontend

示例:
  ./scripts/deploy_fast.sh          # 日常发版（推荐）
  ./scripts/deploy_backend_prod.sh  # 同上，auto 模式
  ./scripts/deploy_local_images.sh  # 仅首次或 requirements 变更后
  ./scripts/deploy_full.sh
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
SETUP_NGINX="${SETUP_NGINX:-1}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
BACKEND_BASE_IMAGE="${BACKEND_BASE_IMAGE:-douyin-backend-base:py312}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"

NEED_BASE=0
NEED_FRONTEND_DIST=0
NEED_FRONTEND_IMAGE=0
if [[ "$LOCAL_IMAGES" == "1" ]]; then
  NEED_BASE="$(deploy_needs_base_rebuild "$DEPLOY_MODE")"
  if ! docker image inspect "$BACKEND_BASE_IMAGE" >/dev/null 2>&1 \
    || ! docker image inspect "$BACKEND_BASE_IMAGE" --format '{{.Architecture}} {{.Os}}' 2>/dev/null | grep -q 'amd64 linux'; then
    echo "本地无匹配 $IMAGE_PLATFORM 的依赖层镜像，将先构建 $BACKEND_BASE_IMAGE" >&2
    NEED_BASE=1
  fi
elif [[ "$DEPLOY_MODE" != "full" ]]; then
  NEED_FRONTEND_DIST="$(deploy_needs_frontend_dist "$DEPLOY_MODE")"
  NEED_FRONTEND_IMAGE="$(deploy_needs_frontend_image "$DEPLOY_MODE")"
fi

if [[ -z "${BUILD_FRONTEND:-}" ]]; then
  if [[ "$DEPLOY_MODE" == "full" ]] || [[ "$NEED_FRONTEND_IMAGE" == "1" ]]; then
    BUILD_FRONTEND=1
  else
    BUILD_FRONTEND=0
  fi
fi

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
  UP_FRONTEND_PROD="${UP_FRONTEND_PROD:-1}"
fi

echo "Deploy target: $PROD_HOST"
echo "Remote root: $PROD_ROOT"
echo "Compose project: $PROD_PROJECT_NAME"
echo "Health URL: $HEALTH_URL"
if [[ "$LOCAL_IMAGES" == "1" ]]; then
  echo "Deploy mode: local-images (NEED_BASE=${NEED_BASE})"
else
  echo "Deploy mode: $DEPLOY_MODE → SKIP_BUILD=$SKIP_BUILD"
  echo "NEED_FRONTEND_DIST=$NEED_FRONTEND_DIST BUILD_FRONTEND=$BUILD_FRONTEND"
fi
echo "BUILD_FRONTEND=$BUILD_FRONTEND UP_FRONTEND_PROD=${UP_FRONTEND_PROD:-0} SETUP_NGINX=$SETUP_NGINX"

cd "$ROOT_DIR"

if [[ "$LOCAL_IMAGES" != "1" && "$NEED_FRONTEND_DIST" == "1" ]]; then
  echo "--- 本地构建前端 dist（同步静态文件，不重建 nginx 镜像）---"
  (cd "$ROOT_DIR/frontend" && npm run build)
  export RSYNC_FRONTEND_DIST=1
fi

if [[ "$LOCAL_IMAGES" == "1" ]]; then
  # shellcheck source=lib/docker_images.sh
  source "$ROOT_DIR/scripts/lib/docker_images.sh"
  BUILD_BACKEND_BASE="$NEED_BASE"
  PUSH_BACKEND_BASE="$NEED_BASE"
  export BUILD_BACKEND_BASE PUSH_BACKEND_BASE
  case "$IMAGE_PUSH_TARGET" in
    backend)
      build_prod_images_local backend
      push_prod_images_to_server backend
      ;;
    frontend)
      build_prod_images_local frontend
      push_prod_images_to_server frontend
      ;;
    all|*)
      build_prod_images_local backend
      push_prod_images_to_server backend
      build_prod_images_local frontend
      push_prod_images_to_server frontend
      ;;
  esac
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
