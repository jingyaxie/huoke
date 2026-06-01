<template>
  <MainLayout>
    <div class="container">
      <TopActions
        title="评论抓取"
        subtitle="支持单个视频抓取，以及关键词批量抓取前几个视频的全部评论"
        @login="onLogin"
      />
      <el-alert
        v-if="loginStatus.message"
        :title="loginStatus.message"
        :type="loginStatus.status === 'ready' ? 'success' : 'warning'"
        show-icon
        :closable="false"
        class="login-status"
      >
        <template #default>
          <el-button link type="primary" @click="refreshLoginStatus">刷新登录状态</el-button>
        </template>
      </el-alert>

      <div class="grid">
        <div class="panel form-panel">
          <h3 class="section-title">单个视频</h3>
          <el-form label-width="88px">
            <el-form-item label="视频链接">
              <el-input v-model="single.videoUrl" placeholder="https://www.douyin.com/video/..." />
            </el-form-item>
            <el-form-item label="可见浏览器">
              <el-switch v-model="single.showBrowser" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="single.loading" @click="crawlSingle">开始抓取</el-button>
            </el-form-item>
          </el-form>
        </div>

        <div class="panel form-panel">
          <h3 class="section-title">关键词批量</h3>
          <el-form label-width="88px">
            <el-form-item label="关键词">
              <el-input v-model="batch.keyword" placeholder="例如：淋浴房" />
            </el-form-item>
            <el-form-item label="抓取数量">
              <el-input-number v-model="batch.limit" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="最近天数">
              <el-input-number v-model="batch.days" :min="1" :max="30" />
            </el-form-item>
            <el-form-item label="地区">
              <el-input v-model="batch.region" placeholder="可选，例如：辽宁" />
            </el-form-item>
            <el-form-item label="可见浏览器">
              <el-switch v-model="batch.showBrowser" />
            </el-form-item>
            <el-form-item>
              <el-button type="warning" :loading="batch.loading" @click="crawlBatch">批量抓取</el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>

      <div class="panel result-panel">
        <div class="toolbar">
          <h3 class="section-title">结果</h3>
          <el-button text @click="clearResults">清空</el-button>
        </div>
        <el-table :data="results" stripe style="width: 100%">
          <el-table-column prop="type" label="类型" width="110" />
          <el-table-column prop="target" label="目标" min-width="320" />
          <el-table-column prop="total_comments_captured" label="抓到评论数" width="120" />
          <el-table-column prop="api_total_top_comments" label="接口总数" width="120" />
          <el-table-column prop="output_file" label="输出文件" min-width="280" />
          <el-table-column label="下载" width="90">
            <template #default="{ row }">
              <el-button link type="primary" @click="downloadFile(row.file_name)">下载</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <ServerLoginDialog v-model="loginDialogVisible" :url="serverLoginUrl" />
      <ServerBrowserDialog v-model="browserDialogVisible" :url="serverBrowserUrl" />
    </div>
  </MainLayout>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import TopActions from "../components/TopActions.vue";
import ServerLoginDialog from "../components/ServerLoginDialog.vue";
import ServerBrowserDialog from "../components/ServerBrowserDialog.vue";
import {
  commentFileDownloadUrl,
  crawlKeywordComments,
  crawlVideoComments,
  fetchLoginStatus,
  fetchServerLoginUrl,
  triggerServerLogin,
} from "../api/douyin";

const RESULTS_STORAGE_KEY = "douyin_comment_crawl_results_v1";

function formatCrawlError(err, actionLabel) {
  const detail = err?.response?.data?.detail;
  const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : err?.message || String(err);
  if (err?.code === "ECONNABORTED" || /timeout/i.test(msg)) {
    return `${actionLabel}超时：抓取耗时较长，请确认后端仍在运行；若 reports 已生成文件可手动下载。`;
  }
  return `${actionLabel}失败：${msg}`;
}
const results = ref([]);
const loginDialogVisible = ref(false);
const serverLoginUrl = ref("");
const browserDialogVisible = ref(false);
const serverBrowserUrl = ref("");
const loginStatus = reactive({
  status: "unknown",
  message: "",
});

const single = reactive({
  videoUrl: "",
  showBrowser: false,
  loading: false,
});

