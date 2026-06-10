#!/usr/bin/env bash
# 在服务器上安装/更新宿主机 Nginx（由 deploy 脚本 rsync 上传后调用）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NGINX_CONF_SRC="${NGINX_CONF_SRC:-$ROOT_DIR/docker/nginx/huoke.conf}"
NGINX_CONF_DEST="${NGINX_CONF_DEST:-/etc/nginx/conf.d/huoke.conf}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"

if [[ ! -f "$NGINX_CONF_SRC" ]]; then
  echo "nginx config not found: $NGINX_CONF_SRC" >&2
  exit 1
fi

if ! command -v nginx >/dev/null 2>&1; then
  echo "--- installing nginx ---"
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y nginx
  elif command -v yum >/dev/null 2>&1; then
    yum install -y nginx
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y nginx
  else
    echo "unsupported package manager, install nginx manually" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$NGINX_CONF_DEST")"
if [[ "$NGINX_SERVER_NAME" != "_" && -n "$NGINX_SERVER_NAME" ]]; then
  sed "s/server_name _;/server_name ${NGINX_SERVER_NAME};/" "$NGINX_CONF_SRC" > "$NGINX_CONF_DEST"
else
  cp "$NGINX_CONF_SRC" "$NGINX_CONF_DEST"
fi

nginx -t
systemctl enable nginx
systemctl restart nginx
echo "nginx ready: $NGINX_CONF_DEST"
