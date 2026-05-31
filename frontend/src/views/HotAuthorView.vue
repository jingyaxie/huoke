<template>
  <MainLayout>
    <div class="container">
      <TopActions
        title="热门作者排行"
        subtitle="按入榜视频数量和互动量统计作者热度"
        @crawl="onCrawl"
        @login="onLogin"
      />
      <div class="panel content-panel">
        <div class="toolbar">
          <el-date-picker v-model="snapshotDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" />
          <el-button @click="loadData">查询</el-button>
        </div>
        <el-table :data="rows" stripe style="width: 100%">
          <el-table-column prop="author_name" label="作者" min-width="220" />
          <el-table-column prop="video_count" label="入榜视频数" width="140" />
          <el-table-column prop="like_count" label="点赞总数" width="140" />
          <el-table-column prop="comment_count" label="评论总数" width="140" />
          <el-table-column prop="share_count" label="分享总数" width="140" />
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
import { fetchHotAuthors, triggerCrawl, fetchServerLoginUrl, triggerServerLogin } from "../api/douyin";

const rows = ref([]);
const snapshotDate = ref("");

async function loadData() {
  rows.value = await fetchHotAuthors(snapshotDate.value || undefined, 50);
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
