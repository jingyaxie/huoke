<template>
  <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">{{ task?.name || "任务详情" }}</h2>
          <p v-if="task" class="page-subtitle">
            模板 {{ task.template_id }} · {{ task.platform }} · {{ task.source === "external" ? "外部" : "本地" }}
          </p>
        </div>
        <div v-if="task" class="header-actions">
          <el-button :loading="loading" @click="reload">刷新</el-button>
          <el-button v-if="canSubmit" type="success" :loading="submitting" @click="onSubmit">提交执行</el-button>
          <el-button v-if="hasCompileReport" plain @click="onRecompileTest">重新编译测试</el-button>
          <el-button v-if="task.status === 'running'" @click="onPause">暂停</el-button>
          <el-button v-if="task.status === 'paused'" type="primary" @click="onResume">恢复</el-button>
          <el-button
            v-if="['queued', 'running', 'paused', 'scheduled'].includes(task.status)"
            type="danger"
            plain
            @click="onCancel"
          >
            取消
          </el-button>
        </div>
      </div>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <div v-if="task" class="panel summary-panel">
        <div class="summary-row">
          <span>状态</span>
          <el-tag :type="statusTagType(task.status)">{{ statusLabel(task.status) }}</el-tag>
        </div>
        <div class="summary-row">
          <span>进度</span>
          <el-progress :percentage="task.progress?.overall_percent || 0" :stroke-width="10" style="flex: 1" />
        </div>
        <div v-if="task.scheduled_at" class="summary-row">
          <span>计划执行</span>
          <span>{{ formatTime(task.scheduled_at) }}</span>
        </div>
        <div v-if="task.current_phase" class="summary-row">
          <span>当前阶段</span>
          <code>{{ task.current_phase }}</code>
        </div>
        <div v-if="task.error" class="summary-row error-row">
          <span>错误</span>
          <span>{{ task.error }}</span>
        </div>
      </div>

      <div v-if="templatePhases.length" class="panel workflow-panel">
        <h3 class="section-title">任务编排流程</h3>
        <div class="workflow-steps">
          <div
            v-for="(phase, idx) in templatePhases"
            :key="phase.id"
            class="workflow-step"
            :class="phaseStatusClass(phase.id)"
          >
            <div class="step-index">{{ idx + 1 }}</div>
            <div class="step-body">
              <div class="step-id">{{ phase.id }}</div>
              <div class="step-cap">{{ phase.capability }}</div>
              <div v-if="phaseRunLabel(phase.id)" class="step-run">{{ phaseRunLabel(phase.id) }}</div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="task" class="panel test-panel">
        <h3 class="section-title">运行与测试</h3>
        <dl class="meta-grid">
          <dt>任务 ID</dt>
          <dd><code>{{ task.task_id }}</code></dd>
          <dt>执行器</dt>
          <dd>{{ task.template_id }} / {{ task.template_version }}</dd>
          <dt>账号</dt>
          <dd>{{ task.account_id }}</dd>
          <dt v-if="task.adapter_id">Adapter</dt>
          <dd v-if="task.adapter_id">{{ task.adapter_id }}</dd>
        </dl>
        <p class="test-hint">
          「提交执行」将任务放入 worker 队列运行；「重新编译测试」用原始 JSON 再次编译，不修改当前任务。
        </p>
        <pre v-if="recompilePreview" class="code-block recompile-preview">{{ formatJson(recompilePreview) }}</pre>
      </div>

      <el-tabs v-if="task" v-model="activeTab" class="panel">
        <el-tab-pane label="运行情况" name="runtime">
          <el-table :data="phases" stripe size="small" empty-text="暂无阶段日志（提交执行后产生）">
            <el-table-column prop="phase_id" label="阶段" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="attempt" label="次数" width="70" />
            <el-table-column label="开始" width="160">
              <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
            </el-table-column>
            <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
          </el-table>
          <details v-if="phases.length" class="phase-details">
            <summary>阶段输入/输出快照</summary>
            <div v-for="p in phases" :key="p.id" class="phase-snapshot">
              <h4>{{ p.phase_id }} · {{ p.status }}</h4>
              <pre class="code-block">{{ formatJson({ input: p.input_snapshot, output: p.output_snapshot }) }}</pre>
            </div>
          </details>
        </el-tab-pane>
        <el-tab-pane label="编排 Spec" name="spec">
          <pre class="code-block">{{ formatJson(task.spec) }}</pre>
        </el-tab-pane>
        <el-tab-pane label="编译报告" name="compile">
          <div v-if="!hasCompileReport" class="empty-hint">此任务无编译快照（可能由本地表单直接创建）</div>
          <template v-else>
            <div class="compile-meta">
              <el-tag v-if="compilePlan.method" type="info">{{ methodLabel(compilePlan.method) }}</el-tag>
              <el-tag v-if="compilePlan.confidence != null">
                置信度 {{ Math.round((compilePlan.confidence || 0) * 100) }}%
              </el-tag>
              <el-tag v-if="compilePlan.validation_ok === false" type="danger">校验失败</el-tag>
              <el-tag v-else type="success">校验通过</el-tag>
            </div>
            <p v-if="compilePlan.reasoning" class="reasoning">{{ compilePlan.reasoning }}</p>
            <div v-if="compilePlan.unmapped_fields?.length" class="unmapped">
              未映射：{{ compilePlan.unmapped_fields.join(", ") }}
            </div>
            <div class="compare-grid">
              <div>
                <h4 class="compare-title">原始 JSON</h4>
                <pre class="code-block">{{ formatJson(task.raw_payload) }}</pre>
              </div>
              <div>
                <h4 class="compare-title">编译 Spec</h4>
                <pre class="code-block">{{ formatJson(compilePlan.spec || task.spec) }}</pre>
              </div>
            </div>
          </template>
        </el-tab-pane>
        <el-tab-pane label="执行结果" name="result">
          <pre class="code-block">{{ formatJson(task.result || {}) }}</pre>
        </el-tab-pane>
      </el-tabs>
    </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { cancelTask, compileTask, fetchTask, fetchTaskPhases, fetchTaskTemplate, pauseTask, resumeTask, submitTask } from "../api/tasks";

