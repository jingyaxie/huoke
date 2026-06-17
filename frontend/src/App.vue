<template>
  <router-view />
</template>

<script setup>
import { onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import { handlePortalMessage } from "./utils/portalShell";

const router = useRouter();

function onPortalMessage(event) {
  const result = handlePortalMessage(event);
  if (result?.navigate) {
    router.push(result.navigate).catch(() => {});
  }
}

onMounted(() => {
  window.addEventListener("message", onPortalMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", onPortalMessage);
});
</script>
