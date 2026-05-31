<template>
  <MainLayout>
    <div class="container">
      <TopActions
        title="热点日报"
        subtitle="对接 OpenAI / DeepSeek 自动生成日报并导出 PDF"
        @crawl="onCrawl"
        @login="onLogin"
      />
      <div class="panel content-panel">
        <div class="toolbar">
          <el-date-picker v-model="reportDate" type="date" value-format="YYYY-MM-DD" />
          <el-select v-model="provider" style="width: 180px">
            <el-option label="模板" value="template" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="DeepSeek" value="deepseek" />
          </el-select>
          <el-button type="primary" @click="generate">生成日报</el-button>
        </div>
        <el-table :data="rows" stripe>
          <el-table-column prop="report_date" label="日期" width="140" />
          <el-table-column prop="provider" label="模型提供方" width="120" />
          <el-table-column prop="title" label="标题" min-width="260" />
          <el-table-column prop="created_at" label="生成时间" min-width="200" />
          <el-table-column label="操作" width="120">
            <template #default="scope">
              <a :href="pdfUrl(scope.row.report_date)" target="_blank">下载 PDF</a>
            </template>
          </el-table-column>
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
import { fetchReports, generateDailyReport, reportPdfUrl, triggerCrawl, triggerLogin } from "../api/douyin";

const rows = ref([]);
const provider = ref("template");
const reportDate = ref(new Date().toISOString().slice(0, 10));

async function loadReports() {
  rows.value = await fetchReports();
}

function pdfUrl(date) {
  return reportPdfUrl(date);
}

async function generate() {
  await generateDailyReport(reportDate.value, provider.value);
  ElMessage.success("日报已生成");
  await loadReports();
}

async function onCrawl() {
  await triggerCrawl(100);
  ElMessage.success("抓取任务完成");
}

async function onLogin() {
  ElMessage.info("将打开抖音页面，请在 3 分钟内手动扫码");
  await triggerLogin();
  ElMessage.success("Cookie 已保存");
}

onMounted(loadReports);
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
  flex-wrap: wrap;
}
</style>

