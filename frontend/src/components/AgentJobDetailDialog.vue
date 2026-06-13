<template>
  <el-dialog
    :model-value="visible"
    title="任务详情"
    width="760px"
    destroy-on-close
    @update:model-value="$emit('update:visible', $event)"
  >
    <div v-loading="loading" class="detail-body">
      <template v-if="job">
        <div class="detail-head">
          <el-tag :type="statusTagType(job.status)" size="small">{{ statusLabel(job.status) }}</el-tag>
          <span class="stage-text">阶段 · {{ job.stage || "—" }}</span>
          <el-tag v-if="orchestration?.template_name" type="info" size="small" effect="plain">
            {{ orchestration.template_name }}
          </el-tag>
        </div>

        <el-alert
          v-if="executionNote"
          :title="executionNote"
          :type="orchestration?.is_preview ? 'info' : 'success'"
          show-icon
          :closable="false"
          class="detail-alert top-note"
        />

        <div v-if="progressEvents.length" class="progress-block panel-lite">
          <div class="block-head">
            <h4 class="block-title">处理过程</h4>
            <span class="block-hint">{{ progressEvents.length }} 条事件</span>
          </div>
          <ul class="progress-list">
            <li v-for="(evt, idx) in progressEventsDisplayed" :key="idx">
              <span class="evt-time">{{ formatEventTime(evt.at) }}</span>
              <span class="evt-label">{{ evt.label || evt.type }}</span>
            </li>
          </ul>
          <p v-if="progressEvents.length > progressEventsDisplayed.length" class="progress-more">
            仅展示最近 {{ progressEventsDisplayed.length }} 条，完整记录请查看 Run
          </p>
        </div>
        <el-empty
          v-else-if="job.status === 'running' || job.status === 'retrying'"
          description="执行已开始，等待 Agent 事件…"
          :image-size="56"
        />
        <el-empty
          v-else-if="orchestration?.is_preview"
          description="尚未启动执行，编排步骤为静态预览"
          :image-size="56"
        />

        <div v-if="inputSummary" class="summary-block panel-lite">
          <h4 class="block-title">任务摘要</h4>
          <dl class="summary-grid">
            <template v-for="(val, key) in inputSummary" :key="key">
              <dt>{{ summaryLabel(key) }}</dt>
              <dd>{{ val ?? "—" }}</dd>
            </template>
          </dl>
        </div>

        <div v-if="outreachPolicy" class="policy-block panel-lite">
          <h4 class="block-title">触达策略（评论 / 私信分流）</h4>
          <p class="policy-summary">{{ outreachPolicy.rule_summary }}</p>
          <div class="ratio-bar">
            <div class="ratio-seg reply" :style="{ width: `${outreachPolicy.comment_prob_pct}%` }">
              评论 {{ outreachPolicy.comment_ratio }} ({{ outreachPolicy.comment_prob_pct }}%)
            </div>
            <div class="ratio-seg dm" :style="{ width: `${outreachPolicy.dm_prob_pct}%` }">
              私信 {{ outreachPolicy.dm_ratio }} ({{ outreachPolicy.dm_prob_pct }}%)
            </div>
          </div>
          <dl class="summary-grid policy-grid">
            <dt>随机规则</dt>
            <dd>每条线索按权重随机，实现类 <code>choose_outreach_action</code></dd>
            <dt>动作间隔</dt>
            <dd>{{ outreachPolicy.interval_min_sec }}~{{ outreachPolicy.interval_max_sec }} 秒</dd>
            <dt>日配额</dt>
            <dd>
              评论回复 ≤ {{ outreachPolicy.daily_limits?.max_comment_replies ?? "—" }} ·
              关注 ≤ {{ outreachPolicy.daily_limits?.max_follows ?? "—" }} ·
              私信 ≤ {{ outreachPolicy.daily_limits?.max_dms ?? "—" }}
            </dd>
          </dl>
        </div>

        <div v-if="orchestrationSteps.length" class="orch-block panel-lite">
          <div class="block-head">
            <h4 class="block-title">编排步骤</h4>
            <span class="block-hint">{{ orchestrationHint }}</span>
          </div>
          <div class="workflow-steps">
            <div
              v-for="(step, idx) in orchestrationSteps"
              :key="step.id || idx"
              class="workflow-step"
              :class="stepStatusClass(step.status)"
            >
              <div class="step-index">{{ step.order || idx + 1 }}</div>
              <div class="step-body">
                <div class="step-id">{{ step.id || step.stage }}</div>
                <div class="step-action">{{ step.action }}</div>
                <div v-if="step.capability" class="step-cap">{{ step.capability }}</div>
                <ul v-if="step.sub_steps?.length" class="sub-steps">
                  <li v-for="sub in step.sub_steps" :key="sub.action">
                    <strong>{{ sub.label }}</strong>
                    <span class="sub-weight">权重 {{ sub.weight }} · 约 {{ sub.prob_pct }}%</span>
                    <span class="sub-desc">{{ sub.description }}</span>
                  </li>
                </ul>
              </div>
              <el-tag size="small" :type="stepTagType(step.status)" effect="light">
                {{ stepStatusLabel(step.status) }}
              </el-tag>
            </div>
          </div>
          <p v-if="orchestration?.reasoning" class="orch-reason">{{ orchestration.reasoning }}</p>
          <router-link v-if="linkedTaskId" :to="`/tasks/${linkedTaskId}`" class="task-link">
            在任务中心查看结构化任务 →
          </router-link>
        </div>

        <dl class="meta-grid">
          <dt>Job ID</dt>
          <dd><code class="mono">{{ job.job_id }}</code></dd>
          <dt v-if="!inputSummary">任务内容</dt>
          <dd v-if="!inputSummary" class="message-cell">{{ job.message || "—" }}</dd>
          <dt>模型 / 模式</dt>
          <dd>{{ job.provider || "—" }} · {{ job.mode || "—" }} · {{ runModeLabel(job.run_mode) }}</dd>
          <dt>平台 / 账号</dt>
          <dd>{{ job.platform || "—" }} · {{ job.account_id || "—" }}</dd>
          <dt>调度</dt>
          <dd>
            优先级 {{ job.priority ?? "—" }} · 重试 {{ job.retry_count ?? 0 }}/{{ job.max_retries ?? "—" }} ·
            超时 {{ job.timeout_seconds ?? "—" }}s · {{ job.auto_execute ? "自动执行" : "手动启动" }} ·
            {{ job.auto_restart ? "失败自动重启" : "失败即停" }}
          </dd>
          <dt>Run ID</dt>
          <dd>
            <code v-if="job.run_id" class="mono link-code" @click="openRun">{{ job.run_id }}</code>
            <span v-else class="muted">—</span>
          </dd>
          <dt>Session ID</dt>
          <dd><code v-if="job.session_id" class="mono">{{ job.session_id }}</code><span v-else class="muted">—</span></dd>
          <dt>创建时间</dt>
          <dd>{{ formatTime(job.created_at) }}</dd>
          <dt>更新时间</dt>
          <dd>{{ formatTime(job.updated_at) }}</dd>
        </dl>

        <el-alert v-if="job.error" :title="job.error" type="error" show-icon :closable="false" class="detail-alert" />
        <el-alert
          v-if="job.dead_letter_reason"
          :title="`死信原因：${job.dead_letter_reason}`"
          type="warning"
          show-icon
          :closable="false"
          class="detail-alert"
        />

        <details v-if="parsedMessage" class="raw-block">
          <summary>原始 JSON</summary>
          <pre class="result-pre">{{ JSON.stringify(parsedMessage, null, 2) }}</pre>
        </details>

        <div v-if="executionSummary" class="result-block">
          <h4 class="block-title">执行摘要</h4>
          <p class="exec-summary">{{ executionSummary }}</p>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="未找到任务" />
    </div>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
      <el-button
        v-if="job?.status === 'pending'"
        type="primary"
        :loading="executing"
        @click="$emit('execute', job.job_id)"
      >
        启动执行
      </el-button>
      <el-button v-if="job?.run_id" type="primary" plain @click="openRun">查看 Run</el-button>
      <el-button
        v-if="canSubmitToTaskCenter"
        type="success"
        plain
        :loading="submittingTask"
        @click="submitToTaskCenter"
      >
        提交到任务中心
      </el-button>
      <el-button :loading="loading" @click="$emit('refresh')">刷新</el-button>
      <el-button
        v-if="job && (job.status === 'queued' || job.status === 'running')"
        type="danger"
        plain
        @click="$emit('cancel', job.job_id)"
      >
        取消任务
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { compileAndCreateTask } from "../api/tasks";

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  executing: { type: Boolean, default: false },
  job: { type: Object, default: null },
});

