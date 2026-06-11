#!/usr/bin/env bash
# 本地构建生产镜像并推送到服务器（供 deploy 脚本 source）

BACKEND_IMAGE="${BACKEND_IMAGE:-douyin-backend-app:latest}"
FRONTEND_PROD_IMAGE="${FRONTEND_PROD_IMAGE:-huoke-frontend-prod:latest}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
IMAGE_COMPRESS_LEVEL="${IMAGE_COMPRESS_LEVEL:-1}"

docker_images_repo_root() {
  local here="${BASH_SOURCE[0]}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/../.." && pwd
}

ensure_docker_buildx() {
  if ! docker buildx version >/dev/null 2>&1; then
    echo "需要 Docker Buildx（Docker Desktop 一般已自带）" >&2
    return 1
  fi
  if ! docker buildx inspect huoke-builder >/dev/null 2>&1; then
    docker buildx create --name huoke-builder --driver docker-container --use >/dev/null
  else
    docker buildx use huoke-builder >/dev/null
  fi
}

build_backend_image_local() {
  local root
  root="$(docker_images_repo_root)"
  echo "--- 本地构建 backend 镜像 (${IMAGE_PLATFORM}) ---"
  ensure_docker_buildx
  docker buildx build \
    --platform "$IMAGE_PLATFORM" \
    -f "$root/backend/Dockerfile" \
    --target backend-app \
    -t "$BACKEND_IMAGE" \
    --load \
    "$root/backend"
}

build_frontend_prod_image_local() {
  local root
  root="$(docker_images_repo_root)"
  echo "--- 本地构建 frontend_prod 镜像 (${IMAGE_PLATFORM}) ---"
  ensure_docker_buildx
  docker buildx build \
    --platform "$IMAGE_PLATFORM" \
    -f "$root/frontend/Dockerfile" \
    --build-arg VITE_API_BASE_URL=/api \
    -t "$FRONTEND_PROD_IMAGE" \
    --load \
    "$root/frontend"
}

push_docker_image_to_prod() {
  local image="${1:?image required}"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "本地不存在镜像: $image" >&2
    return 1
  fi
  local size size_label
  size="$(docker image inspect "$image" --format '{{.Size}}' 2>/dev/null || echo 0)"
  if command -v numfmt >/dev/null 2>&1; then
    size_label="$(numfmt --to=iec "$size" 2>/dev/null || echo "${size}B")"
  else
    size_label="${size}B"
  fi
  echo "--- 上传镜像 $image (${size_label}) ---"
  # shellcheck disable=SC2016
  docker save "$image" | gzip "-${IMAGE_COMPRESS_LEVEL}" | prod_ssh 'gunzip | docker load'
  echo "已加载到服务器: $image"
}

push_prod_images_to_server() {
  local which="${1:-all}"
  case "$which" in
    backend)
      push_docker_image_to_prod "$BACKEND_IMAGE"
      ;;
    frontend)
      push_docker_image_to_prod "$FRONTEND_PROD_IMAGE"
      ;;
    all)
      push_docker_image_to_prod "$BACKEND_IMAGE"
      push_docker_image_to_prod "$FRONTEND_PROD_IMAGE"
      ;;
    *)
      echo "未知镜像目标: $which（backend|frontend|all）" >&2
      return 2
      ;;
  esac
}

build_prod_images_local() {
  local which="${1:-all}"
  case "$which" in
    backend) build_backend_image_local ;;
    frontend) build_frontend_prod_image_local ;;
    all)
      build_backend_image_local
      build_frontend_prod_image_local
      ;;
    *)
      echo "未知构建目标: $which（backend|frontend|all）" >&2
      return 2
      ;;
  esac
}
