<template>
  <div class="task-layout">
    <header class="task-layout-header panel">
      <div class="header-left">
        <el-button v-if="isSecondary" class="back-btn" text @click="goBack">
          ← 返回列表
        </el-button>
        <nav class="breadcrumb" aria-label="任务导航">
          <router-link to="/tasks" class="crumb-link" :class="{ active: !isSecondary }">任务编排</router-link>
          <template v-if="isSecondary">
            <span class="crumb-sep">/</span>
            <span class="crumb-current">{{ secondaryTitle }}</span>
          </template>
        </nav>
      </div>
      <router-link to="/test" class="exit-link">← 返回测试入口</router-link>
    </header>

    <main class="task-layout-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

const isSecondary = computed(() => route.name !== "tasks");

const secondaryTitle = computed(() => {
  if (route.name === "task-create") return "创建任务";
  if (route.name === "task-compile") return "编译联调";
  if (route.name === "task-detail") return "任务详情";
  return "";
});

function goBack() {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  router.push("/tasks");
}
</script>

<style scoped>
.task-layout {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: #f3f6f9;
  padding: 12px;
  gap: 12px;
  box-sizing: border-box;
}

.task-layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.back-btn {
  flex-shrink: 0;
  padding-left: 0;
  font-weight: 600;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 15px;
}

.crumb-link {
  color: var(--el-color-primary);
  text-decoration: none;
  font-weight: 600;
  white-space: nowrap;
}

.crumb-link.active {
  color: #1f2937;
  cursor: default;
  pointer-events: none;
}

.crumb-sep {
  color: #cbd5e1;
}

.crumb-current {
  color: #64748b;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exit-link {
  flex-shrink: 0;
  font-size: 13px;
  color: #64748b;
  text-decoration: none;
}

.exit-link:hover {
  color: var(--el-color-primary);
}

.task-layout-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
}
</style>
