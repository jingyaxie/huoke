<template>
  <el-dialog
    v-model="visible"
    title="查看数据"
    width="1180px"
    destroy-on-close
    class="outreach-dialog"
    @closed="resetState"
  >
    <div v-if="job" class="outreach-body">
      <div class="outreach-toolbar">
        <span class="toolbar-label">评论筛选</span>
        <el-input
          v-model="keyword"
          placeholder="输入原评论、评论内容、私信内容关键词"
          clearable
          @keyup.enter="page = 1"
        />
        <el-select v-model="actionType" style="width: 140px" @change="page = 1">
          <el-option label="全部类型" value="all" />
          <el-option label="评论" value="comment" />
          <el-option label="私信" value="dm" />
        </el-select>
        <el-button type="primary" @click="page = 1">查询</el-button>
      </div>

      <div class="summary-grid">
        <div><span class="summary-label">任务名称</span><div>{{ rowModel?.name || "—" }}</div></div>
        <div><span class="summary-label">渠道</span><div>{{ platformLabel(rowModel?.platform) }}</div></div>
        <div><span class="summary-label">视频发布时间</span><div>{{ publishLabel }}</div></div>
        <div><span class="summary-label">采集几天内评论</span><div>{{ commentDaysLabel }}</div></div>
      </div>

      <el-alert
        v-if="emptyHint"
        type="warning"
        :closable="false"
        :title="emptyHint"
        show-icon
        class="empty-hint"
      />

      <el-table v-loading="loading" :data="pageRows" stripe empty-text="暂无触达数据">
        <el-table-column prop="nickname" label="用户昵称" width="120" show-overflow-tooltip />
        <el-table-column label="头像" width="72">
          <template #default="{ row }">
            <el-avatar :size="28">{{ avatarInitial(row.nickname) }}</el-avatar>
          </template>
        </el-table-column>
        <el-table-column prop="comment_at" label="评论时间" width="140">
          <template #default="{ row }">{{ formatJobTime(row.comment_at) }}</template>
        </el-table-column>
        <el-table-column prop="video_title" label="视频名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="comment_content" label="原评论" min-width="160" show-overflow-tooltip />
        <el-table-column label="精准评论" width="88">
          <template #default="{ row }">
            <el-tag :type="row.is_precise ? 'success' : 'info'" size="small">
              {{ row.is_precise ? "是" : "否" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reply_content" label="评论内容" min-width="140" show-overflow-tooltip />
        <el-table-column prop="dm_content" label="私信内容" min-width="140" show-overflow-tooltip />
        <el-table-column prop="location_text" label="位置" width="100" show-overflow-tooltip />
        <el-table-column prop="executed_at" label="触达时间" width="140">
          <template #default="{ row }">{{ formatJobTime(row.executed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.video_url" link type="primary" size="small" @click="openLink(row.video_url)">
              查看视频
            </el-button>
            <el-button v-if="row.profile_url" link type="primary" size="small" @click="openLink(row.profile_url)">
              查看主页
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager-row">
        <span class="pager-text">
          共 {{ filteredRows.length }} 条，当前显示 {{ pageStart }}-{{ pageEnd }}
        </span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          layout="prev, pager, next"
          :total="filteredRows.length"
          background
          small
        />
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import {
  avatarInitial,
  filterOutreachRows,
  formatJobTime,
  getJobRowModel,
  getOutreachRows,
  platformLabel,
} from "../utils/acquisitionJobs";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  job: { type: Object, default: null },
});

const emit = defineEmits(["update:modelValue"]);

const visible = ref(false);
const keyword = ref("");
const actionType = ref("all");
const page = ref(1);
const pageSize = 10;
const loading = ref(false);

watch(
  () => props.modelValue,
  (value) => {
    visible.value = value;
  },
  { immediate: true },
);

watch(visible, (value) => {
  emit("update:modelValue", value);
});

const rowModel = computed(() => (props.job ? getJobRowModel(props.job) : null));

const publishLabel = computed(() => {
  const map = { unlimited: "不限", "1d": "1天内", "3d": "3天内", "7d": "1周内", "180d": "半年内" };
  const raw = String(rowModel.value?.config?.publish_time_range || "unlimited");
  return map[raw] || raw;
});

const commentDaysLabel = computed(() => {
  const days = String(rowModel.value?.config?.comment_days ?? "3");
  const map = { 0: "不限", 3: "3天", 5: "5天", 7: "7天" };
  return map[days] || `${days}天`;
});

const allRows = computed(() => (props.job ? getOutreachRows(props.job) : []));

const filteredRows = computed(() =>
  filterOutreachRows(allRows.value, { keyword: keyword.value, actionType: actionType.value }),
);

const pageRows = computed(() => {
  const start = (page.value - 1) * pageSize;
  return filteredRows.value.slice(start, start + pageSize);
});

const pageStart = computed(() => (filteredRows.value.length ? (page.value - 1) * pageSize + 1 : 0));
const pageEnd = computed(() => Math.min(page.value * pageSize, filteredRows.value.length));

const emptyHint = computed(() => {
  if (!props.job || loading.value) return "";
  const produced = Number(rowModel.value?.metrics?.produced_total || 0);
  if (filteredRows.value.length > 0 || produced <= 0) return "";
  return `任务显示已采集 ${produced} 条线索，明细同步中，请稍后刷新。`;
});

function openLink(url) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function resetState() {
  keyword.value = "";
  actionType.value = "all";
  page.value = 1;
}
</script>

<style scoped>
.outreach-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.outreach-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
}

.toolbar-label {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--el-fill-color-light);
}

.summary-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.pager-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pager-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
