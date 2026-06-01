<template>
  <div class="layout">
    <aside class="sidebar panel">
      <div class="brand">抖音热点平台</div>
      <div class="tenant-box">
        <div class="tenant-label">数据源</div>
        <el-input v-model="platformId" size="small" placeholder="douyin / xiaohongshu / kuaishou" @change="onPlatformChange" />
      </div>
      <div class="tenant-box">
        <div class="tenant-label">租户 ID</div>
        <el-input v-model="tenantId" size="small" placeholder="default" @change="onTenantChange" />
      </div>
      <div class="tenant-box">
        <div class="tenant-label">API Key</div>
        <el-input
          v-model="apiKey"
          size="small"
          type="password"
          show-password
          placeholder="启用鉴权时填写"
          @change="onApiKeyChange"
        />
      </div>
      <el-menu :default-active="activePath" router>
        <el-menu-item index="/videos">热门视频</el-menu-item>
        <el-menu-item index="/authors">热门作者</el-menu-item>
        <el-menu-item index="/trend">趋势分析</el-menu-item>
        <el-menu-item index="/comments">评论抓取</el-menu-item>
        <el-menu-item index="/agent" class="agent-nav-item">智能体助手</el-menu-item>
        <el-menu-item index="/antibot">AntiBot</el-menu-item>
        <el-menu-item index="/reports">热点日报</el-menu-item>
      </el-menu>
    </aside>
    <main class="content">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { getTenantId, setTenantId, getPlatformId, setPlatformId, getApiKey, setApiKey } from "../api/http";

const route = useRoute();
const activePath = computed(() => route.path);
const tenantId = ref(getTenantId());
const platformId = ref(getPlatformId());
const apiKey = ref(getApiKey());

function onTenantChange() {
  setTenantId(tenantId.value);
  window.dispatchEvent(new CustomEvent("huoke-tenant-changed", { detail: tenantId.value }));
}

function onPlatformChange() {
  setPlatformId(platformId.value);
}

function onApiKeyChange() {
  setApiKey(apiKey.value);
}
</script>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-height: 100vh;
  gap: 12px;
  padding: 12px;
}

.sidebar {
  overflow: hidden;
}

.brand {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
  padding: 18px 16px 12px;
}

.tenant-box {
  padding: 0 12px 12px;
}

.tenant-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 6px;
}

.content {
  min-width: 0;
}

:deep(.agent-nav-item) {
  color: var(--el-color-primary) !important;
  font-weight: 600;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
