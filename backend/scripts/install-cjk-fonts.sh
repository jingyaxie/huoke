#!/bin/sh
# VNC/Chromium 容器默认无 CJK 字体，中文会显示为方框。启动时补齐常用字体。
set -e

FONT_DIR="/usr/share/fonts/truetype/wqy"
MARKER="$FONT_DIR/.installed"

if [ -f "$FONT_DIR/wqy-microhei.ttc" ]; then
  if [ ! -f "$MARKER" ]; then
    date > "$MARKER" 2>/dev/null || true
  fi
  exit 0
fi

if [ -f "$MARKER" ]; then
  exit 0
fi

mkdir -p "$FONT_DIR"

download() {
  url="$1"
  dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$dest" "$url"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$dest" "$url"
    return
  fi
  echo "[fonts] curl/wget unavailable, skip CJK font install" >&2
  return 1
}

echo "[fonts] installing wqy-microhei for CJK rendering..."
download \
  "https://cdn.jsdelivr.net/gh/anthonyfok/fonts-wqy-microhei@master/wqy-microhei.ttc" \
  "$FONT_DIR/wqy-microhei.ttc"

if command -v fc-cache >/dev/null 2>&1; then
  fc-cache -fv >/dev/null 2>&1 || fc-cache -f >/dev/null 2>&1 || true
fi

date > "$MARKER"
echo "[fonts] CJK fonts ready"
