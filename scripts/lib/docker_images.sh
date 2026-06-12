#!/usr/bin/env bash
# 本地构建生产镜像并推送到服务器（供 deploy 脚本 source）

BACKEND_BASE_IMAGE="${BACKEND_BASE_IMAGE:-douyin-backend-base:py312}"
BACKEND_IMAGE="${BACKEND_IMAGE:-douyin-backend-app:latest}"
FRONTEND_PROD_IMAGE="${FRONTEND_PROD_IMAGE:-huoke-frontend-prod:latest}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
IMAGE_COMPRESS_LEVEL="${IMAGE_COMPRESS_LEVEL:-1}"
BUILDX_CACHE_DIR="${BUILDX_CACHE_DIR:-}"

docker_images_repo_root() {
  local here="${BASH_SOURCE[0]}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/../.." && pwd
}

_buildx_cache_dir() {
  if [[ -n "$BUILDX_CACHE_DIR" ]]; then
    echo "$BUILDX_CACHE_DIR"
    return
  fi
  echo "$(docker_images_repo_root)/.docker-build-cache"
}

_buildx_cache_args() {
  local cache_dir
  cache_dir="$(_buildx_cache_dir)"
  mkdir -p "$cache_dir"
  printf '%s\n' \
    "--cache-from=type=local,src=$cache_dir" \
    "--cache-to=type=local,dest=$cache_dir,mode=max"
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

_buildx_build() {
  local platform="$1"
  shift
  ensure_docker_buildx
  local -a cache_args=()
  while IFS= read -r line; do
    cache_args+=("$line")
  done < <(_buildx_cache_args)
  docker buildx build \
    --platform "$platform" \
    "${cache_args[@]}" \
    "$@"
}

_image_matches_platform() {
  local image="${1:?}"
  local platform="${2:-$IMAGE_PLATFORM}"
  local arch os
  arch="$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || echo "")"
  os="$(docker image inspect "$image" --format '{{.Os}}' 2>/dev/null || echo "")"
  [[ -n "$arch" && -n "$os" ]] || return 1
  case "$platform" in
    linux/amd64) [[ "$os" == "linux" && "$arch" == "amd64" ]] ;;
    linux/arm64) [[ "$os" == "linux" && "$arch" == "arm64" ]] ;;
    *) return 0 ;;
  esac
}

ensure_backend_base_image_local() {
  if docker image inspect "$BACKEND_BASE_IMAGE" >/dev/null 2>&1 \
    && _image_matches_platform "$BACKEND_BASE_IMAGE"; then
    return 0
  fi
  if docker image inspect "$BACKEND_BASE_IMAGE" >/dev/null 2>&1; then
    echo "本地 $BACKEND_BASE_IMAGE 架构与 $IMAGE_PLATFORM 不符，重建依赖层..." >&2
  else
    echo "本地不存在 $BACKEND_BASE_IMAGE，先构建依赖层..." >&2
  fi
  build_backend_base_image_local
}

build_backend_base_image_local() {
  local root
  root="$(docker_images_repo_root)"
  echo "--- 本地构建 backend 依赖层 ${BACKEND_BASE_IMAGE} (${IMAGE_PLATFORM}) ---"
  _buildx_build "$IMAGE_PLATFORM" \
    -f "$root/backend/Dockerfile" \
    --target backend-base \
    -t "$BACKEND_BASE_IMAGE" \
    --load \
    "$root/backend"
}

build_backend_app_image_local() {
  local root
  root="$(docker_images_repo_root)"
  ensure_backend_base_image_local
  echo "--- 本地构建 backend 业务层 ${BACKEND_IMAGE} ---"
  # 普通 docker build 才能 FROM 本地已 load 的 base；buildx container 会去 Hub 拉同名镜像
  docker build \
    --platform "$IMAGE_PLATFORM" \
    -f "$root/backend/Dockerfile.app" \
    --build-arg "BASE_IMAGE=$BACKEND_BASE_IMAGE" \
    -t "$BACKEND_IMAGE" \
    "$root/backend"
}

build_backend_image_local() {
  build_backend_base_image_local
  build_backend_app_image_local
}

build_frontend_prod_image_local() {
  local root
  root="$(docker_images_repo_root)"
  echo "--- 本地构建 frontend_prod 镜像 (${IMAGE_PLATFORM}) ---"
  _buildx_build "$IMAGE_PLATFORM" \
    -f "$root/frontend/Dockerfile" \
    --build-arg VITE_API_BASE_URL=/api \
    -t "$FRONTEND_PROD_IMAGE" \
    --load \
    "$root/frontend"
}

_image_id() {
  docker image inspect "$1" --format '{{.Id}}' 2>/dev/null || true
}

remote_image_id() {
  local image="${1:?}"
  prod_ssh "docker image inspect '$image' --format '{{.Id}}' 2>/dev/null" 2>/dev/null || true
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

push_docker_image_if_changed() {
  local image="${1:?image required}"
  local local_id remote_id
  local_id="$(_image_id "$image")"
  if [[ -z "$local_id" ]]; then
    echo "本地不存在镜像: $image" >&2
    return 1
  fi
  remote_id="$(remote_image_id "$image")"
  if [[ -n "$remote_id" && "$local_id" == "$remote_id" ]]; then
    echo "跳过上传 $image（服务器镜像 ID 一致）"
    return 0
  fi
  push_docker_image_to_prod "$image"
}

push_prod_images_to_server() {
  local which="${1:-all}"
  local push_base="${PUSH_BACKEND_BASE:-1}"
  case "$which" in
    backend)
      if [[ "$push_base" == "1" ]]; then
        push_docker_image_if_changed "$BACKEND_BASE_IMAGE"
      fi
      push_docker_image_if_changed "$BACKEND_IMAGE"
      ;;
    backend-app)
      push_docker_image_if_changed "$BACKEND_IMAGE"
      ;;
    backend-base)
      push_docker_image_if_changed "$BACKEND_BASE_IMAGE"
      ;;
    frontend)
      push_docker_image_if_changed "$FRONTEND_PROD_IMAGE"
      ;;
    all)
      if [[ "$push_base" == "1" ]]; then
        push_docker_image_if_changed "$BACKEND_BASE_IMAGE"
      fi
      push_docker_image_if_changed "$BACKEND_IMAGE"
      push_docker_image_if_changed "$FRONTEND_PROD_IMAGE"
      ;;
    *)
      echo "未知镜像目标: $which（backend|backend-app|backend-base|frontend|all）" >&2
      return 2
      ;;
  esac
}

build_prod_images_local() {
  local which="${1:-all}"
  local build_base="${BUILD_BACKEND_BASE:-1}"
  case "$which" in
    backend)
      if [[ "$build_base" == "1" ]]; then
        build_backend_base_image_local
      else
        ensure_backend_base_image_local
      fi
      build_backend_app_image_local
      ;;
    backend-app)
      build_backend_app_image_local
      ;;
    backend-base)
      build_backend_base_image_local
      ;;
    frontend) build_frontend_prod_image_local ;;
    all)
      if [[ "$build_base" == "1" ]]; then
        build_backend_base_image_local
      else
        ensure_backend_base_image_local
      fi
      build_backend_app_image_local
      build_frontend_prod_image_local
      ;;
    *)
      echo "未知构建目标: $which（backend|backend-app|backend-base|frontend|all）" >&2
      return 2
      ;;
  esac
}
