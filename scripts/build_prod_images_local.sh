#!/usr/bin/env bash
# 在本地（Mac）构建 linux/amd64 生产镜像，避免在服务器上慢速 apt/pip/playwright
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/docker_images.sh
source "$ROOT_DIR/scripts/lib/docker_images.sh"

usage() {
  cat <<'EOF'
用法: ./scripts/build_prod_images_local.sh [backend|frontend|all]

在本地构建生产镜像（默认 linux/amd64，适配云服务器）：
  - douyin-backend-app:latest      （含 Playwright / VNC 依赖）
  - huoke-frontend-prod:latest     （前端静态页 + nginx）

环境变量:
  IMAGE_PLATFORM=linux/amd64   目标架构
  BACKEND_IMAGE / FRONTEND_PROD_IMAGE   镜像名

示例:
  ./scripts/build_prod_images_local.sh
  ./scripts/build_prod_images_local.sh backend
EOF
}

TARGET="${1:-all}"
case "$TARGET" in
  -h|--help)
    usage
    exit 0
    ;;
  backend|frontend|all) ;;
  *)
    echo "未知目标: $TARGET" >&2
    usage >&2
    exit 2
    ;;
esac

build_prod_images_local "$TARGET"
echo "本地镜像构建完成。"
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' \
  | grep -E '^(REPOSITORY|douyin-backend-app|huoke-frontend-prod)' || true
