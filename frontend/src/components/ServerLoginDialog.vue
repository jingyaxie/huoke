<template>
  <el-dialog
    v-model="visibleProxy"
    :title="title"
    width="92vw"
    top="5vh"
    append-to-body
    destroy-on-close
  >
    <div class="login-shell">
      <div v-if="contextLabel" class="login-context-banner">
        <div class="login-context-title">请在此窗口完成扫码登录</div>
        <div class="login-context-meta">
          <span v-if="platformLabel" class="login-context-tag">{{ platformLabel }}</span>
          <span class="login-context-tag login-context-tenant">租户 {{ tenantId || "default" }}</span>
          <span class="login-context-tag login-context-account">账号 {{ accountId || "default" }}</span>
        </div>
        <p class="login-context-hint">
          请确认以上信息与你要绑定的账号一致，避免扫错码导致串号。
          若状态显示「已登录」但页面仍出现登录框，说明 Cookie 已过期或与 Profile 不同步，可在此直接查看真实浏览器界面。
        </p>
      </div>
      <div class="login-toolbar">
        <el-button type="primary" @click="openInNewTab">新窗口打开</el-button>
        <el-link v-if="displayUrl" :href="displayUrl" target="_blank" type="primary">直接打开登录页</el-link>
      </div>
      <iframe v-if="displayUrl" class="login-frame" :src="displayUrl" />
      <el-empty v-else description="未获取到登录地址" />
    </div>
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

const contextLabel = computed(
  () => props.platformLabel || props.tenantId || props.accountId,
);

function openInNewTab() {
  if (!displayUrl.value) return;
  window.open(displayUrl.value, "_blank", "noopener,noreferrer");
}
</script>

<style scoped>
.login-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.login-context-banner {
  padding: 14px 16px;
  border-radius: 10px;
  background: linear-gradient(135deg, #ecfdf5 0%, #eff6ff 100%);
  border: 1px solid #99f6e4;
}

.login-context-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f766e;
  margin-bottom: 10px;
}

.login-context-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.login-context-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  background: #fff;
  color: #0f766e;
  border: 1px solid #99f6e4;
}

.login-context-tenant {
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.login-context-account {
  color: #7c3aed;
  border-color: #ddd6fe;
}

.login-context-hint {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.login-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.login-frame {
  width: 100%;
  height: 78vh;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
}
</style>