const route = useRoute();
const loading = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
const task = ref(null);
const phases = ref([]);
const templatePhases = ref([]);
const recompilePreview = ref(null);
const activeTab = ref("runtime");
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

const compilePlan = computed(() => task.value?.compile_plan || {});
const hasCompileReport = computed(
  () => Boolean(task.value?.raw_payload) || Boolean(task.value?.compile_plan),
);
const canSubmit = computed(() => {
  const s = task.value?.status;
  return s === "queued" || s === "failed" || s === "paused" || s === "scheduled";
});

function statusLabel(status) {
  return statusOptions.find((o) => o.value === status)?.label || status;
}

function statusTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "paused") return "warning";
  if (status === "scheduled") return "warning";
  return "info";
}

function methodLabel(method) {
  if (method === "rule") return "规则编译";
  if (method === "llm") return "LLM 编译";
  if (method === "hybrid") return "混合编译";
  return method;
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function formatTime(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}

function findPhaseRun(phaseId) {
  const direct = phases.value.find((p) => p.phase_id === phaseId);
  if (direct) return direct;
  if (phaseId === "crawl") {
    return phases.value.find((p) => p.phase_id === "execute" || p.phase_id === "crawl");
  }
  return null;
}

function phaseRunLabel(phaseId) {
  const run = findPhaseRun(phaseId);
  if (!run) return "";
  return `${run.status}${run.attempt > 1 ? ` · 第${run.attempt}次` : ""}`;
}

function phaseStatusClass(phaseId) {
  const run = findPhaseRun(phaseId);
  if (run?.status === "completed") return "done";
  if (run?.status === "running") return "active";
  if (run?.status === "failed") return "failed";
  const current = task.value?.current_phase;
  const status = task.value?.status;
  if (status === "completed") return "done";
  if (current === phaseId || (current === "crawl" && phaseId === "crawl")) return "active";
  if (
    current &&
    templatePhases.value.findIndex((p) => p.id === phaseId) <
      templatePhases.value.findIndex((p) => p.id === current)
  ) {
    return "done";
  }
  return "pending";
}

async function loadTemplatePhases() {
  if (!task.value?.template_id) return;
  try {
    const tpl = await fetchTaskTemplate(task.value.template_id, task.value.template_version);
    templatePhases.value = tpl.phases || [];
  } catch {
    templatePhases.value = [];
  }
}

async function reload() {
  const taskId = route.params.taskId;
  if (!taskId) return;
  loading.value = true;
  errorMessage.value = "";
  try {
    task.value = await fetchTask(taskId);
    if (task.value?.compile_plan || task.value?.raw_payload) {
      activeTab.value = "compile";
    } else {
      activeTab.value = "runtime";
    }
    const phaseData = await fetchTaskPhases(taskId);
    phases.value = phaseData.items || [];
    await loadTemplatePhases();
    schedulePoll();
  } catch (err) {
    errorMessage.value = err.message || "加载失败";
  } finally {
    loading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  if (!task.value || !["running", "queued"].includes(task.value.status)) return;
  pollTimer = setInterval(async () => {
    try {
      task.value = await fetchTask(route.params.taskId);
      if (!["running", "queued"].includes(task.value.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
        const phaseData = await fetchTaskPhases(route.params.taskId);
        phases.value = phaseData.items || [];
      }
    } catch {
      /* ignore */
    }
  }, 3000);
}

async function onSubmit() {
  submitting.value = true;
  try {
    task.value = await submitTask(route.params.taskId);
    ElMessage.success("已提交执行");
    schedulePoll();
    const phaseData = await fetchTaskPhases(route.params.taskId);
    phases.value = phaseData.items || [];
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  } finally {
    submitting.value = false;
  }
}

async function onRecompileTest() {
  if (!task.value?.raw_payload) return;
  try {
    const resp = await compileTask({
      raw_payload: task.value.raw_payload,
      adapter_id: task.value.adapter_id || "yingxiaoyi-lead-v1",
      source: "external",
    });
    recompilePreview.value = resp;
    activeTab.value = "compile";
    ElMessage.success(resp.ok ? "重新编译通过" : "编译未通过，请查看编译报告");
  } catch (err) {
    ElMessage.error(err.message || "编译测试失败");
  }
}

async function onPause() {
  try {
    task.value = await pauseTask(route.params.taskId);
    ElMessage.success("已请求暂停");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function onResume() {
  try {
    task.value = await resumeTask(route.params.taskId);
    ElMessage.success("已恢复执行");
    schedulePoll();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function onCancel() {
  try {
    await ElMessageBox.confirm("确定取消此任务？", "取消任务", { type: "warning" });
    task.value = await cancelTask(route.params.taskId);
    ElMessage.success("任务已取消");
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "取消失败");
  }
}

watch(
  () => route.params.taskId,
  () => reload(),
);

onMounted(() => reload());
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.back-btn {
  padding-left: 0;
  margin-bottom: 4px;
}
.page-title {
  margin: 0 0 6px;
}
.page-subtitle {
  margin: 0;
  color: #666;
  font-size: 14px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.summary-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.summary-row span:first-child {
  width: 80px;
  color: #888;
  font-size: 13px;
}
.error-row span:last-child {
  color: var(--el-color-danger);
}
.section-title {
  margin: 0 0 12px;
  font-size: 15px;
}
.workflow-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.workflow-step {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  min-width: 160px;
}
.workflow-step.active {
  border-color: var(--el-color-primary);
  background: #ecf5ff;
}
.workflow-step.done {
  border-color: var(--el-color-success-light-5);
  background: #f0f9eb;
}
.workflow-step.failed {
  border-color: var(--el-color-danger-light-5);
  background: #fef0f0;
}
.step-run {
  font-size: 11px;
  color: var(--el-color-primary);
  margin-top: 4px;
}
.test-panel {
  padding-bottom: 16px;
}
.meta-grid {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px 12px;
  margin: 0 0 12px;
  font-size: 13px;
}
.meta-grid dt {
  color: #888;
  margin: 0;
}
.meta-grid dd {
  margin: 0;
}
.test-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: #666;
}
.recompile-preview {
  max-height: 240px;
}
.phase-details {
  margin-top: 16px;
}
.phase-snapshot {
  margin-top: 12px;
}
.phase-snapshot h4 {
  margin: 0 0 8px;
  font-size: 13px;
}
.step-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #eee;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.workflow-step.active .step-index {
  background: var(--el-color-primary);
  color: #fff;
}
.step-id {
  font-weight: 600;
  font-size: 13px;
}
.step-cap {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
}
.compile-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.reasoning {
  margin: 0 0 8px;
  color: #555;
  font-size: 13px;
}
.unmapped {
  margin-bottom: 12px;
  font-size: 12px;
  color: #888;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 900px) {
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
.compare-title {
  margin: 0 0 8px;
  font-size: 13px;
  color: #666;
}
.empty-hint {
  color: #999;
  padding: 12px 0;
}
.code-block {
  margin: 0;
  padding: 12px;
  background: #f6f8fa;
  border-radius: 6px;
  overflow: auto;
  font-size: 12px;
  max-height: 480px;
}
</style>
