<template>
  <el-dialog
    v-model="visibleProxy"
    width="96vw"
    top="2vh"
    append-to-body
    destroy-on-close
    :show-header="false"
    :body-style="{ padding: '0' }"
    class="vnc-browser-dialog"
  >
    <iframe v-if="url" class="browser-frame" :src="url" title="服务器浏览器" />
    <el-empty v-else description="未获取到浏览器地址" />
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
</script>

<style scoped>
.browser-frame {
  display: block;
  width: 100%;
  height: 92vh;
  border: 0;
  background: #111;
}
</style>
