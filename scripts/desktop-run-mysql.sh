#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/desktop-common.sh
source "$ROOT/scripts/desktop-common.sh"
HUOKE_ROOT="$ROOT"
ensure_desktop_path

DATA_DIR="$(resolve_huoke_data_dir)"
MYSQL_DATA="$DATA_DIR/mysql"
STORAGE_DIR="$DATA_DIR/storage"
mkdir -p "$MYSQL_DATA" "$STORAGE_DIR" "$DATA_DIR/logs"

LOG_FILE="$DATA_DIR/logs/desktop-mysql.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date '+%F %T')] desktop-run-mysql root=$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker，请先安装并启动 Docker Desktop。" >&2
  exit 1
fi

export HUOKE_MYSQL_DATA="$MYSQL_DATA"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-huoke-desktop}"
INIT_SQL="$ROOT/backend/sql/init.sql"
if [[ ! -f "$INIT_SQL" ]]; then
  INIT_SQL="$ROOT/sql/init.sql"
fi
export HUOKE_INIT_SQL="$INIT_SQL"

if docker inspect huoke_desktop_mysql >/dev/null 2>&1; then
  echo "复用已有 MySQL 容器 huoke_desktop_mysql"
  docker start huoke_desktop_mysql >/dev/null
else
  cd "$ROOT"
  docker compose -f docker-compose.desktop.yml up -d mysql
fi

echo "等待 MySQL 就绪..."
for _ in $(seq 1 60); do
  if docker exec huoke_desktop_mysql \
    mysqladmin ping -h localhost -udouyin -pdouyin --silent 2>/dev/null; then
    echo "MySQL 已就绪"
    exit 0
  fi
  sleep 1
done

echo "MySQL 启动超时，日志: $LOG_FILE" >&2
exit 1
