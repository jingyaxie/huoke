#!/usr/bin/env bash
# 快速发布：rsync 源码 + 重启容器，不 docker build、不上传镜像
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/scripts/deploy_backend_prod.sh" --fast "$@"
