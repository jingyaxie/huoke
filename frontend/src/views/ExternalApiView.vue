<template>
  <MainLayout>
    <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">对外接口 API</h2>
          <p class="page-subtitle">
            查看接口文档、鉴权说明，并在线测试关键词视频+评论 Pipeline
          </p>
        </div>
        <div class="header-actions">
          <el-button :loading="healthLoading" @click="checkHealthStatus">健康检查</el-button>
          <el-button type="primary" @click="openSwagger">OpenAPI 文档</el-button>
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

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <div class="panel section-panel">
        <h3 class="section-title">缓存策略</h3>
        <p class="section-desc">
          所有抓取类接口默认缓存 <strong>24 小时</strong>。缓存命中时直接返回已存储数据，不触发 Playwright 抓取。
          评论数据按 <code>comment_id</code> 增量合并写入数据库，并维护 canonical JSON 文件。
        </p>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="默认 TTL">24 小时（可通过 cache_ttl_hours 调整）</el-descriptions-item>
          <el-descriptions-item label="强制拉取">force_refresh=true 时跳过缓存并即时拉取；拉取失败则自动回退返回已有缓存</el-descriptions-item>
          <el-descriptions-item label="评论存储">
            DB 表 content_comments + 文件 comments_{platform}_{tenant}_{content_id}.json
          </el-descriptions-item>
          <el-descriptions-item label="搜索存储">
            缓存索引 crawl_cache_entries + 文件 search_{platform}_{tenant}_{hash}.json
          </el-descriptions-item>
          <el-descriptions-item label="响应字段">cache.from_cache / cache.cache_hit / cache.expires_at</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">鉴权与请求头</h3>
        <p class="section-desc">
          在左侧边栏配置租户 ID 与 API Key；请求会自动携带以下 Header（通过
          <code>http.js</code> 拦截器注入）。
        </p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="X-Tenant-Id">
            <code>{{ tenantId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-Platform-Id">
            <code>{{ platformId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-Account-Id">
            <code>{{ accountId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-API-Key">
            <code>{{ apiKeyMasked }}</code>
            <span class="muted-inline">（启用租户鉴权时必填）</span>
          </el-descriptions-item>
          <el-descriptions-item label="Authorization">
            <code>{{ tokenMasked }}</code>
            <span class="muted-inline">（用户登录后自动携带）</span>
          </el-descriptions-item>
          <el-descriptions-item label="API Base URL">
            <code>{{ apiBaseUrl }}</code>
          </el-descriptions-item>
        </el-descriptions>
        <p class="section-desc note">
          管理员创建 API Key：<code>POST /api/admin/tenant-keys</code>，需携带
          <code>X-Admin-Secret</code>。
        </p>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">关键词视频 + 评论 Pipeline</h3>
        <p class="section-desc">
          核心对外接口，按关键词搜索热门视频/笔记并抓取评论，由固定 Skill 驱动。
        </p>

        <div class="grid">
          <div class="form-area">
            <el-form label-width="110px">
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
              <el-form-item label="地区">
                <el-input
                  v-model="pipelineForm.region"
                  placeholder="可选，如：辽宁、沈阳、辽宁省淋浴房"
                  clearable
                />
                <span class="field-hint">会拼入搜索词并作为筛选上下文，留空则不限制</span>
              </el-form-item>
              <el-form-item label="最近天数">
                <el-input-number v-model="pipelineForm.days" :min="1" :max="30" />
              </el-form-item>
              <el-form-item label="超时 (秒)">
                <el-input-number v-model="pipelineForm.timeout_seconds" :min="60" :max="3600" :step="60" />
              </el-form-item>
              <el-form-item label="异步任务">
                <el-switch v-model="pipelineForm.async_job" />
                <span class="field-hint">开启后返回 job_id，通过任务接口轮询结果</span>
              </el-form-item>
              <el-form-item label="强制拉取">
                <el-switch v-model="pipelineForm.force_refresh" />
                <span class="field-hint">忽略 24h 缓存，立即触发抓取</span>
              </el-form-item>
              <el-form-item label="缓存 (小时)">
                <el-input-number v-model="pipelineForm.cache_ttl_hours" :min="0.25" :max="168" :step="1" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="pipelineLoading" @click="runPipeline">
                  调用接口
                </el-button>
                <el-button @click="copyPipelineCurl">复制 curl</el-button>
              </el-form-item>
            </el-form>
          </div>

          <div class="curl-area">
            <div class="curl-head">
              <span class="curl-label">请求示例</span>
              <el-button text size="small" @click="copyPipelineCurl">复制</el-button>
            </div>
            <pre class="code-block">{{ pipelineCurl }}</pre>
          </div>
        </div>

        <div v-if="pipelineResult" class="result-area">
          <div class="result-head">
            <h4>响应结果</h4>
            <el-tag :type="pipelineResult.status === 'completed' ? 'success' : 'warning'" size="small">
              {{ pipelineResult.status }}
            </el-tag>
            <el-tag v-if="pipelineResult.job_id" type="info" size="small" class="tag-gap">
              job_id: {{ pipelineResult.job_id }}
            </el-tag>
            <el-tag
              v-if="pipelineResult.cache?.from_cache"
              type="success"
              size="small"
              class="tag-gap"
            >
              缓存命中
            </el-tag>
          </div>
          <pre class="code-block result-json">{{ formatJson(pipelineResult) }}</pre>
        </div>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">接口目录</h3>
        <el-tabs v-model="activeTab">
          <el-tab-pane label="Pipeline" name="pipeline">
            <ApiEndpointTable :endpoints="pipelineEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
          <el-tab-pane label="平台工具 API" name="platforms">
            <el-tabs v-model="platformTab" type="card" class="inner-tabs">
              <el-tab-pane label="抖音" name="douyin">
                <ApiEndpointTable :endpoints="douyinEndpoints" :curl-builder="buildCurl" />
              </el-tab-pane>
              <el-tab-pane label="小红书" name="xiaohongshu">
                <ApiEndpointTable :endpoints="xhsEndpoints" :curl-builder="buildCurl" />
              </el-tab-pane>
              <el-tab-pane label="快手" name="kuaishou">
                <ApiEndpointTable :endpoints="kuaishouEndpoints" :curl-builder="buildCurl" />
              </el-tab-pane>
            </el-tabs>
          </el-tab-pane>
          <el-tab-pane label="通用 REST" name="general">
            <ApiEndpointTable :endpoints="generalEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElButton, ElMessage, ElTag } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import {
  getAccountId,
  getApiBaseUrl,
  getApiKey,
  getAccessToken,
  getPlatformId,
  getTenantId,
} from "../api/http";
import { checkHealth, getSwaggerDocsUrl, runKeywordVideoComments } from "../api/openPipeline";

const ApiEndpointTable = defineComponent({
  props: {
    endpoints: { type: Array, required: true },
    curlBuilder: { type: Function, required: true },
  },
  setup(props) {
    return () =>
      h(
        "div",
        { class: "endpoint-list" },
        props.endpoints.map((ep) =>
          h("div", { class: "endpoint-item", key: ep.path }, [
            h("div", { class: "endpoint-head" }, [
              h(ElTag, { type: ep.method === "GET" ? "success" : "primary", size: "small" }, () => ep.method),
              h("code", { class: "endpoint-path" }, ep.path),
              h("span", { class: "endpoint-summary" }, ep.summary),
            ]),
            h("p", { class: "endpoint-desc" }, ep.description),
            ep.body
              ? h("div", { class: "endpoint-body" }, [
                  h("span", { class: "body-label" }, "请求体："),
                  h("pre", { class: "code-block small" }, JSON.stringify(ep.body, null, 2)),
                ])
              : null,
            h(
              ElButton,
              {
                text: true,
                type: "primary",
                size: "small",
                onClick: () => copyText(props.curlBuilder(ep)),
              },
              () => "复制 curl"
            ),
          ])
        )
      );
  },
});

const tenantId = ref(getTenantId());
const platformId = ref(getPlatformId());
const accountId = ref(getAccountId());
const apiBaseUrl = getApiBaseUrl();

const healthLoading = ref(false);
const healthOk = ref(false);
const healthStatus = ref("");
const errorMessage = ref("");
const pipelineLoading = ref(false);
const pipelineResult = ref(null);
const activeTab = ref("pipeline");
const platformTab = ref("douyin");

const pipelineForm = reactive({
  keyword: "",
  platforms: ["douyin", "xiaohongshu"],
  video_limit: 5,
  region: "",
  days: 3,
  timeout_seconds: 1200,
  async_job: false,
  force_refresh: false,
  cache_ttl_hours: 24,
});

const apiKeyMasked = computed(() => {
  const key = getApiKey();
  if (!key) return "（未设置）";
  if (key.length <= 8) return "****";
  return `${key.slice(0, 4)}****${key.slice(-4)}`;
});

const tokenMasked = computed(() => {
  const token = getAccessToken();
  if (!token) return "（未登录）";
  return `Bearer ${token.slice(0, 8)}...`;
});

const pipelineEndpoints = [
  {
    method: "POST",
    path: "/api/agent/pipeline/keyword-video-comments",
    summary: "关键词视频+评论 Pipeline",
    description: "按关键词搜索热门视频/笔记并抓取评论，支持抖音与小红书，可同步或异步执行。",
    body: {
      keyword: "淋浴房",
      platforms: ["douyin", "xiaohongshu"],
      video_limit: 5,
      region: "辽宁",
      days: 3,
      timeout_seconds: 1200,
      async_job: false,
      force_refresh: false,
      cache_ttl_hours: 24,
    },
  },
  {
    method: "POST",
    path: "/api/agent/jobs",
    summary: "提交异步任务",
    description: "提交 Agent 异步任务，返回 job_id 用于轮询。",
    body: { message: "执行关键词评论抓取", provider: "deepseek", mode: "agent" },
  },
  {
    method: "GET",
    path: "/api/agent/jobs/{job_id}",
    summary: "查询异步任务",
    description: "根据 job_id 查询任务状态与结果。",
  },
];

const douyinEndpoints = [
  {
    method: "POST",
    path: "/api/platforms/douyin/search/videos",
    summary: "关键词搜索视频",
    body: { keyword: "淋浴房", limit: 10, days: 3, region: "辽宁", show_browser: false },
  },
  {
    method: "POST",
    path: "/api/platforms/douyin/comments/videos",
    summary: "抓取单视频评论",
    body: { video_url: "https://www.douyin.com/video/xxx", max_comments: 200 },
  },
  {
    method: "POST",
    path: "/api/platforms/douyin/comments/keyword",
    summary: "关键词搜索并抓取评论",
    body: { keyword: "淋浴房", limit: 3, max_comments: 200, days: 3, region: "辽宁" },
  },
  {
    method: "POST",
    path: "/api/platforms/douyin/users/follow",
    summary: "关注用户（已关注则跳过，避免重复点击取消关注）",
    body: { sec_uid: "...", user_id: "...", show_browser: false },
  },
  {
    method: "POST",
    path: "/api/platforms/douyin/users/unfollow",
    summary: "取消关注（未关注则跳过）",
    body: { sec_uid: "...", user_id: "...", show_browser: false },
  },
  {
    method: "POST",
    path: "/api/platforms/douyin/users/messages",
    summary: "发送私信",
    body: { sec_uid: "...", user_id: "...", message: "你好", show_browser: false },
  },
];

const xhsEndpoints = [
  {
    method: "POST",
    path: "/api/platforms/xiaohongshu/search/notes",
    summary: "关键词搜索笔记",
    body: { keyword: "护肤", limit: 10, days: 3, region: "上海", show_browser: false },
  },
  {
    method: "POST",
    path: "/api/platforms/xiaohongshu/comments/notes",
    summary: "抓取单篇笔记评论",
    body: { note_url: "https://www.xiaohongshu.com/explore/xxx", max_comments: 200 },
  },
  {
    method: "POST",
    path: "/api/platforms/xiaohongshu/comments/keyword",
    summary: "关键词搜索并抓取评论",
    body: { keyword: "护肤", limit: 3, max_comments: 200, days: 3, region: "上海" },
  },
];

const kuaishouEndpoints = [
  {
    method: "POST",
    path: "/api/platforms/kuaishou/search/videos",
    summary: "关键词搜索视频",
    body: { keyword: "美食", limit: 10, days: 3, region: "北京", show_browser: false },
  },
  {
    method: "POST",
    path: "/api/platforms/kuaishou/comments/videos",
    summary: "抓取单视频评论",
    body: { video_url: "https://www.kuaishou.com/short-video/xxx", max_comments: 200 },
  },
  {
    method: "POST",
    path: "/api/platforms/kuaishou/comments/keyword",
    summary: "关键词搜索并抓取评论",
    body: { keyword: "美食", limit: 3, max_comments: 200, days: 3, region: "北京" },
  },
];

const generalEndpoints = [
  { method: "GET", path: "/api/health", summary: "健康检查" },
  {
    method: "POST",
    path: "/api/platforms/{platform}/crawl/hot",
    summary: "抓取热榜",
    query: { limit: 100, force_refresh: false },
  },
  {
    method: "GET",
    path: "/api/platforms/{platform}/hot/videos",
    summary: "热门视频列表",
    query: { limit: 100 },
  },
  {
    method: "GET",
    path: "/api/platforms/{platform}/hot/authors",
    summary: "热门作者列表",
    query: { limit: 50 },
  },
  { method: "GET", path: "/api/comments/download", summary: "下载评论 JSON 文件", query: { file_name: "xxx.json" } },
  { method: "POST", path: "/api/platforms/{platform}/reports/daily", summary: "生成热点日报" },
  { method: "GET", path: "/api/platforms/{platform}/reports", summary: "日报列表" },
];

function refreshContext() {
  tenantId.value = getTenantId();
  platformId.value = getPlatformId();
  accountId.value = getAccountId();
}

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return err?.message || fallback;
}

function formatJson(data) {
  return JSON.stringify(data, null, 2);
}

function buildHeaders() {
  const headers = [
    `-H "Content-Type: application/json"`,
    `-H "X-Tenant-Id: ${getTenantId()}"`,
    `-H "X-Platform-Id: ${getPlatformId()}"`,
    `-H "X-Account-Id: ${getAccountId()}"`,
  ];
  const apiKey = getApiKey();
  if (apiKey) headers.push(`-H "X-API-Key: ${apiKey}"`);
  const token = getAccessToken();
  if (token) headers.push(`-H "Authorization: Bearer ${token}"`);
  return headers.join(" \\\n  ");
}

function buildCurl(endpoint) {
  const base = apiBaseUrl.replace(/\/$/, "");
  let url = `${base}${endpoint.path.replace("/api", "")}`;
  if (endpoint.query) {
    const qs = new URLSearchParams(endpoint.query).toString();
    url += `?${qs}`;
  }
  const lines = [`curl -X ${endpoint.method} "${url}" \\`, `  ${buildHeaders()}`];
  if (endpoint.body) {
    lines.push(`  -d '${JSON.stringify(endpoint.body)}'`);
  }
  return lines.join("\n");
}

const pipelineCurl = computed(() =>
  buildCurl({
    method: "POST",
    path: "/api/agent/pipeline/keyword-video-comments",
    body: {
      keyword: pipelineForm.keyword || "淋浴房",
      platforms: pipelineForm.platforms,
      video_limit: pipelineForm.video_limit,
      region: pipelineForm.region || null,
      days: pipelineForm.days,
      timeout_seconds: pipelineForm.timeout_seconds,
      async_job: pipelineForm.async_job,
      force_refresh: pipelineForm.force_refresh,
      cache_ttl_hours: pipelineForm.cache_ttl_hours,
    },
  })
);

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制到剪贴板");
  } catch {
    ElMessage.error("复制失败，请手动选择复制");
  }
}

function copyPipelineCurl() {
  copyText(pipelineCurl.value);
}

async function checkHealthStatus() {
  healthLoading.value = true;
  errorMessage.value = "";
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
  errorMessage.value = "";
  pipelineResult.value = null;
  try {
    const data = await runKeywordVideoComments({
      keyword: pipelineForm.keyword.trim(),
      platforms: pipelineForm.platforms,
      video_limit: pipelineForm.video_limit,
      region: pipelineForm.region.trim() || null,
      days: pipelineForm.days,
      timeout_seconds: pipelineForm.timeout_seconds,
      async_job: pipelineForm.async_job,
      force_refresh: pipelineForm.force_refresh,
      cache_ttl_hours: pipelineForm.cache_ttl_hours,
    });
    pipelineResult.value = data;
    if (data.cache?.from_cache) {
      ElMessage.success("返回缓存数据（未触发抓取）");
    } else if (data.job_id) {
      ElMessage.success(`异步任务已提交，job_id: ${data.job_id}`);
    } else {
      ElMessage.success("Pipeline 执行完成");
    }
  } catch (err) {
    errorMessage.value = formatApiError(err, "Pipeline 调用失败");
    ElMessage.error(errorMessage.value);
  } finally {
    pipelineLoading.value = false;
  }
}

function onContextChanged() {
  refreshContext();
}

onMounted(() => {
  refreshContext();
  window.addEventListener("huoke-tenant-changed", onContextChanged);
});

onUnmounted(() => {
  window.removeEventListener("huoke-tenant-changed", onContextChanged);
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
}

.status-alert {
  margin-top: 12px;
}

.section-panel {
  padding: 16px;
  margin-top: 12px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 16px;
}

.section-desc {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.section-desc.note {
  margin-top: 12px;
  margin-bottom: 0;
}

.muted-inline {
  margin-left: 8px;
  color: var(--muted);
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-area {
  min-width: 0;
}

.curl-area {
  min-width: 0;
}

.curl-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.curl-label {
  font-size: 13px;
  color: var(--muted);
}

.code-block {
  margin: 0;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.code-block.small {
  font-size: 11px;
  padding: 8px;
}

.result-area {
  margin-top: 16px;
}

.result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.result-head h4 {
  margin: 0;
  font-size: 14px;
}

.tag-gap {
  margin-left: 4px;
}

.field-hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

.inner-tabs {
  margin-top: 8px;
}

:deep(.endpoint-list) {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

:deep(.endpoint-item) {
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

:deep(.endpoint-item:last-child) {
  border-bottom: none;
  padding-bottom: 0;
}

:deep(.endpoint-head) {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

:deep(.endpoint-path) {
  font-size: 13px;
  color: #374151;
}

:deep(.endpoint-summary) {
  font-size: 13px;
  color: var(--muted);
}

:deep(.endpoint-desc) {
  margin: 0 0 8px;
  font-size: 13px;
  color: #4b5563;
  line-height: 1.5;
}

:deep(.endpoint-body) {
  margin-bottom: 8px;
}

:deep(.body-label) {
  font-size: 12px;
  color: var(--muted);
}

.result-json {
  max-height: 400px;
  overflow-y: auto;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
