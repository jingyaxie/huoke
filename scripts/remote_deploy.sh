#!/usr/bin/env bash
# 在服务器上执行：Docker 构建 + 启动 + Nginx（由 deploy_backend_prod.sh 调用）
set -euo pipefail

PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
SKIP_BUILD="${SKIP_BUILD:-1}"
BUILD_FRONTEND="${BUILD_FRONTEND:-1}"
SETUP_NGINX="${SETUP_NGINX:-1}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"

cd "$PROD_ROOT"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml -p "$PROD_PROJECT_NAME")

mkdir -p storage reports mysql/data

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "--- docker build backend（服务器上构建）---"
  "${COMPOSE[@]}" build backend
else
  echo "--- 跳过 backend 镜像构建 ---"
fi

echo "--- 启动 mysql + backend ---"
"${COMPOSE[@]}" up -d mysql
"${COMPOSE[@]}" up -d --no-deps backend

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
  echo "--- docker build frontend_prod（服务器上构建）---"
  "${COMPOSE[@]}" --profile prod build frontend_prod
  "${COMPOSE[@]}" --profile prod up -d --no-deps frontend_prod
fi

if [[ "$SETUP_NGINX" == "1" ]]; then
  echo "--- 配置宿主机 Nginx ---"
  bash "$PROD_ROOT/scripts/setup_host_nginx.sh"
fi

echo "--- containers ---"
"${COMPOSE[@]}" ps
if [[ "$BUILD_FRONTEND" == "1" ]]; then
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
