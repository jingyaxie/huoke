<template>
  <div class="orch-layout">
    <header class="orch-layout-header panel">
      <div class="header-left">
        <router-link to="/test" class="exit-link">← 返回测试入口</router-link>
        <nav class="breadcrumb">
          <span class="crumb-current">Agent 任务编排</span>
        </nav>
      </div>
      <router-link to="/agent" class="agent-link">智能体助手 →</router-link>
    </header>
    <main class="orch-layout-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.orch-layout {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  background: #f0f4f8;
  padding: 12px;
  gap: 12px;
  box-sizing: border-box;
}

.orch-layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.exit-link,
.agent-link {
  font-size: 13px;
  color: #64748b;
  text-decoration: none;
}

.exit-link:hover,
.agent-link:hover {
  color: var(--el-color-primary);
}

.crumb-current {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.orch-layout-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
}
</style>
