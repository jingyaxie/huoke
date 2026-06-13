import { getAccountId, getApiKey, getAccessToken, getTenantId, getApiBaseUrl } from "./http";

const baseURL = getApiBaseUrl();

function taskHeaders() {
  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Id": getTenantId(),
    "X-Account-Id": getAccountId(),
  };
  const apiKey = getApiKey();
  if (apiKey) headers["X-API-Key"] = apiKey;
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function parseJson(resp) {
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `请求失败 (${resp.status})`);
  }
  return resp.json();
}

export async function fetchTaskTemplates() {
  const resp = await fetch(`${baseURL}/open/task-templates`, { headers: taskHeaders() });
  return parseJson(resp);
}

export async function fetchTaskTemplate(templateId, version) {
  const qs = version ? `?version=${encodeURIComponent(version)}` : "";
  const resp = await fetch(`${baseURL}/open/task-templates/${encodeURIComponent(templateId)}${qs}`, {
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function fetchTasks(params = {}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.template_id) qs.set("template_id", params.template_id);
  if (params.platform) qs.set("platform", params.platform);
  if (params.source) qs.set("source", params.source);
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.limit != null) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const resp = await fetch(`${baseURL}/open/tasks${suffix}`, { headers: taskHeaders() });
  return parseJson(resp);
}

export async function fetchTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}`, {
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function fetchTaskPhases(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/phases`, {
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function compileTask(payload) {
  const resp = await fetch(`${baseURL}/open/tasks/compile`, {
    method: "POST",
    headers: taskHeaders(),
    body: JSON.stringify(payload),
  });
  return parseJson(resp);
}

export async function compileAndCreateTask(payload) {
  const resp = await fetch(`${baseURL}/open/tasks/compile-and-create`, {
    method: "POST",
    headers: taskHeaders(),
    body: JSON.stringify(payload),
  });
  return parseJson(resp);
}

export async function createTask(payload) {
  const resp = await fetch(`${baseURL}/open/tasks`, {
    method: "POST",
    headers: taskHeaders(),
    body: JSON.stringify(payload),
  });
  return parseJson(resp);
}

export async function pauseTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/pause`, {
    method: "POST",
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function resumeTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/resume`, {
    method: "POST",
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function cancelTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function submitTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/submit`, {
    method: "POST",
    headers: taskHeaders(),
  });
  return parseJson(resp);
}

export async function restartTask(taskId, { fresh = false } = {}) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}/restart`, {
    method: "POST",
    headers: taskHeaders(),
    body: JSON.stringify({ fresh }),
  });
  return parseJson(resp);
}

export async function deleteTask(taskId) {
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
    headers: taskHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `请求失败 (${resp.status})`);
  }
}

export async function patchTaskSpec(taskId, patch) {
  const body = {};
  if (patch.headless !== undefined) body.headless = patch.headless;
  if (patch.auto_restart !== undefined) body.auto_restart = patch.auto_restart;
  if (patch.max_retries !== undefined) body.max_retries = patch.max_retries;
  const resp = await fetch(`${baseURL}/open/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: taskHeaders(),
    body: JSON.stringify(body),
  });
  return parseJson(resp);
}

export const SAMPLE_YINGXIAOYI_PAYLOAD = {
  task_name: "深圳团餐线索",
  keyword: "团餐配送",
  platform: "douyin",
  region: "深圳",
  target_count: 100,
  comment_days: 3,
};
