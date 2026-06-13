<template>
  <MainLayout>
    <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">测试入口</h2>
          <p class="page-subtitle">
            传统 REST / Skill API 与 Agent 模式均可在此快速验证；完整接口文档见
            <router-link to="/external-api">对外接口 API</router-link>
          </p>
        </div>
        <div class="header-actions">
          <el-button :loading="healthLoading" @click="checkHealthStatus">健康检查</el-button>
          <el-button @click="openSwagger">OpenAPI</el-button>
          <el-button type="primary" plain @click="$router.push('/agent')">完整 Agent 界面</el-button>
        </div>
      </div>

      <el-alert
        v-if="healthStatus"
        :title="healthStatus"
        :type="healthOk ? 'success' : 'error'"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <el-tabs v-model="activeTab" class="test-tabs panel">
        <el-tab-pane label="传统 API 调用" name="api">
          <div class="tab-section">
            <h3 class="section-title">Pipeline · 关键词视频+评论</h3>
            <p class="section-desc">
              调用 <code>POST /api/agent/pipeline/keyword-video-comments</code>，走 Skill 统一链路（T0 → T1 → T2）。
            </p>
            <el-form label-width="110px" class="compact-form">
              <el-form-item label="关键词" required>
                <el-input v-model="pipelineForm.keyword" placeholder="例如：淋浴房" />
              </el-form-item>
              <el-form-item label="平台">
                <el-checkbox-group v-model="pipelineForm.platforms">
                  <el-checkbox value="douyin">抖音</el-checkbox>
                  <el-checkbox value="xiaohongshu">小红书</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
              <el-form-item label="视频数量">
                <el-input-number v-model="pipelineForm.video_limit" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label="强制拉取">
                <el-switch v-model="pipelineForm.force_refresh" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="pipelineLoading" @click="runPipeline">调用 Pipeline</el-button>
              </el-form-item>
            </el-form>
            <pre v-if="pipelineResult" class="code-block result-json">{{ formatJson(pipelineResult) }}</pre>
          </div>

          <div class="tab-section">
            <h3 class="section-title">Skill Execute · 同步执行</h3>
            <p class="section-desc">
              调用 <code>POST /api/agent/skills/execute</code>，适用于 builtin Skill 与平台 REST 等价能力。
            </p>
            <el-form label-width="110px" class="compact-form">
              <el-form-item label="Skill ID" required>
                <el-input v-model="skillForm.skill_id" placeholder="douyin-keyword-comments" />
              </el-form-item>
              <el-form-item label="平台">
                <el-select v-model="skillForm.platform">
                  <el-option label="douyin" value="douyin" />
                  <el-option label="xiaohongshu" value="xiaohongshu" />
                  <el-option label="kuaishou" value="kuaishou" />
                </el-select>
              </el-form-item>
              <el-form-item label="参数 JSON">
                <el-input
                  v-model="skillForm.paramsText"
                  type="textarea"
                  :rows="4"
                  placeholder='{"keyword":"护肤","limit":3,"days":3}'
                />
              </el-form-item>
              <el-form-item label="Agent 兜底">
                <el-switch v-model="skillForm.agent_fallback" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="skillLoading" @click="runSkillExecute">执行 Skill</el-button>
                <el-button :loading="skillsLoading" @click="loadSkills">列出 Skill</el-button>
              </el-form-item>
            </el-form>
            <pre v-if="skillResult" class="code-block result-json">{{ formatJson(skillResult) }}</pre>
            <pre v-if="skillsList" class="code-block result-json">{{ formatJson(skillsList) }}</pre>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Agent 模式" name="agent">
          <div class="tab-section">
            <h3 class="section-title">Agent 同步对话</h3>
            <p class="section-desc">
              调用 <code>POST /api/agent/chat/sync</code>，阻塞等待任务结束。复杂任务或需审批/plan 时请使用
              <router-link to="/agent">完整 Agent 界面</router-link>（SSE 流式 + 浏览器预览）。
            </p>
            <el-form label-width="110px" class="compact-form">
              <el-form-item label="消息" required>
                <el-input
                  v-model="agentForm.message"
                  type="textarea"
                  :rows="3"
                  placeholder="/check-login 或：搜索抖音关键词「护肤」前 3 条视频"
                />
              </el-form-item>
              <el-form-item label="Provider">
                <el-select v-model="agentForm.provider">
                  <el-option label="deepseek" value="deepseek" />
                  <el-option label="openai" value="openai" />
                </el-select>
              </el-form-item>
              <el-form-item label="模式">
                <el-select v-model="agentForm.mode">
                  <el-option label="agent（执行）" value="agent" />
                  <el-option label="plan（规划）" value="plan" />
                  <el-option label="ask（问答）" value="ask" />
                </el-select>
              </el-form-item>
              <el-form-item label="Headless">
                <el-switch v-model="agentForm.headless" />
              </el-form-item>
              <el-form-item label="超时 (秒)">
                <el-input-number v-model="agentForm.timeout_seconds" :min="30" :max="3600" :step="30" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="agentLoading" @click="runAgentSync">同步调用 Agent</el-button>
                <el-button @click="$router.push('/agent')">打开流式 Agent</el-button>
              </el-form-item>
            </el-form>
            <div v-if="agentResult" class="result-head">
              <el-tag :type="agentResult.status === 'completed' ? 'success' : 'warning'" size="small">
                {{ agentResult.status }}
              </el-tag>
              <el-tag v-if="agentResult.run_id" type="info" size="small" class="tag-gap">
                run_id: {{ agentResult.run_id }}
              </el-tag>
            </div>
            <pre v-if="agentResult" class="code-block result-json">{{ formatJson(agentResult) }}</pre>
          </div>

          <div class="tab-section quick-prompts">
            <h3 class="section-title">快捷指令</h3>
            <div class="prompt-chips">
              <el-button
                v-for="item in quickPrompts"
                :key="item"
                size="small"
                @click="agentForm.message = item"
              >
                {{ item }}
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="任务编排" name="tasks">
          <div class="tab-section">
            <h3 class="section-title">编排任务 · 列表 / 详情 / 联调</h3>
            <p class="section-desc">
              外部 JSON 经编译器映射为结构化任务，可在任务列表查看编排方式、运行阶段与进度；支持编译预览与提交执行测试。
            </p>
            <div class="task-test-actions">
              <el-button type="primary" @click="$router.push('/tasks')">打开任务列表</el-button>
              <el-button @click="$router.push('/tasks/compile')">编译联调</el-button>
              <el-button @click="$router.push('/orchestration')">Agent 编排</el-button>
              <el-button type="success" plain :loading="taskQuickLoading" @click="runTaskQuickTest">
                快速创建测试任务
              </el-button>
            </div>
            <pre v-if="taskQuickResult" class="code-block result-json">{{ formatJson(taskQuickResult) }}</pre>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </MainLayout>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import { syncAgentChat } from "../api/agent";
