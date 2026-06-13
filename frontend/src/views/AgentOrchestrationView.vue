<template>
  <div class="orch-hub">
    <header class="hub-header panel">
      <div class="hub-brand">
        <h1 class="hub-title">任务编排与评测</h1>
        <p class="hub-desc">管理 Agent 异步任务队列，运行基准评测验证 Skill 链路</p>
      </div>
      <div class="hub-actions">
        <el-button :loading="loading" @click="loadJobs">刷新队列</el-button>
        <el-button type="primary" @click="createVisible = true">创建任务</el-button>
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

    <div class="panel jobs-panel">
      <div class="panel-head">
        <h2 class="section-title">任务队列</h2>
        <span class="result-count">共 {{ filteredJobs.length }} 条</span>
      </div>
      <el-table
        v-loading="loading"
        :data="filteredJobs"
        stripe
        class="jobs-table"
        empty-text="暂无任务，点击「创建任务」提交"
        row-class-name="job-row"
        @row-click="openJobDetail"
      >
        <el-table-column prop="job_id" label="Job ID" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <button type="button" class="job-link" @click.stop="openJobDetail(row)">
              <code class="mono">{{ row.job_id }}</code>
            </button>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="light">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stage" label="阶段" width="100" />
        <el-table-column prop="retry_count" label="重试" width="72" align="center" />
        <el-table-column prop="run_id" label="Run ID" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <code v-if="row.run_id" class="mono">{{ row.run_id }}</code>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="168">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="openJobDetail(row)">查看</el-button>
            <el-button
              v-if="row.status === 'pending'"
              link
              type="success"
              size="small"
              @click.stop="executeOneJob(row.job_id)"
            >
              启动
            </el-button>
            <el-button link type="primary" size="small" @click.stop="refreshOneJob(row.job_id)">刷新</el-button>
            <el-button
              v-if="row.status === 'queued' || row.status === 'running'"
              link
              type="danger"
              size="small"
              @click.stop="cancelOneJob(row.job_id)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel benchmark-panel">
      <div class="panel-head">
        <h2 class="section-title">基准评测</h2>
        <el-button type="success" plain size="small" :loading="benchmarkRunning" @click="runBenchmarkNow">
          运行评测
        </el-button>
      </div>
      <p class="bench-hint">JSON 数组，每项含 name 与 message 字段</p>
      <el-input
        v-model="benchmarkCasesText"
        type="textarea"
        :rows="5"
        placeholder='[{"name":"douyin-comments","message":"关键词淋浴房，抓取前3个视频评论并汇总"}]'
      />
      <pre v-if="benchmarkResult" class="bench-result">{{ JSON.stringify(benchmarkResult, null, 2) }}</pre>
    </div>

    <AgentJobCreateDialog
      v-model:visible="createVisible"
      :submitting="jobSubmitting"
      @submit="onCreateJob"
    />

    <AgentJobDetailDialog
      v-model:visible="detailVisible"
      :loading="detailLoading"
      :executing="detailExecuting"
      :job="detailJob"
      @refresh="refreshDetailJob"
      @cancel="cancelFromDetail"
      @execute="executeFromDetail"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import AgentJobCreateDialog from "../components/AgentJobCreateDialog.vue";
import AgentJobDetailDialog from "../components/AgentJobDetailDialog.vue";
import {
  cancelAgentJobTask,
  executeAgentJob,
  fetchAgentJob,
  fetchAgentJobs,
  runAgentBenchmark,
  submitAgentJob,
} from "../api/agent";

const loading = ref(false);
const jobSubmitting = ref(false);
const benchmarkRunning = ref(false);
const errorMessage = ref("");
const createVisible = ref(false);
const detailVisible = ref(false);
const detailLoading = ref(false);
const detailExecuting = ref(false);
const detailJob = ref(null);
const detailJobId = ref("");
const jobs = ref([]);
const filters = ref({ status: "" });
const benchmarkResult = ref(null);
const benchmarkCasesText = ref(
  '[{"name":"douyin-comments","message":"关键词淋浴房，抓取前3个视频评论并汇总"}]',
);
let pollTimer = null;

const STATUS_MAP = {
  pending: "待执行",
  retrying: "重试中",
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const statCards = computed(() => {
  const list = jobs.value;
  return [
    { key: "all", label: "全部", filterValue: "", count: list.length },
    { key: "running", label: "运行中", filterValue: "running", count: list.filter((j) => j.status === "running").length },
    { key: "queued", label: "排队", filterValue: "queued", count: list.filter((j) => j.status === "queued").length },
    { key: "pending", label: "待执行", filterValue: "pending", count: list.filter((j) => j.status === "pending").length },
    { key: "completed", label: "已完成", filterValue: "completed", count: list.filter((j) => j.status === "completed").length },
    { key: "failed", label: "失败", filterValue: "failed", count: list.filter((j) => j.status === "failed" || j.status === "dead_letter").length },
  ];
});

const filteredJobs = computed(() => {
  if (!filters.value.status) return jobs.value;
  if (filters.value.status === "failed") {
    return jobs.value.filter((j) => j.status === "failed" || j.status === "dead_letter");
  }
  return jobs.value.filter((j) => j.status === filters.value.status);
});

function statusLabel(status) {
  return STATUS_MAP[status] || status;
}

function statusTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "retrying") return "warning";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  if (status === "pending") return "info";
  return "warning";
}

function formatTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(value);
  }
}

function applyStatFilter(value) {
  filters.value.status = value;
}

async function loadJobs() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const data = await fetchAgentJobs(50);
    jobs.value = Array.isArray(data) ? data : [];
    schedulePoll();
  } catch (err) {
    errorMessage.value = err.message || "加载任务队列失败";
  } finally {
    loading.value = false;
  }
}

async function onCreateJob(payload) {
  jobSubmitting.value = true;
  try {
    const row = await submitAgentJob(payload);
    ElMessage.success(payload.auto_execute ? "异步任务已提交执行" : "任务已创建，待手动启动");
    createVisible.value = false;
    await loadJobs();
    if (!payload.auto_execute) openJobDetail(row);
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  } finally {
    jobSubmitting.value = false;
  }
}

async function openJobDetail(row) {
  if (!row?.job_id) return;
  detailJobId.value = row.job_id;
  detailJob.value = row;
  detailVisible.value = true;
  await refreshDetailJob();
}

async function refreshDetailJob() {
  if (!detailJobId.value) return;
  detailLoading.value = true;
  try {
    const data = await fetchAgentJob(detailJobId.value);
    detailJob.value = data;
    const idx = jobs.value.findIndex((item) => item.job_id === detailJobId.value);
    if (idx >= 0) jobs.value[idx] = data;
  } catch (err) {
    ElMessage.error(err.message || "加载任务详情失败");
  } finally {
    detailLoading.value = false;
  }
}

async function executeOneJob(jobId) {
  detailExecuting.value = true;
  try {
    const data = await executeAgentJob(jobId);
    const idx = jobs.value.findIndex((item) => item.job_id === jobId);
    if (idx >= 0) jobs.value[idx] = data;
    if (detailJobId.value === jobId) detailJob.value = data;
    ElMessage.success("任务已启动");
    schedulePoll();
  } catch (err) {
    ElMessage.error(err.message || "启动任务失败");
  } finally {
    detailExecuting.value = false;
  }
}

async function executeFromDetail(jobId) {
  await executeOneJob(jobId);
  await refreshDetailJob();
}

async function cancelFromDetail(jobId) {
  await cancelOneJob(jobId);
  await refreshDetailJob();
}

async function refreshOneJob(jobId) {
  try {
    const data = await fetchAgentJob(jobId);
    const idx = jobs.value.findIndex((item) => item.job_id === jobId);
    if (idx >= 0) jobs.value[idx] = data;
    else jobs.value.unshift(data);
  } catch (err) {
    ElMessage.error(err.message || "刷新任务失败");
  }
}

async function cancelOneJob(jobId) {
  try {
    await cancelAgentJobTask(jobId);
    ElMessage.success("已取消任务");
    await refreshOneJob(jobId);
  } catch (err) {
    ElMessage.error(err.message || "取消任务失败");
  }
}

async function runBenchmarkNow() {
  let cases = [];
  try {
    cases = JSON.parse(benchmarkCasesText.value || "[]");
  } catch {
    ElMessage.error("评测 cases JSON 格式无效");
    return;
  }
  if (!Array.isArray(cases) || !cases.length) {
    ElMessage.warning("请至少提供一个评测用例");
    return;
  }
  benchmarkRunning.value = true;
  try {
    benchmarkResult.value = await runAgentBenchmark(cases);
    ElMessage.success("基准评测已完成");
  } catch (err) {
    ElMessage.error(err.message || "评测失败");
  } finally {
    benchmarkRunning.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  const hasActive = jobs.value.some((j) => ["running", "queued", "retrying"].includes(j.status));
  if (!hasActive) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchAgentJobs(50);
      jobs.value = Array.isArray(data) ? data : [];
      if (!jobs.value.some((j) => ["running", "queued", "retrying"].includes(j.status))) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch {
      /* ignore poll errors */
    }
  }, 4000);
}

onMounted(loadJobs);
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.orch-hub {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

.hub-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 20px 24px;
}

.hub-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.hub-desc {
  margin: 0;
  font-size: 14px;
  color: #64748b;
}

.hub-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 8px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
  background: #fff;
  border-radius: 8px;
}

.stat-card:hover,
.stat-card.active {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.1);
}

.stat-num {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
}

.stat-label {
  font-size: 12px;
  color: #94a3b8;
}

.jobs-panel,
.benchmark-panel {
  padding: 16px 20px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #334155;
}

.result-count {
  font-size: 13px;
  color: #94a3b8;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.muted {
  color: #cbd5e1;
}

.bench-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #94a3b8;
}

.bench-result {
  margin: 12px 0 0;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 12px;
  overflow: auto;
  max-height: 280px;
}

:deep(.job-row) {
  cursor: pointer;
}

.job-link {
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
}

.job-link .mono {
  color: var(--el-color-primary);
}

.job-link:hover .mono {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .stats-row {
    grid-template-columns: repeat(3, 1fr);
  }

  .hub-header {
    flex-direction: column;
  }
}
</style>
