<template>
  <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">编译预览</h2>
          <p class="page-subtitle">粘贴外部原始 JSON，预览编译结果后再创建任务；不创建也可用于联调测试。</p>
        </div>
      </div>

      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

      <div class="panel compile-toolbar">
        <el-form :inline="true">
          <el-form-item label="Adapter">
            <el-select v-model="adapterId" style="width: 200px">
              <el-option label="yingxiaoyi-lead-v1" value="yingxiaoyi-lead-v1" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button @click="loadSample">加载示例</el-button>
            <el-button type="primary" :loading="compiling" @click="runCompile">编译预览</el-button>
            <el-button type="success" :loading="creating" :disabled="!compileResult?.ok" @click="runCreate">
              编译并创建
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="compile-grid">
        <div class="panel compile-col">
          <h3 class="col-title">原始 JSON</h3>
          <el-input
            v-model="rawJsonText"
            type="textarea"
            :rows="22"
            placeholder='{"keyword":"团餐","platform":"douyin","target_count":100}'
            class="json-input"
          />
        </div>

        <div class="panel compile-col">
          <h3 class="col-title">编译结果</h3>
          <div v-if="!compileResult" class="empty-hint">点击「编译预览」查看 plan 与 spec</div>
          <template v-else>
            <div class="compile-meta">
              <el-tag :type="compileResult.ok ? 'success' : 'danger'">
                {{ compileResult.ok ? "校验通过" : "校验失败" }}
              </el-tag>
              <el-tag v-if="plan.method" type="info">{{ methodLabel(plan.method) }}</el-tag>
              <el-tag v-if="plan.confidence != null">置信度 {{ Math.round(plan.confidence * 100) }}%</el-tag>
              <el-tag v-if="plan.template_id">{{ plan.template_id }}</el-tag>
            </div>
            <p v-if="plan.reasoning" class="reasoning">{{ plan.reasoning }}</p>
            <p v-if="plan.validation_error" class="validation-error">{{ plan.validation_error }}</p>
            <div v-if="plan.unmapped_fields?.length" class="unmapped">
              未映射字段：{{ plan.unmapped_fields.join(", ") }}
            </div>
            <el-tabs v-model="resultTab" class="result-tabs">
              <el-tab-pane label="编译 Plan" name="plan">
                <pre class="code-block">{{ formatJson(plan) }}</pre>
              </el-tab-pane>
              <el-tab-pane label="最终 Spec" name="spec">
                <pre class="code-block">{{ formatJson(plan.spec) }}</pre>
              </el-tab-pane>
              <el-tab-pane v-if="compileResult.create_request" label="Create Request" name="create">
                <pre class="code-block">{{ formatJson(compileResult.create_request) }}</pre>
              </el-tab-pane>
            </el-tabs>
          </template>
        </div>
      </div>
    </div>
</template>

<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { SAMPLE_YINGXIAOYI_PAYLOAD, compileAndCreateTask, compileTask } from "../api/tasks";

const router = useRouter();
const adapterId = ref("yingxiaoyi-lead-v1");
const rawJsonText = ref(JSON.stringify(SAMPLE_YINGXIAOYI_PAYLOAD, null, 2));
const compiling = ref(false);
const creating = ref(false);
const errorMessage = ref("");
const compileResult = ref(null);
const plan = ref({});
const resultTab = ref("plan");

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function methodLabel(method) {
  if (method === "rule") return "规则编译";
  if (method === "llm") return "LLM 编译";
  if (method === "hybrid") return "混合编译";
  return method;
}

function parseRawPayload() {
  try {
    const parsed = JSON.parse(rawJsonText.value || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("JSON 必须是对象");
    }
    return parsed;
  } catch (err) {
    throw new Error(`JSON 解析失败: ${err.message}`);
  }
}

function loadSample() {
  rawJsonText.value = JSON.stringify(SAMPLE_YINGXIAOYI_PAYLOAD, null, 2);
  compileResult.value = null;
  errorMessage.value = "";
}

async function runCompile() {
  compiling.value = true;
  errorMessage.value = "";
  try {
    const raw_payload = parseRawPayload();
    const resp = await compileTask({
      raw_payload,
      adapter_id: adapterId.value,
      source: "external",
    });
    compileResult.value = resp;
    plan.value = resp.plan || {};
    if (!resp.ok) {
      ElMessage.warning(resp.plan?.validation_error || "编译未通过");
    } else {
      ElMessage.success("编译预览完成");
    }
  } catch (err) {
    errorMessage.value = err.message || "编译失败";
  } finally {
    compiling.value = false;
  }
}

async function runCreate() {
  creating.value = true;
  errorMessage.value = "";
  try {
    const raw_payload = parseRawPayload();
    const resp = await compileAndCreateTask({
      raw_payload,
      adapter_id: adapterId.value,
      source: "external",
      auto_submit: false,
    });
    compileResult.value = resp.compile;
    plan.value = resp.compile?.plan || {};
    if (!resp.task) {
      throw new Error(resp.compile?.plan?.validation_error || "创建失败");
    }
    ElMessage.success("任务已创建");
    router.push(`/tasks/${resp.task.task_id}`);
  } catch (err) {
    errorMessage.value = err.message || "创建失败";
  } finally {
    creating.value = false;
  }
}
</script>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.back-btn {
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
.compile-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 960px) {
  .compile-grid {
    grid-template-columns: 1fr;
  }
}
.col-title {
  margin: 0 0 12px;
  font-size: 15px;
}
.json-input :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.compile-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.reasoning {
  margin: 0 0 8px;
  color: #555;
  font-size: 13px;
}
.validation-error {
  margin: 0 0 8px;
  color: var(--el-color-danger);
  font-size: 13px;
}
.unmapped {
  margin-bottom: 8px;
  font-size: 12px;
  color: #888;
}
.empty-hint {
  color: #999;
  padding: 24px 0;
}
.code-block {
  margin: 0;
  padding: 12px;
  background: #f6f8fa;
  border-radius: 6px;
  overflow: auto;
  font-size: 12px;
  max-height: 420px;
}
</style>