import { checkHealth, getSwaggerDocsUrl, runKeywordVideoComments } from "../api/openPipeline";
import { executeSkill, listSkills } from "../api/skills";
import { SAMPLE_YINGXIAOYI_PAYLOAD, compileAndCreateTask } from "../api/tasks";
import { getPlatformId } from "../api/http";

const route = useRoute();
const router = useRouter();

const activeTab = ref(
  route.query.tab === "agent" ? "agent" : route.query.tab === "tasks" ? "tasks" : "api",
);
const taskQuickLoading = ref(false);
const taskQuickResult = ref(null);
const healthLoading = ref(false);
const healthOk = ref(false);
const healthStatus = ref("");

const pipelineLoading = ref(false);
const pipelineResult = ref(null);
const pipelineForm = reactive({
  keyword: "",
  platforms: ["douyin", "xiaohongshu"],
  video_limit: 3,
  force_refresh: false,
  days: 3,
  timeout_seconds: 1200,
  async_job: false,
  cache_ttl_hours: 24,
});

const skillLoading = ref(false);
const skillsLoading = ref(false);
const skillResult = ref(null);
const skillsList = ref(null);
const skillForm = reactive({
  skill_id: "douyin-keyword-comments",
  platform: getPlatformId(),
  paramsText: '{"keyword":"护肤","limit":3,"days":3}',
  agent_fallback: false,
  timeout_seconds: 600,
});

const agentLoading = ref(false);
const agentResult = ref(null);
const agentForm = reactive({
  message: "/check-login",
  provider: "deepseek",
  mode: "agent",
  headless: true,
  timeout_seconds: 600,
});

const quickPrompts = [
  "/check-login",
  "/search-content keyword=护肤 limit=3",
  "/douyin-keyword-comments keyword=淋浴房 limit=2",
  "列出当前可用技能",
];

function formatJson(data) {
  return JSON.stringify(data, null, 2);
}

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return err?.message || fallback;
}

function parseSkillParams() {
  const text = skillForm.paramsText.trim();
  if (!text) return {};
  return JSON.parse(text);
}

async function checkHealthStatus() {
  healthLoading.value = true;
  try {
    const data = await checkHealth();
    healthOk.value = true;
    healthStatus.value = `服务正常：${data.status || "ok"}`;
  } catch (err) {
    healthOk.value = false;
    healthStatus.value = formatApiError(err, "健康检查失败");
  } finally {
    healthLoading.value = false;
  }
}

function openSwagger() {
  window.open(getSwaggerDocsUrl(), "_blank", "noopener,noreferrer");
}

