#!/usr/bin/env bash
# 将本地已构建的生产镜像推送到服务器（docker save | ssh docker load）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/load_deploy_env.sh
source "$ROOT_DIR/scripts/lib/load_deploy_env.sh"
# shellcheck source=lib/docker_images.sh
source "$ROOT_DIR/scripts/lib/docker_images.sh"

usage() {
  cat <<'EOF'
用法: ./scripts/push_prod_images.sh [backend|backend-base|backend-app|frontend|all]

将本地镜像上传到生产服务器（需先 build_prod_images_local.sh）。
默认对比服务器镜像 ID，相同则跳过上传。

环境变量:
  PROD_SSH_HOST / PROD_SSH_KEY   见 .env.deploy.local
  PUSH_BACKEND_BASE=0|1          上传 backend 时是否包含依赖层（默认 1）
  IMAGE_COMPRESS_LEVEL=1         gzip 压缩级别（1 较快，9 更小）

示例:
  ./scripts/push_prod_images.sh
  ./scripts/push_prod_images.sh backend
EOF
}

TARGET="${1:-all}"
case "$TARGET" in
  -h|--help)
    usage
    exit 0
    ;;
  backend|backend-base|backend-app|frontend|all) ;;
  *)
    echo "未知目标: $TARGET" >&2
    usage >&2
    exit 2
    ;;
esac

echo "Push target: $PROD_HOST"
push_prod_images_to_server "$TARGET"
echo "镜像上传完成。"
