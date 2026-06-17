<template>
  <div class="interaction-fields">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="评论/私信随机间隔">
          <div class="interval-row">
            <el-input-number
              :model-value="modelValue.comment_dm_interval_seconds_min"
              :min="1"
              :max="600"
              @update:model-value="patch({ comment_dm_interval_seconds_min: $event })"
            />
            <span>-</span>
            <el-input-number
              :model-value="modelValue.comment_dm_interval_seconds_max"
              :min="1"
              :max="600"
              @update:model-value="patch({ comment_dm_interval_seconds_max: $event })"
            />
            <span class="unit">秒</span>
          </div>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="评论/私信百分比">
          <el-input-number
            :model-value="modelValue.comment_dm_percentage"
            :min="0"
            :max="100"
            @update:model-value="patch({ comment_dm_percentage: $event })"
          />
          <span class="unit">%</span>
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="每日关注上限">
          <el-input-number
            :model-value="modelValue.follow_per_day"
            :min="0"
            :max="1000"
            @update:model-value="patch({ follow_per_day: $event })"
          />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="每日私信上限">
          <el-input-number
            :model-value="modelValue.dm_per_day"
            :min="0"
            :max="1000"
            @update:model-value="patch({ dm_per_day: $event })"
          />
        </el-form-item>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({
      comment_dm_interval_seconds_min: 10,
      comment_dm_interval_seconds_max: 30,
      comment_dm_percentage: 50,
      follow_per_day: 30,
      dm_per_day: 30,
      batch_cooldown_minutes: 8,
    }),
  },
});

const emit = defineEmits(["update:modelValue"]);

function patch(partial) {
  emit("update:modelValue", { ...props.modelValue, ...partial });
}
</script>

<style scoped>
.interval-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unit {
  margin-left: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
