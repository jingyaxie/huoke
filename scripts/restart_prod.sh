#!/usr/bin/env bash
# 仅重启生产 backend + frontend_prod（不 rsync、不 build）
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/load_deploy_env.sh
source "$ROOT_DIR/scripts/lib/load_deploy_env.sh"

PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
BACKEND_IMAGE="${BACKEND_IMAGE:-douyin-backend-app:latest}"

echo "Restart target: $PROD_HOST"
echo "Remote: $PROD_ROOT (project $PROD_PROJECT_NAME)"

prod_ssh "set -e
cd '$PROD_ROOT'
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml -p '$PROD_PROJECT_NAME')
if ! docker image inspect '$BACKEND_IMAGE' >/dev/null 2>&1; then
  echo 'ERROR: 缺少镜像 $BACKEND_IMAGE' >&2
  exit 1
fi
echo '--- force-recreate backend ---'
\"\${COMPOSE[@]}\" up -d --no-build --no-deps --force-recreate backend
echo '--- force-recreate frontend_prod ---'
\"\${COMPOSE[@]}\" --profile prod up -d --no-build --no-deps --force-recreate frontend_prod
\"\${COMPOSE[@]}\" ps
"

echo "Restart finished."
