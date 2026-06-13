<template>
  <el-dialog
    :model-value="visible"
    title="创建异步任务"
    width="640px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <p class="dialog-desc">
      任务将在后台队列中执行。盈小蚁 JSON 可粘贴 <code>raw_payload</code> 或完整 compile-and-create 结构；含触达字段时编排为 5 步 lead-acquisition。
    </p>
    <el-form label-width="96px" class="job-form">
      <el-form-item label="任务内容" required>
        <el-input
          v-model="form.message"
          type="textarea"
          :rows="5"
          placeholder="例如：/pipeline-keyword-video-comments keyword=淋浴房 video_limit=5 days=3"
        />
      </el-form-item>
      <el-form-item label="模型">
        <el-select v-model="form.provider" style="width: 140px">
          <el-option label="DeepSeek" value="deepseek" />
          <el-option label="OpenAI" value="openai" />
        </el-select>
      </el-form-item>
      <el-form-item label="运行模式">
        <el-radio-group v-model="form.mode">
          <el-radio value="agent">Agent</el-radio>
          <el-radio value="plan">Plan</el-radio>
          <el-radio value="ask">Ask</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="审批策略">
        <el-radio-group v-model="form.run_mode">
          <el-radio value="auto">工具自动批准</el-radio>
          <el-radio value="confirm">工具需审批</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="自动执行">
        <el-switch v-model="form.auto_execute" active-text="创建后立即入队执行" inactive-text="仅创建，稍后手动启动" />
      </el-form-item>
      <el-form-item label="自动重启">
        <el-switch v-model="form.auto_restart" active-text="失败时自动重试" inactive-text="失败即停止" />
        <span v-if="form.auto_restart" class="field-hint">最多重试 {{ form.max_retries }} 次</span>
      </el-form-item>
      <el-form-item label="调度参数">
        <div class="param-row">
          <div class="param-item">
            <span class="param-label">优先级</span>
            <el-input-number v-model="form.priority" :min="1" :max="10" size="small" />
          </div>
          <div class="param-item">
            <span class="param-label">重试</span>
            <el-input-number v-model="form.max_retries" :min="0" :max="5" size="small" />
          </div>
          <div class="param-item">
            <span class="param-label">超时(秒)</span>
            <el-input-number v-model="form.timeout_seconds" :min="60" :max="3600" :step="60" size="small" />
          </div>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">提交任务</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from "vue";

const props = defineProps({
  visible: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
});

const emit = defineEmits(["update:visible", "submit"]);

const defaultForm = () => ({
  message: "",
  provider: "deepseek",
  mode: "agent",
  run_mode: "auto",
  auto_execute: true,
  auto_restart: true,
  timeout_seconds: 600,
  max_retries: 1,
  priority: 5,
});

const form = ref(defaultForm());

watch(
  () => props.visible,
  (open) => {
    if (open) form.value = defaultForm();
  },
);

function onSubmit() {
  if (!form.value.message.trim()) return;
  emit("submit", { ...form.value, message: form.value.message.trim() });
}
</script>

<style scoped>
.dialog-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.param-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-label {
  font-size: 12px;
  color: #94a3b8;
}

.field-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #94a3b8;
}
</style>