const batch = reactive({
  keyword: "",
  limit: 3,
  days: 3,
  region: "",
  showBrowser: false,
  loading: false,
});

async function openServerBrowser() {
  const data = await fetchServerLoginUrl();
  serverBrowserUrl.value = data.url || "";
  browserDialogVisible.value = true;
  if (serverBrowserUrl.value) {
    window.open(serverBrowserUrl.value, "_blank", "noopener,noreferrer");
    ElMessage.info("已打开服务器浏览器窗口，请手动搜索，检测到结果后会自动抓评论");
  }
}

async function crawlSingle() {
  if (!single.videoUrl) {
    ElMessage.warning("请先输入视频链接");
    return;
  }
  single.loading = true;
  try {
    if (single.showBrowser) {
      await openServerBrowser();
    }
    const data = await crawlVideoComments(single.videoUrl, single.showBrowser);
    const fileName = data.output_file.split("/").pop();
    results.value.unshift({
      type: "单视频",
      target: single.videoUrl,
      total_comments_captured: data.total_comments_captured,
      api_total_top_comments: data.api_total_top_comments,
      output_file: data.output_file,
      file_name: fileName,
    });
    ElMessage.success("抓取完成");
  } catch (err) {
    ElMessage.error(formatCrawlError(err, "单视频抓取"));
  } finally {
    single.loading = false;
  }
}

async function crawlBatch() {
  if (!batch.keyword) {
    ElMessage.warning("请先输入关键词");
    return;
  }
  batch.loading = true;
  try {
    if (batch.showBrowser) {
      await openServerBrowser();
    }
    const data = await crawlKeywordComments(batch.keyword, batch.limit, batch.showBrowser, batch.days, batch.region);
    if (!data.items || data.items.length === 0) {
      const reason = data.diagnostic ? `原因：${data.diagnostic}` : "请先登录抖音，或切换关键词后重试。";
      ElMessage.warning(`未抓到数据：关键词“${data.keyword}”本次找到视频 ${data.videos_found || 0} 条。${reason}`);
      return;
    }
    data.items.forEach((item) => {
      const fileName = item.output_file.split("/").pop();
      results.value.unshift({
        type: "关键词",
        target: `${data.keyword} / ${item.video_url}`,
        total_comments_captured: item.total_comments_captured,
        api_total_top_comments: item.api_total_top_comments,
        output_file: item.output_file,
        file_name: fileName,
      });
    });
    ElMessage.success(`批量抓取完成：成功抓取 ${data.items.length} 条视频评论`);
  } catch (err) {
    ElMessage.error(formatCrawlError(err, "关键词批量抓取"));
  } finally {
    batch.loading = false;
  }
}

async function onLogin() {
  try {
    const data = await fetchServerLoginUrl();
    serverLoginUrl.value = data.url || "";
    loginDialogVisible.value = true;
    ElMessage.info("请在弹窗里完成扫码/验证，完成后点击“刷新登录状态”");
    await triggerServerLogin();
    await refreshLoginStatus();
  } catch (err) {
    ElMessage.error(`打开登录失败：${err?.message || err}`);
  }
}

function downloadFile(fileName) {
  if (!fileName) return;
  window.open(commentFileDownloadUrl(fileName), "_blank");
}

function clearResults() {
  results.value = [];
  localStorage.removeItem(RESULTS_STORAGE_KEY);
}

onMounted(() => {
  const raw = localStorage.getItem(RESULTS_STORAGE_KEY);
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      results.value = parsed;
    }
  } catch {
    localStorage.removeItem(RESULTS_STORAGE_KEY);
  }
});

async function refreshLoginStatus() {
  try {
    const data = await fetchLoginStatus();
    loginStatus.status = data.status || "unknown";
    loginStatus.message = data.message || "";
  } catch {
    loginStatus.status = "error";
    loginStatus.message = "登录状态检查失败";
  }
}

onMounted(refreshLoginStatus);

watch(
  results,
  (val) => {
    localStorage.setItem(RESULTS_STORAGE_KEY, JSON.stringify(val));
  },
  { deep: true }
);
</script>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.form-panel,
.result-panel {
  padding: 16px;
}

.result-panel {
  margin-top: 12px;
}

.section-title {
  margin: 0 0 14px;
  font-size: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
