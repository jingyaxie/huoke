<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">账号设置</h1>
        <p class="page-subtitle">管理已授权的抖音、小红书与快手账号，拉取会话并控制监听状态。</p>
      </div>
      <el-button type="primary" class="create-btn" @click="openAuthorize">+ 授权账号</el-button>
    </header>

    <AccountSettingsPanel ref="panelRef" />
  </div>
</template>

<script setup>
import { ref } from "vue";
import AccountSettingsPanel from "../../components/AccountSettingsPanel.vue";

const panelRef = ref(null);

function openAuthorize() {
  panelRef.value?.openAuthorize();
}
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.create-btn {
  flex-shrink: 0;
  padding: 0 20px;
}
</style>
