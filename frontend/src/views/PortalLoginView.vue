<template>
  <div class="portal-login">
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
  readPortalAuth,
} from "../utils/portalShell";
import { mapH5PathToCloudRoute } from "../config/cloudNav";

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

function resolveRedirectTarget() {
  if (typeof route.query.redirect === "string" && route.query.redirect) {
    return route.query.redirect;
  }
  const authPath = readPortalAuth()?.path;
  if (authPath) return mapH5PathToCloudRoute(authPath);
  return "/cloud/dashboard";
}

function onMessage(event) {
  const result = handlePortalMessage(event);
  if (!result || result.navigate) return;
  if (!isPortalAuthenticated()) return;
  router.replace(resolveRedirectTarget()).catch(() => {});
}

onMounted(() => {
  if (isPortalAuthenticated()) {
    router.replace(resolveRedirectTarget()).catch(() => {});
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
  width: 100%;
  height: 100%;
  min-height: 100%;
  overflow: auto;
  background: linear-gradient(160deg, #f0f9ff 0%, #f8fafc 48%, #eff6ff 100%);
}

.portal-login-frame {
  display: block;
  width: 100%;
  min-height: 100%;
  height: 100vh;
  border: 0;
  background: transparent;
}
</style>
