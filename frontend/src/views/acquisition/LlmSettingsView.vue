<template>
  <div class="acquisition-page">
    <header class="page-header panel">
      <div>
        <h1 class="page-title">大模型配置</h1>
        <p class="page-subtitle">配置 DeepSeek，用于任务编排、评论评估与线索筛选。</p>
      </div>
    </header>

    <SettingsModelSection />
  </div>
</template>

<script setup>
import SettingsModelSection from "../settings/SettingsModelSection.vue";
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.page-header {
  padding: 20px 24px;
}
</style>
