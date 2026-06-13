<template>
  <el-dialog
    v-model="visibleProxy"
    width="100vw"
    top="0"
    append-to-body
    destroy-on-close
    :show-header="false"
    :body-style="{ padding: '0' }"
    class="vnc-browser-dialog"
  >
    <iframe v-if="displayUrl" class="login-frame" :src="displayUrl" title="VNC 浏览器" />
    <el-empty v-else description="未获取到登录地址" />
  </el-dialog>
</template>

<script setup>
import { computed } from "vue";
import { resolveVncUrl } from "../api/http";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  url: { type: String, default: "" },
  tenantId: { type: String, default: "" },
  accountId: { type: String, default: "" },
  platformLabel: { type: String, default: "" },
  title: { type: String, default: "VNC 浏览器" },
});

const emit = defineEmits(["update:modelValue"]);

const visibleProxy = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const displayUrl = computed(() => resolveVncUrl(props.url));
</script>

<style scoped>
.login-frame {
  display: block;
  width: 100%;
  height: 100vh;
  border: 0;
  background: #111;
}
</style>

<style>
.vnc-browser-dialog .el-dialog {
  margin: 0;
  max-height: 100vh;
  background: #111;
}

.vnc-browser-dialog .el-dialog__body {
  overflow: hidden;
}
</style>
