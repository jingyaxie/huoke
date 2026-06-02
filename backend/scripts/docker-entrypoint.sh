#!/bin/sh
set -e

display_ready() {
  if command -v xdpyinfo >/dev/null 2>&1; then
    xdpyinfo -display :99 >/dev/null 2>&1
  else
    test -S /tmp/.X11-unix/X99
  fi
}

port_open() {
  python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', $1)); s.close()"
}

start_vnc() {
  rm -f /tmp/.X99-lock 2>/dev/null || true
  mkdir -p /tmp/.X11-unix
  rm -f /tmp/.X11-unix/X99 2>/dev/null || true

  echo "[vnc] starting Xvfb :99..."
  Xvfb :99 -screen 0 1440x900x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
  sleep 2

  i=0
  while [ "$i" -lt 15 ]; do
    if display_ready; then
      echo "[vnc] Xvfb ready"
      break
    fi
    i=$((i + 1))
    sleep 1
  done

  if ! display_ready; then
    echo "[vnc] WARN: Xvfb may not be ready" >&2
    cat /tmp/xvfb.log >&2 || true
  fi

  export DISPLAY=:99
  mkdir -p /root/.fluxbox
  if [ -f /app/scripts/fluxbox/init ]; then
    cp /app/scripts/fluxbox/init /root/.fluxbox/init
  fi
  # 避免默认 init 调用 fbsetbg 弹出 xmessage 挡住 VNC 登录窗口
  fluxbox -display :99 >/tmp/fluxbox.log 2>&1 &
  sleep 1
  pkill -x xmessage 2>/dev/null || true

  echo "[vnc] starting x11vnc on :5900..."
  x11vnc -display :99 -nopw -forever -shared -listen 0.0.0.0 -xkb -rfbport 5900 \
    -bg -o /tmp/x11vnc.log

  sleep 1
  if ! port_open 5900; then
    echo "[vnc] WARN: x11vnc not listening on 5900" >&2
    cat /tmp/x11vnc.log >&2 || true
  fi

  echo "[vnc] starting websockify on :6080..."
  websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
  sleep 1
  echo "[vnc] stack ready"
}

wait_mysql() {
  python - <<'PY'
import os
import time
import pymysql

host = "mysql"
port = 3306
user = os.getenv("MYSQL_USER", "douyin")
pwd = os.getenv("MYSQL_PASSWORD", "douyin")
db = os.getenv("MYSQL_DATABASE", "douyin_hot")
for _ in range(60):
    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=pwd, database=db)
        conn.close()
        raise SystemExit(0)
    except Exception:
        time.sleep(2)
raise SystemExit(1)
PY
}

sh /app/scripts/install-cjk-fonts.sh || echo "[fonts] WARN: CJK font install skipped" >&2

# 运行时兜底：某些旧镜像未包含 PyJWT，先补齐依赖再启动 API。
python - <<'PY'
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("jwt") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyJWT==2.10.1"])
PY

start_vnc
wait_mysql
alembic upgrade head
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