async function runTaskQuickTest() {
  taskQuickLoading.value = true;
  taskQuickResult.value = null;
  try {
    const resp = await compileAndCreateTask({
      raw_payload: {
        ...SAMPLE_YINGXIAOYI_PAYLOAD,
        task_name: "测试入口快速任务",
        target_count: 20,
      },
      adapter_id: "yingxiaoyi-lead-v1",
      source: "external",
      auto_submit: false,
    });
    taskQuickResult.value = resp;
    if (resp.task?.task_id) {
      ElMessage.success("测试任务已创建");
      router.push(`/tasks/${resp.task.task_id}`);
    } else {
      ElMessage.warning(resp.compile?.plan?.validation_error || "创建失败");
    }
  } catch (err) {
    ElMessage.error(formatApiError(err, "快速测试失败"));
  } finally {
    taskQuickLoading.value = false;
  }
}

async function runPipeline() {
  if (!pipelineForm.keyword.trim()) {
    ElMessage.warning("请先输入关键词");
    return;
  }
  if (!pipelineForm.platforms.length) {
    ElMessage.warning("请至少选择一个平台");
    return;
  }
  pipelineLoading.value = true;
  pipelineResult.value = null;
  try {
    pipelineResult.value = await runKeywordVideoComments({
      keyword: pipelineForm.keyword.trim(),
      platforms: pipelineForm.platforms,
      video_limit: pipelineForm.video_limit,
      days: pipelineForm.days,
      timeout_seconds: pipelineForm.timeout_seconds,
      async_job: pipelineForm.async_job,
      force_refresh: pipelineForm.force_refresh,
      cache_ttl_hours: pipelineForm.cache_ttl_hours,
    });
    ElMessage.success(pipelineResult.value.job_id ? "异步任务已提交" : "Pipeline 执行完成");
  } catch (err) {
    ElMessage.error(formatApiError(err, "Pipeline 调用失败"));
  } finally {
    pipelineLoading.value = false;
  }
}

async function runSkillExecute() {
  if (!skillForm.skill_id.trim()) {
    ElMessage.warning("请填写 Skill ID");
    return;
  }
  let params;
  try {
    params = parseSkillParams();
  } catch {
    ElMessage.error("参数 JSON 格式不正确");
    return;
  }
  skillLoading.value = true;
  skillResult.value = null;
  try {
    const resp = await executeSkill({
      skill_id: skillForm.skill_id.trim(),
      platform: skillForm.platform,
      params,
      agent_fallback: skillForm.agent_fallback,
      timeout_seconds: skillForm.timeout_seconds,
    });
    skillResult.value = resp.data;
    ElMessage.success("Skill 执行完成");
  } catch (err) {
    ElMessage.error(formatApiError(err, "Skill 执行失败"));
  } finally {
    skillLoading.value = false;
  }
}

async function loadSkills() {
  skillsLoading.value = true;
  try {
    const resp = await listSkills();
    skillsList.value = resp.data;
  } catch (err) {
    ElMessage.error(formatApiError(err, "获取 Skill 列表失败"));
  } finally {
    skillsLoading.value = false;
  }
}

async function runAgentSync() {
  if (!agentForm.message.trim()) {
    ElMessage.warning("请输入消息");
    return;
  }
  agentLoading.value = true;
  agentResult.value = null;
  try {
    agentResult.value = await syncAgentChat({
      message: agentForm.message.trim(),
      provider: agentForm.provider,
      mode: agentForm.mode,
      headless: agentForm.headless,
      timeout_seconds: agentForm.timeout_seconds,
    });
    ElMessage.success("Agent 同步调用完成");
  } catch (err) {
    ElMessage.error(formatApiError(err, "Agent 调用失败"));
  } finally {
    agentLoading.value = false;
  }
}

function syncTabQuery() {
  router.replace({ query: { ...route.query, tab: activeTab.value } });
}

onMounted(() => {
  checkHealthStatus();
  window.addEventListener("huoke-tenant-changed", checkHealthStatus);
  window.addEventListener("huoke-platform-changed", () => {
    skillForm.platform = getPlatformId();
  });
});

watch(activeTab, syncTabQuery);

onUnmounted(() => {
  window.removeEventListener("huoke-tenant-changed", checkHealthStatus);
});
</script>

<style scoped>
.page-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.status-alert {
  margin-top: 12px;
}

.test-tabs {
  margin-top: 12px;
  padding: 8px 16px 16px;
}

.tab-section {
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--border, #eee);
}

.tab-section:first-child {
  border-top: none;
  padding-top: 8px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 15px;
}

.section-desc {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.compact-form {
  max-width: 640px;
}

.task-test-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.code-block {
  margin: 12px 0 0;
  padding: 12px;
  background: #f6f8fa;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  max-height: 360px;
}

.result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.tag-gap {
  margin-left: 4px;
}

.quick-prompts .prompt-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 760px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
