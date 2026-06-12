#!/usr/bin/env bash
# 在服务器上执行：Docker 构建 + 启动 + Nginx（由 deploy_backend_prod.sh 调用）
set -euo pipefail

PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
SKIP_BUILD="${SKIP_BUILD:-1}"
BUILD_FRONTEND="${BUILD_FRONTEND:-1}"
UP_FRONTEND_PROD="${UP_FRONTEND_PROD:-$BUILD_FRONTEND}"
SETUP_NGINX="${SETUP_NGINX:-1}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
BACKEND_IMAGE="${BACKEND_IMAGE:-douyin-backend-app:latest}"

cd "$PROD_ROOT"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml -p "$PROD_PROJECT_NAME")

mkdir -p storage reports mysql/data

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "--- docker build backend（服务器上构建）---"
  "${COMPOSE[@]}" build backend
else
  echo "--- 跳过 backend 镜像构建 ---"
fi

_mysql_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'douyin_mysql'
}

_ensure_mysql() {
  if _mysql_running; then
    echo "--- mysql 已在运行，跳过启动 ---"
    return 0
  fi
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'douyin_mysql'; then
    echo "--- 启动已有 mysql 容器 ---"
    if ! docker start douyin_mysql 2>/dev/null; then
      echo "--- 旧 mysql 端口/配置冲突，重建容器（数据保留在 mysql/data）---"
      docker rm -f douyin_mysql
      "${COMPOSE[@]}" up -d --no-recreate mysql
    fi
    return 0
  fi
  echo "--- 首次创建 mysql ---"
  "${COMPOSE[@]}" up -d --no-recreate mysql
}

if [[ "$SKIP_BUILD" == "1" ]]; then
  _ensure_mysql || echo "WARN: mysql 未启动；若 3306 被占用可忽略（生产 compose 不映射宿主机端口）" >&2
else
  _ensure_mysql
fi

echo "--- 重启 backend ---"
if [[ "$SKIP_BUILD" == "1" ]]; then
  if ! docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
    echo "ERROR: 服务器缺少镜像 $BACKEND_IMAGE，快速发布不会在服务器上构建。" >&2
    echo "请先在本机执行一次: ./scripts/deploy_local_images.sh" >&2
    echo "或在服务器全量构建: ./scripts/deploy_full.sh" >&2
    exit 1
  fi
  "${COMPOSE[@]}" up -d --no-build --no-deps --force-recreate backend
else
  "${COMPOSE[@]}" up -d --no-deps --force-recreate backend
fi

echo "--- 等待 backend 健康 ---"
ok=0
for _ in $(seq 1 45); do
  if curl -sS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$BUILD_FRONTEND" == "1" ]]; then
  echo "--- docker build frontend_prod（仅 package.json / Dockerfile 变更时）---"
  "${COMPOSE[@]}" --profile prod build frontend_prod
else
  echo "--- 跳过 frontend_prod 镜像构建（使用 rsync 的 dist 目录）---"
fi

if [[ "$UP_FRONTEND_PROD" == "1" ]]; then
  echo "--- 启动/重启 frontend_prod ---"
  if [[ "$SKIP_BUILD" == "1" && "$BUILD_FRONTEND" != "1" ]]; then
    "${COMPOSE[@]}" --profile prod up -d --no-build --no-deps frontend_prod
  else
    "${COMPOSE[@]}" --profile prod up -d --no-deps frontend_prod
  fi
fi

if [[ "$SETUP_NGINX" == "1" ]]; then
  echo "--- 配置宿主机 Nginx ---"
  bash "$PROD_ROOT/scripts/setup_host_nginx.sh"
fi

echo "--- containers ---"
"${COMPOSE[@]}" ps
if [[ "$UP_FRONTEND_PROD" == "1" ]]; then
  "${COMPOSE[@]}" --profile prod ps frontend_prod
fi

echo "--- health ---"
if [[ "$ok" != "1" ]]; then
  for _ in $(seq 1 10); do
    if curl -sS -m 8 "$HEALTH_URL"; then
      echo
      ok=1
      break
    fi
    sleep 2
  done
fi

if [[ "$ok" != "1" ]]; then
  echo "health check failed: $HEALTH_URL" >&2
  "${COMPOSE[@]}" logs backend --tail 40 >&2 || true
  exit 56
fi

if [[ "$SETUP_NGINX" == "1" ]]; then
  echo "--- public api ---"
  curl -sS -m 8 "http://127.0.0.1/api/health" || true
  echo
fi

echo "remote deploy done."
