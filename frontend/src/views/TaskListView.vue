<template>
  <div class="task-hub">
      <header class="hub-header panel">
        <div class="hub-brand">
          <h1 class="hub-title">任务编排</h1>
          <p class="hub-desc">独立管理所有编排任务，卡片点击查看编排详情与运行情况</p>
        </div>
        <div class="hub-actions">
          <el-button :loading="loading" @click="loadTasks">刷新</el-button>
          <el-button @click="$router.push('/tasks/compile')">编译联调</el-button>
          <el-button type="success" plain :loading="quickTesting" @click="runQuickTest">快速测试</el-button>
          <el-button type="primary" @click="$router.push('/tasks/create')">创建任务</el-button>
        </div>
      </header>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <div class="stats-row">
        <button
          v-for="stat in statCards"
          :key="stat.key"
          type="button"
          class="stat-card panel"
          :class="{ active: filters.status === stat.filterValue }"
          @click="applyStatFilter(stat.filterValue)"
        >
          <span class="stat-num">{{ stat.count }}</span>
          <span class="stat-label">{{ stat.label }}</span>
        </button>
      </div>

      <div class="panel filter-bar">
        <el-form :inline="true">
          <el-form-item label="状态">
            <el-select v-model="filters.status" clearable placeholder="全部" style="width: 130px" @change="loadTasks">
              <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="模板">
            <el-select v-model="filters.template_id" clearable placeholder="全部" style="width: 150px" @change="loadTasks">
              <el-option v-for="tpl in templates" :key="tpl.template_id" :label="tpl.name" :value="tpl.template_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="来源">
            <el-select v-model="filters.source" clearable placeholder="全部" style="width: 110px" @change="loadTasks">
              <el-option label="本地" value="local" />
              <el-option label="外部" value="external" />
            </el-select>
          </el-form-item>
        </el-form>
        <span class="result-count">共 {{ items.length }} 个任务</span>
      </div>

      <div v-loading="loading" class="card-grid">
        <TaskCard
          v-for="task in items"
          :key="task.task_id"
          :task="task"
          @open="goDetail"
          @submit="onSubmit"
        />
      </div>

      <div v-if="!loading && items.length === 0" class="empty-panel panel">
        <div class="empty-icon">📋</div>
        <h3>还没有任务</h3>
        <p>创建任务或通过编译联调导入外部 JSON，任务会以卡片形式展示在此</p>
        <div class="empty-actions">
          <el-button type="primary" @click="$router.push('/tasks/create')">创建任务</el-button>
          <el-button @click="$router.push('/tasks/compile')">编译联调</el-button>
          <el-button type="success" plain :loading="quickTesting" @click="runQuickTest">快速测试</el-button>
        </div>
      </div>
    </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import TaskCard from "../components/TaskCard.vue";
import {
  SAMPLE_YINGXIAOYI_PAYLOAD,
  compileAndCreateTask,
  fetchTaskTemplates,
  fetchTasks,
  submitTask,
} from "../api/tasks";

const router = useRouter();
const loading = ref(false);
const quickTesting = ref(false);
const errorMessage = ref("");
const items = ref([]);
const allItems = ref([]);
const templates = ref([]);
const filters = ref({ status: "", template_id: "", source: "" });
let pollTimer = null;

