#!/usr/bin/env bash
# 解析 Huoke 工程根目录（开发 / .app 打包后均可用）
set -euo pipefail

ensure_desktop_path() {
  export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
}

resolve_huoke_root() {
  if [[ -n "${HUOKE_ROOT:-}" ]]; then
    if [[ -f "$HUOKE_ROOT/scripts/desktop-run-backend.sh" ]]; then
      echo "$HUOKE_ROOT"
      return
    fi
    if [[ -f "$HUOKE_ROOT/desktop-run-backend.sh" ]]; then
      echo "$HUOKE_ROOT"
      return
    fi
  fi
  local here="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  local dir
  dir="$(cd "$(dirname "$here")" && pwd)"
  if [[ -f "$dir/desktop-run-backend.sh" ]]; then
    echo "$dir"
    return
  fi
  if [[ -f "$dir/scripts/desktop-run-backend.sh" ]]; then
    echo "$dir"
    return
  fi
  if [[ -f "$dir/../scripts/desktop-run-backend.sh" ]]; then
    echo "$(cd "$dir/.." && pwd)"
    return
  fi
  echo "无法定位 Huoke 工程根目录" >&2
  exit 1
}

resolve_huoke_data_dir() {
  if [[ -n "${HUOKE_DATA_DIR:-}" ]]; then
    echo "$HUOKE_DATA_DIR"
    return
  fi
  local home="${HOME:-/tmp}"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "$home/Library/Application Support/com.huoke.desktop"
    return
  fi
  echo "$home/.local/share/huoke"
}

resolve_huoke_bundle_dir() {
  if [[ -n "${HUOKE_BUNDLE_DIR:-}" && -d "$HUOKE_BUNDLE_DIR/runtime" ]]; then
    echo "$HUOKE_BUNDLE_DIR"
    return
  fi
  local root
  root="$(resolve_huoke_root)"
  if [[ -d "$root/desktop/bundle/runtime" ]]; then
    echo "$root/desktop/bundle"
    return
  fi
  if [[ -d "$root/bundle/runtime" ]]; then
    echo "$root/bundle"
    return
  fi
  echo "$root"
}