const emit = defineEmits(["update:visible", "refresh", "cancel", "execute"]);

const router = useRouter();
const submittingTask = ref(false);
let detailPollTimer = null;

const SUMMARY_LABELS = {
  task_name: "任务名称",
  keyword: "关键词",
  platform: "平台",
  region: "地区",
  target_leads: "目标线索",
  comment_days: "评论天数",
  video_publish_days: "视频发布天数",
  comment_ratio: "评论权重",
  dm_ratio: "私信权重",
  interval_sec: "触达间隔",
  daily_follow_limit: "日关注上限",
  daily_dm_limit: "日私信上限",
};

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

const STEP_STATUS_MAP = {
  pending: "待执行",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const orchestration = computed(() => {
  const r = props.job?.result;
  if (r?.orchestration && typeof r.orchestration === "object") return r.orchestration;
  if (Array.isArray(r?.pipeline) && r.pipeline.length) {
    return { source: "legacy", steps: r.pipeline };
  }
  return null;
});

const outreachPolicy = computed(() => orchestration.value?.outreach_policy || null);

const executionNote = computed(() => orchestration.value?.execution_note || "");

const progressEvents = computed(() => {
  const events = props.job?.result?.progress_events;
  return Array.isArray(events) ? events : [];
});

const progressEventsDisplayed = computed(() => progressEvents.value.slice(-20).reverse());

const canSubmitToTaskCenter = computed(() => {
  const src = orchestration.value?.source;
  return src === "yingxiaoyi" || !!parsedMessage.value?.keyword || !!parsedMessage.value?.raw_payload;
});

const orchestrationSteps = computed(() => orchestration.value?.steps || []);

const orchestrationHint = computed(() => {
  const src = orchestration.value?.source;
  if (src === "yingxiaoyi") return "由盈小蚁 JSON 编译预览";
  if (src === "task_template") return "任务模板编排";
  if (src === "slash_command") return "Pipeline 指令编排";
  if (src === "agent") return "Agent 内置执行流水线";
  return "编排预览";
});

const parsedMessage = computed(() => {
  const text = props.job?.message?.trim();
  if (!text?.startsWith("{")) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
});

const inputSummary = computed(() => {
  const fromOrch = orchestration.value?.input_summary;
  if (fromOrch && Object.keys(fromOrch).length) {
    return Object.fromEntries(Object.entries(fromOrch).filter(([, v]) => v != null && v !== ""));
  }
  if (!parsedMessage.value) return null;
  const raw = parsedMessage.value;
  return Object.fromEntries(
    Object.entries({
      task_name: raw.task_name,
      keyword: raw.keyword || raw.product_keyword,
      platform: raw.platform || raw.channel,
      region: raw.region,
      target_leads: raw.target_count || raw.target_leads,
      comment_days: raw.comment_days,
      video_publish_days: raw.video_publish_days,
      comment_ratio: raw.comment_ratio,
      dm_ratio: raw.dm_ratio,
    }).filter(([, v]) => v != null && v !== ""),
  );
});

const linkedTaskId = computed(() => {
  const ref = parsedMessage.value?.external_ref || parsedMessage.value?.task_id;
  return typeof ref === "string" && ref.startsWith("task_") ? ref : "";
});

const executionSummary = computed(() => props.job?.result?.summary || "");

function summaryLabel(key) {
  return SUMMARY_LABELS[key] || key;
}

function statusLabel(status) {
  return STATUS_MAP[status] || status;
}

function stepStatusLabel(status) {
  return STEP_STATUS_MAP[status] || status || "待执行";
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

function stepTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  return "info";
}

function stepStatusClass(status) {
  if (status === "running") return "is-running";
  if (status === "completed") return "is-done";
  if (status === "failed" || status === "dead_letter" || status === "cancelled") return "is-error";
  return "";
}

function runModeLabel(mode) {
  if (mode === "confirm") return "工具需审批";
  if (mode === "auto") return "工具自动批准";
  return mode || "—";
}

function formatTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return String(value);
  }
}

function formatEventTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(value);
  }
}

function buildTaskCenterPayload() {
  const msg = props.job?.message?.trim();
  if (!msg) return null;
  try {
    const parsed = JSON.parse(msg);
    if (parsed?.raw_payload && typeof parsed.raw_payload === "object") {
      return {
        adapter_id: parsed.adapter_id || "yingxiaoyi-lead-v1",
        intent: parsed.intent || "lead_acquisition",
        raw_payload: parsed.raw_payload,
        async: parsed.async !== false,
        auto_submit: parsed.auto_submit !== false,
      };
    }
    if (parsed?.keyword || parsed?.task_name) {
      return {
        adapter_id: "yingxiaoyi-lead-v1",
        intent: "lead_acquisition",
        raw_payload: parsed,
        async: true,
        auto_submit: true,
      };
    }
  } catch {
    /* not json */
  }
  return null;
}

async function submitToTaskCenter() {
  const payload = buildTaskCenterPayload();
  if (!payload) {
    ElMessage.warning("无法从任务内容解析盈小蚁 JSON");
    return;
  }
  submittingTask.value = true;
  try {
    const resp = await compileAndCreateTask(payload);
    const taskId = resp?.task?.task_id;
    if (!taskId) {
      ElMessage.error(resp?.compile?.plan?.validation_error || "编译创建失败");
      return;
    }
    ElMessage.success("已提交到任务中心");
    emit("update:visible", false);
    router.push(`/tasks/${taskId}`);
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  } finally {
    submittingTask.value = false;
  }
}

