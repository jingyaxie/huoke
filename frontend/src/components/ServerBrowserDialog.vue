<template>
  <el-dialog v-model="visibleProxy" title="服务器浏览器" width="92vw" top="5vh" append-to-body destroy-on-close>
    <div class="browser-shell">
      <div class="browser-toolbar">
        <el-button type="primary" @click="openInNewTab">新窗口打开</el-button>
        <el-link v-if="url" :href="url" target="_blank" type="primary">直接打开浏览器</el-link>
      </div>
      <iframe v-if="url" class="browser-frame" :src="url" />
      <el-empty v-else description="未获取到浏览器地址" />
    </div>
  </el-dialog>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  url: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);

const visibleProxy = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

function openInNewTab() {
  if (!props.url) return;
  window.open(props.url, "_blank", "noopener,noreferrer");
}
</script>

<style scoped>
.browser-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.browser-frame {
  width: 100%;
  height: 78vh;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
}
</style>
