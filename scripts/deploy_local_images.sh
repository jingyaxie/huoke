#!/usr/bin/env bash
# 本地构建镜像 → 上传服务器 → rsync 代码 → 服务器仅 docker compose up（不在服务器 build）
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/scripts/deploy_backend_prod.sh" --local-images "$@"
