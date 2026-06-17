<template>
  <div class="portal-login">
    <header class="portal-login-bar">
      <div class="portal-login-bar-text">
        <strong>盈小蚁 · AI获客</strong>
        <span>登录云端客户后台后，可使用数据看板、AI 客服；本机获客从侧栏直接进入</span>
      </div>
    </header>

    <iframe
      ref="frameRef"
      class="portal-login-frame"
      :src="loginUrl"
      title="盈小蚁登录"
      scrolling="yes"
      referrerpolicy="no-referrer-when-downgrade"
      @load="pingFrame"
    />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  buildPortalLoginUrl,
  handlePortalMessage,
  isPortalAuthenticated,
  PORTAL_PING_MESSAGE,
} from "../utils/portalShell";

const router = useRouter();
const route = useRoute();
const frameRef = ref(null);
const loginUrl = buildPortalLoginUrl();
let pingTimer = null;

function pingFrame() {
  const win = frameRef.value?.contentWindow;
  if (!win) return;
  try {
    win.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* ignore */
  }
}

function onMessage(event) {
  const result = handlePortalMessage(event);
  if (!result || result.navigate) return;
  if (!isPortalAuthenticated()) return;
  const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/cloud/dashboard";
  router.replace(redirect).catch(() => {});
}

onMounted(() => {
  if (isPortalAuthenticated()) {
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/cloud/dashboard";
    router.replace(redirect).catch(() => {});
    return;
  }
  window.addEventListener("message", onMessage);
  pingTimer = window.setInterval(pingFrame, 1500);
});

onUnmounted(() => {
  window.removeEventListener("message", onMessage);
  if (pingTimer) {
    window.clearInterval(pingTimer);
    pingTimer = null;
  }
});
</script>

<style scoped>
.portal-login {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #f8fafc;
}

.portal-login-bar {
  flex-shrink: 0;
  padding: 14px 28px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}

.portal-login-bar-text {
  display: flex;
  align-items: baseline;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 14px;
  color: #64748b;
}

.portal-login-bar-text strong {
  font-size: 16px;
  color: #0f172a;
}

.portal-login-frame {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  background: #fff;
}
</style>