const statusOptions = [
  { value: "scheduled", label: "已预约" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "运行中" },
  { value: "paused", label: "已暂停" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

const statCards = computed(() => {
  const list = allItems.value;
  return [
    { key: "all", label: "全部", filterValue: "", count: list.length },
    { key: "running", label: "运行中", filterValue: "running", count: list.filter((t) => t.status === "running").length },
    { key: "queued", label: "排队", filterValue: "queued", count: list.filter((t) => t.status === "queued").length },
    { key: "scheduled", label: "已预约", filterValue: "scheduled", count: list.filter((t) => t.status === "scheduled").length },
    { key: "completed", label: "已完成", filterValue: "completed", count: list.filter((t) => t.status === "completed").length },
    { key: "failed", label: "失败", filterValue: "failed", count: list.filter((t) => t.status === "failed").length },
  ];
});

function applyStatFilter(value) {
  filters.value.status = value;
  loadTasks();
}

function goDetail(taskId) {
  router.push(`/tasks/${taskId}`);
}

async function onSubmit(task) {
  try {
    await submitTask(task.task_id);
    ElMessage.success("已提交执行");
    await loadTasks();
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  }
}

async function runQuickTest() {
  quickTesting.value = true;
  errorMessage.value = "";
  try {
    const resp = await compileAndCreateTask({
      raw_payload: {
        ...SAMPLE_YINGXIAOYI_PAYLOAD,
        task_name: `快速测试 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`,
        target_count: 20,
      },
      adapter_id: "yingxiaoyi-lead-v1",
      source: "external",
      auto_submit: false,
    });
    if (!resp.task) {
      throw new Error(resp.compile?.plan?.validation_error || "创建失败");
    }
    ElMessage.success("测试任务已创建");
    router.push(`/tasks/${resp.task.task_id}`);
  } catch (err) {
    errorMessage.value = err.message || "快速测试失败";
  } finally {
    quickTesting.value = false;
  }
}

async function loadTemplates() {
  try {
    const data = await fetchTaskTemplates();
    templates.value = data.items || [];
  } catch {
    templates.value = [];
  }
}

async function loadAllForStats() {
  try {
    const data = await fetchTasks({ limit: 200 });
    allItems.value = data.items || [];
  } catch {
    allItems.value = [];
  }
}

async function loadTasks() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const data = await fetchTasks({
      status: filters.value.status || undefined,
      template_id: filters.value.template_id || undefined,
      source: filters.value.source || undefined,
      limit: 100,
    });
    items.value = data.items || [];
    if (!filters.value.status && !filters.value.template_id && !filters.value.source) {
      allItems.value = items.value;
    } else {
      await loadAllForStats();
    }
    schedulePoll();
  } catch (err) {
    errorMessage.value = err.message || "加载任务失败";
  } finally {
    loading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  const hasRunning = items.value.some(
    (t) => t.status === "running" || t.status === "queued" || t.status === "scheduled",
  );
  if (!hasRunning) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchTasks({
        status: filters.value.status || undefined,
        template_id: filters.value.template_id || undefined,
        source: filters.value.source || undefined,
        limit: 100,
      });
      items.value = data.items || [];
      await loadAllForStats();
      if (!items.value.some((t) => t.status === "running" || t.status === "queued" || t.status === "scheduled")) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch {
      /* ignore */
    }
  }, 3000);
}

onMounted(async () => {
  await loadTemplates();
  await loadTasks();
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.task-hub {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 1280px;
  margin: 0 auto;
  padding-bottom: 8px;
}

.hub-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 20px 22px;
}

.hub-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--primary, #409eff);
}

.hub-desc {
  margin: 0;
  color: #666;
  font-size: 14px;
}

.hub-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  flex-shrink: 0;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}

@media (max-width: 900px) {
  .stats-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 560px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 10px;
  border: 1px solid transparent;
  cursor: pointer;
  background: #fff;
  transition: border-color 0.15s, background 0.15s;
}

.stat-card:hover {
  border-color: var(--el-color-primary-light-7);
}

.stat-card.active {
  border-color: var(--el-color-primary);
  background: #ecf5ff;
}

.stat-num {
  font-size: 22px;
  font-weight: 700;
  color: #333;
  line-height: 1;
}

.stat-label {
  font-size: 12px;
  color: #888;
}

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 4px;
}

.result-count {
  font-size: 13px;
  color: #888;
  padding-bottom: 8px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
  min-height: 120px;
}

.empty-panel {
  text-align: center;
  padding: 48px 24px;
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.empty-panel h3 {
  margin: 0 0 8px;
  font-size: 18px;
}

.empty-panel p {
  margin: 0 0 20px;
  color: #888;
  font-size: 14px;
}

.empty-actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}
</style>
