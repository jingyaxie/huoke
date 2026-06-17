<template>
  <div class="stats-grid">
    <div v-for="item in items" :key="item.key" class="stats-card">
      <span class="stats-label" :class="`tone-${item.key}`">{{ item.label }}</span>
      <div class="stats-value">{{ loading ? "—" : formatValue(data?.[item.key]) }}</div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
});

const items = [
  { key: "running_tasks", label: "运行中任务" },
  { key: "queued_tasks", label: "排队中" },
  { key: "precise_customers", label: "精准客户" },
  { key: "total_leads", label: "总线索" },
  { key: "dm_count", label: "私信数" },
  { key: "follow_count", label: "关注数" },
];

function formatValue(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString("zh-CN") : "0";
}
</script>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.stats-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: #fff;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.stats-label {
  display: inline-flex;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
}

.stats-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.tone-running_tasks { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.tone-queued_tasks { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
.tone-precise_customers { background: var(--el-color-success-light-9); color: var(--el-color-success); }
.tone-total_leads { background: #f3e8ff; color: #7c3aed; }
.tone-dm_count { background: #e0f2fe; color: #0284c7; }
.tone-follow_count { background: #ffe4e6; color: #e11d48; }

@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
