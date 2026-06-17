<template>
  <div class="merchant-layout">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="brand-title">商家管理后台</div>
        <div class="brand-sub">盈小蚁</div>
      </div>

      <div class="sidebar-divider" />

      <nav class="nav-section">
        <div class="section-title">AI 获客管理</div>
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: isActive(item.to) }"
        >
          <span class="nav-indicator" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div v-if="showDevNav" class="nav-section dev-section">
        <div class="section-title">开发者</div>
        <router-link
          v-for="item in devNavItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: isActive(item.to) }"
        >
          <span class="nav-indicator" />
          <span>{{ item.label }}</span>
        </router-link>
      </div>

      <div class="sidebar-foot">
        <div class="foot-meta">v{{ appVersion }} · 本地独立运行</div>
      </div>
    </aside>

    <div class="main-column">
      <header class="top-header">
        <div class="breadcrumb">
          <span class="breadcrumb-section">{{ breadcrumbSection }}</span>
          <span class="breadcrumb-sep">/</span>
          <span class="breadcrumb-title">{{ breadcrumbTitle }}</span>
        </div>
        <div class="top-user">
          <span>你好，{{ displayName }}</span>
          <button type="button" class="logout-btn" @click="handleLogout">[退出]</button>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { getTenantId } from "../api/http";

const route = useRoute();

const navItems = [
  { to: "/auto-tasks", label: "自动获客" },
  { to: "/manual-tasks", label: "手动获客" },
  { to: "/account-settings", label: "账号设置" },
  { to: "/llm-settings", label: "大模型配置" },
  { to: "/presets", label: "评论/私信预设" },
];

const devNavItems = [
  { to: "/agent", label: "智能体助手" },
  { to: "/tasks", label: "任务编排" },
  { to: "/crawl-data", label: "数据面板" },
  { to: "/external-api", label: "API 文档" },
];

const ROUTE_META = {
  "/auto-tasks": { section: "AI 获客管理", title: "任务列表" },
  "/manual-tasks": { section: "AI 获客管理", title: "任务列表" },
  "/account-settings": { section: "AI 获客管理", title: "账号设置" },
  "/llm-settings": { section: "AI 获客管理", title: "大模型配置" },
  "/presets": { section: "AI 获客管理", title: "评论/私信预设" },
};

const showDevNav = computed(() => import.meta.env.DEV || import.meta.env.VITE_DEV_MENU === "1");
const appVersion = computed(() => import.meta.env.VITE_APP_VERSION || "0.2.0");
const displayName = computed(() => getTenantId() || "用户");

const breadcrumbSection = computed(() => {
  const meta = route.meta?.section || ROUTE_META[route.path]?.section;
  return meta || "AI 获客管理";
});

const breadcrumbTitle = computed(() => {
  const meta = route.meta?.title || ROUTE_META[route.path]?.title;
  return meta || "盈小蚁";
});

function isActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`);
}

function handleLogout() {
  ElMessage.info("独立版为本地运行，无需退出登录");
}
</script>

<style scoped>
.merchant-layout {
  display: flex;
  height: 100%;
  background: var(--bg);
}

.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  flex-shrink: 0;
  background: var(--sidebar-bg);
  color: #f8fafc;
}

.brand-block {
  padding: 28px 20px 20px;
}

.brand-title {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
}

.brand-sub {
  margin-top: 4px;
  font-size: 13px;
  color: #6ee7b7;
}

.sidebar-divider {
  height: 1px;
  margin: 0 12px;
  background: rgba(255, 255, 255, 0.1);
}

.nav-section {
  padding: 16px 12px;
  flex: 1;
  overflow-y: auto;
}

.dev-section {
  flex: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 16px;
}

.section-title {
  padding: 0 12px 10px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
}

.nav-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0;
  padding: 10px 12px 10px 16px;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.92);
  text-decoration: none;
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-link:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.nav-link.active {
  background: rgba(191, 219, 254, 0.18);
  color: #fff;
}

.nav-indicator {
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 24px;
  border-radius: 0 4px 4px 0;
  background: transparent;
  transform: translateY(-50%);
}

.nav-link.active .nav-indicator {
  background: #34d399;
}

.sidebar-foot {
  padding: 14px 20px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.foot-meta {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
}

.main-column {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  height: 100%;
}

.top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  flex-shrink: 0;
  padding: 0 32px;
  background: #fff;
  color: var(--text);
  border-bottom: 1px solid var(--border);
}

.breadcrumb {
  font-size: 14px;
}

.breadcrumb-section {
  font-weight: 500;
  color: var(--muted);
}

.breadcrumb-sep {
  margin: 0 8px;
  color: #cbd5e1;
}

.breadcrumb-title {
  color: var(--text);
}

.top-user {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: var(--text);
}

.logout-btn {
  border: none;
  background: transparent;
  padding: 4px 6px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-radius: 4px;
}

.logout-btn:hover {
  color: var(--primary);
  background: #f8fafc;
}

.content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px 32px;
}

@media (max-width: 900px) {
  .merchant-layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    max-height: 220px;
  }

  .content {
    padding: 16px;
  }
}
</style>
