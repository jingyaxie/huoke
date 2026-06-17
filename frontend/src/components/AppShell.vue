<template>
  <div v-if="isNative" class="app-shell-native">
    <router-view />
  </div>
  <div v-else class="app-shell">
    <section v-if="!showApp" class="portal-pane">
      <iframe
        ref="portalFrameRef"
        class="portal-frame"
        :src="portalUrl"
        title="盈小蚁客户平台"
        referrerpolicy="no-referrer-when-downgrade"
        allow="clipboard-read; clipboard-write"
        @load="pingPortalFrame"
      />
    </section>

    <section v-if="showApp" class="app-pane">
      <router-view />
    </section>

    <footer class="shell-footer">
      <span class="shell-hint">{{ showApp ? "当前：获客平台" : "当前：盈小蚁网页" }}</span>
      <button
        v-if="!showApp"
        type="button"
        class="shell-action shell-action-primary"
        @click="openApp"
      >
        进入获客平台
      </button>
      <button
        v-else
        type="button"
        class="shell-action shell-action-back"
        @click="closeApp"
      >
        ← 返回盈小蚁
      </button>
    </footer>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  PORTAL_PING_MESSAGE,
  PORTAL_SHELL_STORAGE_KEY,
  buildPortalEmbedUrl,
  detectNativeShell,
  isPortalAuthMessage,
  isPortalMessageOrigin,
} from "../utils/portalShell";

const router = useRouter();
const portalUrl = buildPortalEmbedUrl();
const isNative = ref(false);
const showApp = ref(false);
const portalFrameRef = ref(null);
let portalPingTimer = null;

function pingPortalFrame() {
  const win = portalFrameRef.value?.contentWindow;
  if (!win || showApp.value) return;
  try {
    win.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* cross-origin iframe may reject until loaded */
  }
}

function openApp({ navigate = true } = {}) {
  if (showApp.value) return;
  showApp.value = true;
  sessionStorage.setItem(PORTAL_SHELL_STORAGE_KEY, "1");
  if (!navigate) return;
  const path = router.currentRoute.value.path;
  if (path === "/" || path === "" || !path.startsWith("/agent")) {
    router.push("/agent");
  }
}

function closeApp() {
  showApp.value = false;
  sessionStorage.removeItem(PORTAL_SHELL_STORAGE_KEY);
}

function onPortalMessage(event) {
  if (!isPortalMessageOrigin(event.origin)) return;
  if (!isPortalAuthMessage(event.data)) return;
  openApp();
}

onMounted(() => {
  const pcEmbed = new URLSearchParams(window.location.search).get("pc_embed") === "1";
  isNative.value = detectNativeShell() || pcEmbed;
  if (pcEmbed) {
    document.body.classList.add("native-shell");
    showApp.value = true;
    router.replace("/settings/account").catch(() => {});
    return;
  }
  if (isNative.value) {
    document.body.classList.add("native-shell");
    return;
  }

  if (sessionStorage.getItem(PORTAL_SHELL_STORAGE_KEY) === "1") {
    showApp.value = true;
  }

  window.addEventListener("message", onPortalMessage);
  portalPingTimer = window.setInterval(pingPortalFrame, 1500);
});

onBeforeUnmount(() => {
  window.removeEventListener("message", onPortalMessage);
  if (portalPingTimer) {
    window.clearInterval(portalPingTimer);
    portalPingTimer = null;
  }
});
</script>

<style scoped>
.app-shell,
.app-shell-native {
  height: 100%;
  min-height: 0;
}

.app-shell-native {
  overflow: auto;
  padding-bottom: 52px;
}

.app-shell {
  display: flex;
  flex-direction: column;
  background: #fff;
}

.portal-pane,
.app-pane {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.portal-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.app-pane {
  overflow: auto;
}

.shell-footer {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 52px;
  padding: 0 16px;
  border-top: 1px solid #cbd5e1;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: 0 -4px 16px rgba(15, 23, 42, 0.08);
}

.shell-hint {
  color: #64748b;
  font-size: 12px;
}

.shell-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid #d1d5db;
  border-radius: 999px;
  background: #fff;
  color: #374151;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.shell-action-primary {
  border-color: #0f766e;
  background: #0f766e;
  color: #fff;
}

.shell-action-primary:hover {
  border-color: #0d9488;
  background: #0d9488;
}

.shell-action:hover {
  border-color: var(--primary);
  color: var(--primary);
  box-shadow: 0 2px 8px rgba(15, 118, 110, 0.12);
}

.shell-action-back {
  color: var(--primary);
  border-color: #99f6e4;
  background: #f0fdfa;
}

.shell-action-icon {
  font-size: 14px;
  line-height: 1;
}
</style>
