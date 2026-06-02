#!/usr/bin/env bash
# 快速发布：不上传后重建镜像，适合只改了 backend/app 或 frontend 源码
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/scripts/deploy_backend_prod.sh" --fast "$@"
