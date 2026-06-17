#!/usr/bin/env bash
# 一键检查 Huoke Sidecar 独立运行状态（Mac dev / 已启动 Sidecar 时）
# 用法：bash projects/huoke/scripts/verify-huoke-standalone.sh
# 若 Sidecar 未运行，先执行：bash projects/huoke/scripts/dev-sidecar-macos.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR_PORT="${SIDECAR_PORT:-18000}"
BASE="http://127.0.0.1:${SIDECAR_PORT}"
ENV_SIDECAR="${ROOT}/.env.sidecar"

read_bridge_secret() {
  if [[ -f "$ENV_SIDECAR" ]]; then
    local line
    line="$(grep -E '^HUOKE_BRIDGE_SECRET=' "$ENV_SIDECAR" 2>/dev/null | tail -1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#HUOKE_BRIDGE_SECRET=}" | tr -d '"'"'"
      return
    fi
  fi
  echo "dev-bridge-secret"
}

BRIDGE_SECRET="$(read_bridge_secret)"
TENANT="${HUOKE_TENANT_ID:-default}"
ACCOUNT="${HUOKE_ACCOUNT_ID:-default}"
PASS=0
FAIL=0
SKIP=0

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad()  { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "  ~ $*"; SKIP=$((SKIP + 1)); }

echo "=== Huoke Sidecar 独立验证 ==="
echo "BASE=$BASE  tenant=$TENANT  account=$ACCOUNT"
echo ""

# 1. 端口 / health
echo "[1/5] Sidecar 健康"
if curl -sS -m 5 "${BASE}/api/health" | grep -q '"status":"ok"'; then
  ok "GET /api/health"
else
  bad "GET /api/health 失败 — Sidecar 未启动？运行: bash projects/huoke/scripts/dev-sidecar-macos.sh"
  echo ""
  echo "结果: ${PASS} 通过, ${FAIL} 失败, ${SKIP} 跳过"
  exit 1
fi

# 2. compat health
echo "[2/5] Compat 桥"
COMPAT_CODE="$(curl -sS -m 8 "${BASE}/api/v3/tikhub-compat/health" \
  -H "X-Bridge-Secret: ${BRIDGE_SECRET}" \
  -H "X-Tenant-Id: ${TENANT}" \
  -H "X-Account-Id: ${ACCOUNT}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',''))" 2>/dev/null || echo "")"
if [[ "$COMPAT_CODE" == "200" ]]; then
  ok "GET /api/v3/tikhub-compat/health (code=200)"
else
  bad "Compat health 异常 (code=${COMPAT_CODE:-?}) — 检查 HUOKE_BRIDGE_SECRET"
fi

# 3. Chrome
echo "[3/5] 环境"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ -x "$CHROME" ]]; then
  ok "系统 Chrome: $("$CHROME" --version 2>/dev/null | head -1)"
else
  skip "未安装系统 Chrome（Sidecar 扫码需 Chrome 或 Playwright Chromium）"
fi
if [[ -d "${ROOT}/backend/.venv" ]]; then
  ok "Python venv: ${ROOT}/backend/.venv"
else
  skip "venv 未创建 — dev-sidecar-macos.sh 首次运行会自动创建"
fi
if [[ -f "$ENV_SIDECAR" ]]; then
  ok ".env.sidecar 存在"
else
  skip ".env.sidecar 缺失 — 首次 dev-sidecar-macos.sh 会自动生成"
fi

# 4. 绑定 / Cookie
echo "[4/5] 平台绑定"
LOGIN_JSON="$(curl -sS -m 8 "${BASE}/api/accounts/${ACCOUNT}/platforms/douyin/login-status" \
  -H "X-Tenant-Id: ${TENANT}" 2>/dev/null || echo '{}')"
LOGIN_STATUS="$(echo "$LOGIN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")"
if [[ "$LOGIN_STATUS" == "ready" ]]; then
  ok "抖音 Cookie 就绪 (status=ready)"
  DO_SEARCH=1
else
  skip "抖音 Cookie 未就绪 (status=${LOGIN_STATUS:-unknown}) — 需 server-login 扫码"
  DO_SEARCH=0
fi

# 5. compat 搜索（可选，较慢）
echo "[5/5] Compat 搜索（可选，约 30–90s）"
if [[ "${SKIP_SEARCH:-0}" == "1" ]]; then
  skip "SKIP_SEARCH=1，跳过搜索"
elif [[ "$DO_SEARCH" != "1" ]]; then
  skip "Cookie 未就绪，跳过搜索"
else
  SEARCH_OUT="$(curl -sS -m 120 -X POST \
    "${BASE}/api/v3/tikhub-compat/api/v1/douyin/search/fetch_video_search_v1" \
    -H "Content-Type: application/json" \
    -H "X-Bridge-Secret: ${BRIDGE_SECRET}" \
    -H "X-Tenant-Id: ${TENANT}" \
    -H "X-Account-Id: ${ACCOUNT}" \
    -d '{"keyword":"团餐","count":2}' 2>/dev/null || echo '{}')"
  SEARCH_CODE="$(echo "$SEARCH_OUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',''))" 2>/dev/null || echo "")"
  if [[ "$SEARCH_CODE" == "200" ]]; then
    ok "抖音关键词搜索 (code=200)"
  else
    bad "搜索失败 (code=${SEARCH_CODE:-?}) — 查看 Sidecar 终端日志"
  fi
fi

echo ""
echo "=== 结果: ${PASS} 通过, ${FAIL} 失败, ${SKIP} 跳过 ==="
if [[ "$FAIL" -gt 0 ]]; then
  echo "排查: projects/huoke/README.md § PC 获客 Sidecar"
  exit 1
fi
echo "Sidecar 独立链路正常。下一步可启动 PC 客户端联调："
echo "  cd code/pc-acquisition-client && bash scripts/dev-with-huoke.sh"
exit 0
