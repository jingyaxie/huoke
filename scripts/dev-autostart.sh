#!/usr/bin/env bash
# Huoke 本地开发一键自启：Native 后端 (8000) + Vite 前端 (5173)
# 用法：./scripts/dev-autostart.sh
# 停止：./scripts/dev-autostart.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${ROOT}/storage/dev-autostart"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID="${LOG_DIR}/backend.pid"
FRONTEND_PID="${LOG_DIR}/frontend.pid"

mkdir -p "$LOG_DIR"

port_listen() {
  local port="$1"
  lsof -iTCP:"${port}" -sTCP:LISTEN -P -n >/dev/null 2>&1
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

echo "=== Huoke dev 自动启动 ==="

if port_listen "$BACKEND_PORT"; then
  echo "  · 后端已在端口 ${BACKEND_PORT}"
else
  echo "  · 启动 Native 后端..."
  nohup bash "$ROOT/scripts/dev-native.sh" >>"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID"
  wait_health "http://127.0.0.1:${BACKEND_PORT}/api/health" "后端"
fi

if port_listen "$FRONTEND_PORT"; then
  echo "  · 前端已在端口 ${FRONTEND_PORT}"
else
  echo "  · 启动 Vite 前端..."
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
echo "前端: http://127.0.0.1:${FRONTEND_PORT}/"
echo "API:  http://127.0.0.1:${BACKEND_PORT}/api/health"
echo "日志: ${LOG_DIR}/"
echo "停止: ./scripts/dev-autostart.sh --stop"
