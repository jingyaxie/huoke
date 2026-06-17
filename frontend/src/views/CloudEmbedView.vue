<template>
  <div class="cloud-embed">
    <iframe
      ref="frameRef"
      class="cloud-frame"
      :src="embedUrl"
      :title="pageTitle"
      referrerpolicy="no-referrer-when-downgrade"
      allow="clipboard-read; clipboard-write"
      @load="onFrameLoad"
    />
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { findCloudNavByRoute, getPortalBaseUrl } from "../config/cloudNav";
import { buildPortalEmbedUrl, PORTAL_PING_MESSAGE } from "../utils/portalShell";

const route = useRoute();
const frameRef = ref(null);

const pageTitle = computed(() => route.meta?.title || "盈小蚁客户后台");

const embedUrl = computed(() => {
  const navItem = findCloudNavByRoute(route.path);
  const h5Path = navItem?.h5Path || route.meta?.h5Path || "/customer/dashboard";
  const base = h5Path.startsWith("http") ? h5Path : `${getPortalBaseUrl()}${h5Path}`;
  const suffix = route.fullPath.includes("?") ? route.fullPath.slice(route.fullPath.indexOf("?")) : "";
  return buildPortalEmbedUrl(`${base}${suffix}`);
});

function onFrameLoad() {
  const win = frameRef.value?.contentWindow;
  if (!win) return;
  try {
    win.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* cross-origin until loaded */
  }
}
</script>

<style scoped>
.cloud-embed {
  height: 100%;
  min-height: 0;
  margin: -28px -32px;
}

.cloud-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: calc(100vh - 56px);
  border: 0;
  background: #fff;
}
</style>
