#!/usr/bin/env bash
# 无 Docker 一键启动：后端 (8000) + 前端 (5173)
# 用法: ./scripts/dev-browser.sh
# 停止: ./scripts/dev-browser.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${ROOT}/storage/dev-browser"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID="${LOG_DIR}/backend.pid"
FRONTEND_PID="${LOG_DIR}/frontend.pid"

mkdir -p "$LOG_DIR"

port_listen() {
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1
}

wait_health() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 60); do
    if curl -sS -m 2 "$url" >/dev/null 2>&1; then
      echo "  ✓ ${label} 就绪"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ ${label} 启动超时，见 ${BACKEND_LOG}" >&2
  return 1
}

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

echo "=== Huoke 浏览器开发（无 Docker）==="

if port_listen "$BACKEND_PORT"; then
  echo "  · 后端已在端口 ${BACKEND_PORT}"
else
  echo "  · 启动后端..."
  nohup env BACKEND_PORT="$BACKEND_PORT" bash "$ROOT/scripts/dev-native.sh" >>"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID"
  wait_health "http://127.0.0.1:${BACKEND_PORT}/api/health" "后端"
fi

if port_listen "$FRONTEND_PORT"; then
  echo "  · 前端已在端口 ${FRONTEND_PORT}"
else
  echo "  · 启动前端..."
  (
    cd "$ROOT/frontend"
    nohup npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1
  ) &
  echo $! >"$FRONTEND_PID"
  for _ in $(seq 1 45); do
    if port_listen "$FRONTEND_PORT"; then
      echo "  ✓ 前端就绪"
      break
    fi
    sleep 1
  done
fi

echo ""
echo "浏览器打开: http://127.0.0.1:${FRONTEND_PORT}/"
echo "API 文档:   http://127.0.0.1:${BACKEND_PORT}/docs"
echo "日志目录:   ${LOG_DIR}/"
echo "停止服务:   ./scripts/dev-browser.sh --stop"
