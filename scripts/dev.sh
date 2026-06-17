#!/usr/bin/env bash
# 本地开发一键启动：后端 (8000) + Vite 前端 (5173)
# 用法: bash scripts/dev.sh
# 停止: bash scripts/dev.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/dev-common.sh
source "$ROOT/scripts/dev-common.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${ROOT}/storage/dev"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID="${LOG_DIR}/backend.pid"
FRONTEND_PID="${LOG_DIR}/frontend.pid"

mkdir -p "$LOG_DIR"

stop_all() {
  for pf in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [[ -f "$pf" ]]; then
      pid="$(cat "$pf" 2>/dev/null || true)"
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "已停止 PID ${pid} ($(basename "$pf" .pid))"
      fi
      rm -f "$pf"
    fi
  done
}

if [[ "${1:-}" == "--stop" ]]; then
  stop_all
  exit 0
fi

echo "=== Huoke 本地开发 ==="

if dev_port_listen "$BACKEND_PORT"; then
  echo "  · 后端已在端口 ${BACKEND_PORT}"
else
  echo "  · 启动后端..."
  nohup env BACKEND_PORT="$BACKEND_PORT" bash "$ROOT/scripts/dev-native.sh" >>"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID"
  dev_wait_health "http://127.0.0.1:${BACKEND_PORT}/api/health" "后端" "$BACKEND_LOG"
fi

if dev_port_listen "$FRONTEND_PORT"; then
  echo "  · 前端已在端口 ${FRONTEND_PORT}"
else
  echo "  · 启动前端..."
  (
    cd "$ROOT/frontend"
    nohup npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1
  ) &
  echo $! >"$FRONTEND_PID"
  for _ in $(seq 1 45); do
    if dev_port_listen "$FRONTEND_PORT"; then
      echo "  ✓ 前端就绪"
      break
    fi
    sleep 1
  done
fi

echo ""
echo "前端:     http://127.0.0.1:${FRONTEND_PORT}/"
echo "API 文档: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "日志:     ${LOG_DIR}/"
echo "停止:     bash scripts/dev.sh --stop"
