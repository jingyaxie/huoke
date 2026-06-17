<template>
  <el-dialog
    v-model="visible"
    title="任务已暂停"
    width="560px"
    destroy-on-close
    class="suspend-dialog"
    @closed="$emit('closed')"
  >
    <div v-if="brief" class="suspend-body">
      <div class="suspend-section">
        <div class="section-label">当前原因</div>
        <p class="section-text">{{ brief.reason }}</p>
      </div>

      <div class="suspend-section">
        <div class="section-label">后续计划</div>
        <p class="section-text">{{ brief.next_action }}</p>
      </div>

      <div v-if="brief.resume_at_display" class="suspend-meta">
        <span class="meta-label">自动恢复时间</span>
        <span>{{ brief.resume_at_display }}</span>
      </div>
      <div v-else class="suspend-meta muted">
        <span class="meta-label">自动恢复时间</span>
        <span>未设定（仅支持手动继续）</span>
      </div>

      <p class="suspend-hint">{{ brief.manual_resume }}</p>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" @click="onResume">继续执行</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  brief: { type: Object, default: null },
});

const emit = defineEmits(["update:modelValue", "resume", "closed"]);

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

function onResume() {
  emit("resume");
  visible.value = false;
}
</script>

<style scoped>
.suspend-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.suspend-section {
  padding: 12px 14px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
  margin-bottom: 6px;
}

.section-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.suspend-meta {
  display: flex;
  gap: 8px;
  font-size: 13px;
  color: #475569;
}

.suspend-meta.muted {
  color: #94a3b8;
}

.meta-label {
  flex-shrink: 0;
  color: #64748b;
}

.suspend-hint {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}
</style>
