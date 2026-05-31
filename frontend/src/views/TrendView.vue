<template>
  <MainLayout>
    <div class="container">
      <TopActions
        title="趋势统计图"
        subtitle="查看单个视频最近 30 天排名变化"
        @crawl="onCrawl"
        @login="onLogin"
      />
      <div class="panel content-panel">
        <div class="toolbar">
          <el-input-number v-model="videoId" :min="1" :step="1" />
          <el-input-number v-model="days" :min="1" :max="365" :step="1" />
          <el-button type="primary" @click="loadTrend">加载趋势</el-button>
        </div>
        <div ref="chartEl" class="chart"></div>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import * as echarts from "echarts";
import { ElMessage } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import TopActions from "../components/TopActions.vue";
import { fetchVideoTrend, triggerCrawl, triggerLogin } from "../api/douyin";

const chartEl = ref(null);
const chart = ref(null);
const videoId = ref(1);
const days = ref(30);

function render(points, title) {
  if (!chart.value) {
    chart.value = echarts.init(chartEl.value);
  }
  chart.value.setOption({
    title: { text: title },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: points.map((p) => p.day) },
    yAxis: { type: "value", inverse: true, minInterval: 1 },
    series: [{ type: "line", data: points.map((p) => p.rank), smooth: true }],
  });
}

async function loadTrend() {
  const data = await fetchVideoTrend(videoId.value, days.value);
  render(data.points, data.title);
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

onMounted(async () => {
  await nextTick();
  await loadTrend();
  window.addEventListener("resize", resizeChart);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  if (chart.value) {
    chart.value.dispose();
  }
});

function resizeChart() {
  if (chart.value) {
    chart.value.resize();
  }
}
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

.chart {
  width: 100%;
  min-height: 420px;
}
</style>

