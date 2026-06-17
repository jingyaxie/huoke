<template>
  <div class="merchant-layout">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="brand-title">AI获客</div>
        <div class="brand-sub">盈小蚁 · 客户后台</div>
      </div>

      <div class="sidebar-divider" />

      <nav class="nav-scroll">
        <template v-if="portalEnabled">
          <div v-for="section in cloudNavSections" :key="section.label" class="nav-section">
            <div class="section-title">{{ section.label }}</div>
            <router-link
              v-for="item in section.items"
              :key="item.to"
              :to="item.to"
              class="nav-link"
              :class="{ active: isActive(item.to) }"
            >
              <span class="nav-indicator" />
              <span>{{ item.label }}</span>
            </router-link>
          </div>

          <div class="nav-section">
            <div class="section-title">AI获客管理</div>
            <router-link
              v-for="item in localNavItems"
              :key="item.to"
              :to="item.to"
              class="nav-link nav-link-local"
              :class="{ active: isActive(item.to) }"
            >
              <span class="nav-indicator" />
              <span>{{ item.label }}</span>
            </router-link>
          </div>
        </template>

        <template v-else>
          <div class="nav-section">
            <div class="section-title">{{ localNavSection.label }}</div>
            <router-link
              v-for="item in localNavItems"
              :key="item.to"
              :to="item.to"
              class="nav-link"
              :class="{ active: isActive(item.to) }"
            >
              <span class="nav-indicator" />
              <span>{{ item.label }}</span>
            </router-link>
          </div>
        </template>
      </nav>

      <div class="sidebar-foot">
        <div class="foot-meta">v{{ appVersion }} · {{ portalEnabled ? "云端+本机" : "本地独立运行" }}</div>
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
          <button v-if="portalEnabled && portalLoggedIn" type="button" class="logout-btn" @click="handlePortalLogout">
            退出云端
          </button>
        </div>
      </header>

      <main class="content" :class="{ 'content-embed': isCloudRoute }">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  CLOUD_NAV_SECTIONS,
  getRouteMeta,
  LOCAL_NAV_SECTION,
} from "../config/cloudNav";
import { getTenantId } from "../api/http";
import {
  clearPortalAuth,
  getPortalDisplayName,
  isPortalAuthenticated,
  isPortalEnabled,
} from "../utils/portalShell";

const route = useRoute();
const router = useRouter();

const portalEnabled = isPortalEnabled();
const cloudNavSections = CLOUD_NAV_SECTIONS.filter((s) => s.label !== "AI获客管理");
const localNavSection = LOCAL_NAV_SECTION;
const localNavItems = LOCAL_NAV_SECTION.items;

const portalLoggedIn = ref(isPortalAuthenticated());

const appVersion = computed(() => import.meta.env.VITE_APP_VERSION || "0.2.0");
const isCloudRoute = computed(() => Boolean(route.meta?.cloud) || route.path.startsWith("/cloud/"));

const displayName = computed(() => {
  if (portalLoggedIn.value) {
    const portalName = getPortalDisplayName();
    if (portalName) return portalName;
  }
  return getTenantId() || "用户";
});

const breadcrumbSection = computed(() => {
  const meta = route.meta?.section || getRouteMeta(route.path)?.section;
  return meta || (isCloudRoute.value ? "客户后台" : "AI 获客");
});

const breadcrumbTitle = computed(() => {
  const meta = route.meta?.title || getRouteMeta(route.path)?.title;
  return meta || "盈小蚁";
});

function isActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`);
}

function onPortalAuthChanged() {
  portalLoggedIn.value = isPortalAuthenticated();
}

function handlePortalLogout() {
  clearPortalAuth();
  portalLoggedIn.value = false;
  ElMessage.success("已退出云端登录");
  router.push("/auto-tasks").catch(() => {});
}

onMounted(() => {
  window.addEventListener("huoke-portal-auth-changed", onPortalAuthChanged);
});

onUnmounted(() => {
  window.removeEventListener("huoke-portal-auth-changed", onPortalAuthChanged);
});
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

.nav-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.nav-section {
  padding: 16px 12px 8px;
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

.nav-link-local {
  color: #a7f3d0;
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

.content-embed {
  padding: 0;
  overflow: hidden;
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
