<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">执行账号绑定</h1>
        <p class="page-subtitle">
          绑定用于本机获客的抖音、小红书、快手账号（在本机 Chrome 登录）。
          与盈小蚁 H5 登录无关，也不同于云端「账号管理」里的组织账号。
        </p>
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
