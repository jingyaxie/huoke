<template>
  <div class="layout">
    <aside class="sidebar panel">
      <div class="brand">抖音热点平台</div>
      <el-menu :default-active="activePath" router>
        <el-menu-item index="/videos">热门视频</el-menu-item>
        <el-menu-item index="/authors">热门作者</el-menu-item>
        <el-menu-item index="/trend">趋势分析</el-menu-item>
        <el-menu-item index="/comments">评论抓取</el-menu-item>
        <el-menu-item index="/reports">热点日报</el-menu-item>
      </el-menu>
    </aside>
    <main class="content">
      <slot />
    </main>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const activePath = computed(() => route.path);
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

.content {
  min-width: 0;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
