#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"

"$ROOT/scripts/desktop-run-mysql.sh"

"$ROOT/scripts/desktop-run-backend.sh" &
BACKEND_PID=$!

echo "等待后端就绪 (http://127.0.0.1:${BACKEND_PORT})..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    echo "后端已就绪 (pid=${BACKEND_PID})"
    exit 0
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "后端进程异常退出" >&2
    exit 1
  fi
  sleep 1
done

echo "后端启动超时" >&2
kill "$BACKEND_PID" 2>/dev/null || true
exit 1
