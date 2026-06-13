<template>
  <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">创建任务</h2>
          <p class="page-subtitle">选择任务模板并填写参数；当前支持 lead-crawl（只抓线索）。</p>
        </div>
      </div>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <div class="panel">
        <el-form label-width="120px" class="create-form">
          <el-form-item label="任务模板" required>
            <el-select v-model="form.template_id" style="width: 280px" @change="onTemplateChange">
              <el-option v-for="tpl in templates" :key="tpl.template_id" :label="tpl.name" :value="tpl.template_id">
                <span>{{ tpl.name }}</span>
                <span class="tpl-desc">{{ tpl.description }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="任务名称">
            <el-input v-model="form.task_name" placeholder="例如：深圳餐饮老板线索" />
          </el-form-item>
          <el-form-item label="关键词" required>
            <el-input v-model="form.keyword" placeholder="例如：团餐配送" />
          </el-form-item>
          <el-form-item label="平台" required>
            <el-radio-group v-model="form.platform">
              <el-radio value="douyin">抖音</el-radio>
              <el-radio value="xiaohongshu">小红书</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="地区">
            <el-input v-model="form.region" placeholder="可选，如：深圳" clearable />
          </el-form-item>
          <el-form-item label="评论天数">
            <el-radio-group v-model="form.comment_days">
              <el-radio :value="3">3天</el-radio>
              <el-radio :value="5">5天</el-radio>
              <el-radio :value="7">7天</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="目标线索数">
            <el-input-number v-model="form.target_leads" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="计划执行">
            <el-date-picker
              v-model="form.scheduled_at"
              type="datetime"
              placeholder="不选则立即排队"
              clearable
              style="width: 280px"
            />
          </el-form-item>
          <el-form-item label="立即执行">
            <el-switch v-model="form.async_mode" active-text="无计划时间时自动执行" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitting" @click="submit">创建任务</el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { createTask, fetchTaskTemplates } from "../api/tasks";

const router = useRouter();
const templates = ref([]);
const submitting = ref(false);
const errorMessage = ref("");
const form = ref({
  template_id: "lead-crawl",
  task_name: "",
  keyword: "",
  platform: "douyin",
  region: "",
  comment_days: 3,
  target_leads: 100,
  async_mode: true,
  scheduled_at: null,
});

function onTemplateChange() {
  if (form.value.template_id !== "lead-crawl") {
    ElMessage.warning("lead-acquisition 模板执行器尚未启用，请先选择「线索抓取」");
    form.value.template_id = "lead-crawl";
  }
}

async function loadTemplates() {
  try {
    const data = await fetchTaskTemplates();
    templates.value = data.items || [];
  } catch (err) {
    errorMessage.value = err.message;
  }
}

async function submit() {
  if (!form.value.keyword.trim()) {
    ElMessage.warning("请填写关键词");
    return;
  }
  submitting.value = true;
  errorMessage.value = "";
  try {
    const row = await createTask({
      template_id: form.value.template_id,
      name: form.value.task_name || undefined,
      async: form.value.async_mode,
      scheduled_at: form.value.scheduled_at || undefined,
      spec: {
        task_name: form.value.task_name,
        keyword: form.value.keyword.trim(),
        platform: form.value.platform,
        region: form.value.region || null,
        crawl: {
          comment_days: form.value.comment_days,
          target_leads: form.value.target_leads,
        },
      },
    });
    ElMessage.success("任务已创建");
    router.push(`/tasks/${row.task_id}`);
  } catch (err) {
    errorMessage.value = err.message || "创建失败";
  } finally {
    submitting.value = false;
  }
}

onMounted(loadTemplates);
</script>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-header .back-btn {
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
.create-form {
  max-width: 640px;
}
.tpl-desc {
  margin-left: 8px;
  color: #999;
  font-size: 12px;
}
</style>
