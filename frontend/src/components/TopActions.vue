<template>
  <div class="panel top-actions">
    <div class="left">
      <h2 class="page-title">{{ title }}</h2>
      <p class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div class="right">
      <el-button type="primary" @click="$emit('crawl')">抓取热榜</el-button>
      <el-button type="warning" @click="$emit('login')">服务器登录</el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: "" },
});

defineEmits(["crawl", "login"]);
</script>

<style scoped>
.top-actions {
  padding: 16px;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
}

.right {
  display: flex;
  gap: 8px;
}

@media (max-width: 760px) {
  .top-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
