<template>
  <MainLayout>
    <div class="container">
      <TopActions
        title="热门视频排行"
        subtitle="展示热榜前 100 条及排名变化"
        @crawl="onCrawl"
        @login="onLogin"
      />
      <div class="panel content-panel">
        <div class="toolbar">
          <el-date-picker v-model="snapshotDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" />
          <el-button @click="loadData">查询</el-button>
        </div>
        <el-table :data="rows" stripe style="width: 100%">
          <el-table-column prop="rank" label="排名" width="80" />
          <el-table-column prop="video.title" label="标题" min-width="280" />
          <el-table-column prop="video.author.name" label="作者" width="160" />
          <el-table-column prop="video.like_count" label="点赞" width="110" />
          <el-table-column prop="video.comment_count" label="评论" width="110" />
          <el-table-column prop="video.share_count" label="分享" width="110" />
          <el-table-column prop="rank_change" label="排名变化" width="120" />
        </el-table>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import TopActions from "../components/TopActions.vue";
import { fetchHotVideos, triggerCrawl, fetchServerLoginUrl, triggerServerLogin } from "../api/douyin";

const rows = ref([]);
const snapshotDate = ref("");

async function loadData() {
  rows.value = await fetchHotVideos(snapshotDate.value || undefined, 100);
}

async function onCrawl() {
  await triggerCrawl(100);
  ElMessage.success("抓取任务完成");
  await loadData();
}

async function onLogin() {
  const win = window.open("about:blank", "_blank", "noopener,noreferrer");
  const data = await fetchServerLoginUrl();
  if (win && data.url) win.location.href = data.url;
  ElMessage.info("已打开服务器登录窗口，请在新页面里完成扫码/验证");
  triggerServerLogin().catch(() => {});
}

onMounted(loadData);
</script>

<style scoped>
.content-panel {
  margin-top: 12px;
  padding: 12px;
}

.toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
}
</style>
