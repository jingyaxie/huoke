#!/usr/bin/env bash
# 全量发布：强制重建 backend 镜像（Dockerfile / requirements / Playwright 变更后使用）
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/scripts/deploy_backend_prod.sh" --full "$@"