function scheduleDetailPoll() {
  if (detailPollTimer) clearInterval(detailPollTimer);
  const active = props.visible && props.job && ["running", "queued", "retrying"].includes(props.job.status);
  if (!active) return;
  detailPollTimer = setInterval(() => emit("refresh"), 2500);
}

watch(
  () => [props.visible, props.job?.status, props.job?.job_id],
  () => scheduleDetailPoll(),
  { immediate: true },
);

onUnmounted(() => {
  if (detailPollTimer) clearInterval(detailPollTimer);
});

function openRun() {
  if (!props.job?.run_id) return;
  localStorage.setItem("huoke_agent_run_id", props.job.run_id);
  router.push("/agent");
}
</script>

<style scoped>
.detail-body {
  min-height: 120px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.stage-text {
  font-size: 13px;
  color: #64748b;
}

.top-note {
  margin-bottom: 12px;
}

.progress-block {
  margin-bottom: 14px;
}

.progress-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 220px;
  overflow: auto;
}

.progress-list li {
  display: flex;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed #e2e8f0;
  font-size: 12px;
}

.evt-time {
  flex-shrink: 0;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.evt-label {
  color: #334155;
}

.progress-more {
  margin: 8px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.policy-block {
  margin-bottom: 14px;
}

.policy-summary {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #475569;
}

.ratio-bar {
  display: flex;
  height: 28px;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 10px;
  font-size: 11px;
  font-weight: 600;
}

.ratio-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ratio-seg.reply {
  background: #dbeafe;
  color: #1d4ed8;
}

.ratio-seg.dm {
  background: #fce7f3;
  color: #be185d;
}

.policy-grid {
  margin-top: 4px;
}

.sub-steps {
  margin: 8px 0 0;
  padding-left: 16px;
  list-style: disc;
  font-size: 12px;
  color: #64748b;
}

.sub-steps li {
  margin-bottom: 4px;
}

.sub-weight {
  margin-left: 6px;
  color: #94a3b8;
}

.sub-desc {
  display: block;
  margin-top: 2px;
  color: #94a3b8;
}

.panel-lite {
  padding: 12px 14px;
  background: #f8fafc;
  border-radius: 8px;
  margin-bottom: 14px;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.block-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #475569;
}

.block-head .block-title {
  margin: 0;
}

.block-hint {
  font-size: 12px;
  color: #94a3b8;
}

.summary-grid {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}

.summary-grid dt {
  margin: 0;
  color: #94a3b8;
}

.summary-grid dd {
  margin: 0;
  color: #334155;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.workflow-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.workflow-step.is-running {
  border-color: var(--el-color-primary-light-5);
  background: #eff6ff;
}

.workflow-step.is-done {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.workflow-step.is-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.step-index {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-id {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
}

.step-action {
  font-size: 14px;
  color: #1e293b;
  margin-top: 2px;
}

.step-cap {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.orch-reason {
  margin: 10px 0 0;
  font-size: 12px;
  color: #64748b;
}

.task-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 13px;
}

.meta-grid {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 10px 16px;
  margin: 0;
  font-size: 13px;
}

.meta-grid dt {
  margin: 0;
  color: #94a3b8;
}

.meta-grid dd {
  margin: 0;
  color: #334155;
  word-break: break-word;
}

.message-cell {
  white-space: pre-wrap;
  line-height: 1.5;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.link-code {
  color: var(--el-color-primary);
  cursor: pointer;
}

.link-code:hover {
  text-decoration: underline;
}

.muted {
  color: #cbd5e1;
}

.detail-alert {
  margin-top: 12px;
}

.raw-block {
  margin-top: 12px;
}

.raw-block summary {
  cursor: pointer;
  font-size: 13px;
  color: #64748b;
}

.result-block {
  margin-top: 16px;
}

.exec-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.result-pre {
  margin: 8px 0 0;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 12px;
  overflow: auto;
  max-height: 200px;
}
</style>
