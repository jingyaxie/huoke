#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/load_deploy_env.sh
source "$ROOT_DIR/scripts/lib/load_deploy_env.sh"

PROD_HOST="${1:-$PROD_HOST}"
PROD_ROOT="${PROD_ROOT:-/root/workspace/huoke}"
PROD_PROJECT_NAME="${PROD_PROJECT_NAME:-huoke}"
REMOTE_TMP="${REMOTE_TMP:-/tmp/huoke-deploy.tgz}"
LOCAL_TMP="${LOCAL_TMP:-/tmp/huoke-deploy.tgz}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
SKIP_BUILD="${SKIP_BUILD:-0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
VNC_PORT="${VNC_PORT:-6080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_PROD_PORT="${FRONTEND_PROD_PORT:-5174}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

echo "Deploy target: $PROD_HOST"
echo "Remote root: $PROD_ROOT"
echo "Compose project: $PROD_PROJECT_NAME"
echo "Health URL: $HEALTH_URL"

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
  docker compose -p "$PROD_PROJECT_NAME" build backend
fi

docker compose -p "$PROD_PROJECT_NAME" up -d mysql
docker compose -p "$PROD_PROJECT_NAME" up -d --no-deps backend

echo "--- containers ---"
docker compose -p "$PROD_PROJECT_NAME" ps backend

echo "--- health ---"
ok=0
for i in $(seq 1 20); do
  if curl -sS -m 8 "$HEALTH_URL"; then
    echo
    ok=1
    break
  fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "health check failed: $HEALTH_URL" >&2
  exit 56
fi
EOF
)

prod_ssh "export PROD_ROOT='$PROD_ROOT' PROD_PROJECT_NAME='$PROD_PROJECT_NAME' REMOTE_TMP='$REMOTE_TMP' HEALTH_URL='$HEALTH_URL' SKIP_BUILD='$SKIP_BUILD' BACKEND_PORT='$BACKEND_PORT' VNC_PORT='$VNC_PORT' FRONTEND_PORT='$FRONTEND_PORT' FRONTEND_PROD_PORT='$FRONTEND_PROD_PORT' MYSQL_PORT='$MYSQL_PORT'; bash -lc '$REMOTE_CMD'"

rm -f "$LOCAL_TMP"
echo "Deploy finished."
