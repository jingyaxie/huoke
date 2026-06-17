const AUTO_INTENTS = new Set(["keyword_auto"]);
const MANUAL_INTENTS = new Set(["single_video", "account_home"]);

export const DEFAULT_ACQUISITION_FILTER = {
  keyword: "",
  platform: "",
  status: "",
  sort: "desc",
};

export const ACQUISITION_STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "抓取中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已关闭" },
];

export const ACQUISITION_PLATFORM_OPTIONS = [
  { value: "", label: "全部平台" },
  { value: "douyin", label: "抖音" },
  { value: "xiaohongshu", label: "小红书" },
  { value: "kuaishou", label: "快手" },
];

export function getJobIntent(job) {
  const config = getJobConfig(job);
  const intent = String(config.intent || config.acquisition_mode || "").trim().toLowerCase();
  if (intent) return intent;

  const message = String(job?.message || "");
  if (message.includes("单条视频")) return "single_video";
  if (message.includes("账号主页")) return "account_home";
  if (message.includes("关键词获客")) return "keyword_auto";
  return null;
}

export function getJobConfig(job) {
  const orchConfig = job?.result?.orchestration?.config;
  if (orchConfig && typeof orchConfig === "object") return orchConfig;
  const syncOrch = job?.sync?.summary?.orchestration;
  if (syncOrch?.config && typeof syncOrch.config === "object") return syncOrch.config;
  if (job?.sync?.task?.config && typeof job.sync.task.config === "object") return job.sync.task.config;
  return {};
}

export function getJobMetrics(job) {
  const config = getJobConfig(job);
  const sync = job?.sync && typeof job.sync === "object" ? job.sync : {};
  const progress = sync.progress && typeof sync.progress === "object" ? sync.progress : {};
  const ledger =
    (sync.summary?.task_ledger && typeof sync.summary.task_ledger === "object" ? sync.summary.task_ledger : null)
    || (job?.result?.task_ledger && typeof job.result.task_ledger === "object" ? job.result.task_ledger : null)
    || {};
  const stats = ledger.stats && typeof ledger.stats === "object" ? ledger.stats : {};
  const outreachEvents = Array.isArray(sync.outreach_events) ? sync.outreach_events : [];

  const countFromEvents = (action) =>
    outreachEvents.filter((row) => String(row?.action || row?.action_type || "").toLowerCase() === action).length;

  const replyOk = Number(stats.reply?.ok || countFromEvents("reply") || 0);
  const dmOk = Number(stats.dm?.ok || countFromEvents("dm") || 0);
  const followOk = Number(stats.follow?.ok || countFromEvents("follow") || 0);

  const requestedTarget = Number(config.target_count || progress.target_leads || 0);
  const producedTotal = Number(
    progress.total_leads_collected
    || progress.leads_collected
    || sync.stats?.leads_total
    || (Array.isArray(sync.leads) ? sync.leads.length : 0)
    || 0,
  );
  const progressPrecise = Number(progress.leads_qualified || 0);

  return {
    requested_target: requestedTarget,
    produced_total: producedTotal,
    progress_precise: progressPrecise,
    comment_count: replyOk,
    dm_count: dmOk,
    follow_count: followOk,
  };
}

export function getJobRowModel(job) {
  const config = getJobConfig(job);
  const metrics = getJobMetrics(job);
  const intent = getJobIntent(job);
  const keywords = Array.isArray(config.keywords)
    ? config.keywords
    : config.keyword
      ? [config.keyword]
      : [];
  const name = String(config.task_name || job?.message?.split("：")[0] || job?.job_id || "").trim();
  const accountLabel = String(
    config.constraints?.account_label
    || config.account_label
    || job?.account_id
    || "",
  ).trim();
  const inputUrl = config.input_url || config.video_url || config.profile_url || "";
  return {
    job,
    config,
    metrics,
    intent,
    name,
    account_label: accountLabel,
    keywords,
    input_url: inputUrl,
    platform: job?.platform || config.platform || "",
    created_at: job?.created_at || job?.updated_at || null,
    status: job?.status || "",
    error: job?.error || job?.dead_letter_reason || "",
  };
}

export function filterJobsByIntent(jobs, intents) {
  const allowed = intents instanceof Set ? intents : new Set(intents);
  return (jobs || []).filter((job) => {
    const intent = getJobIntent(job);
    return intent && allowed.has(intent);
  });
}

export function filterAutoJobs(jobs) {
  return filterJobsByIntent(jobs, AUTO_INTENTS);
}

export function filterManualJobs(jobs) {
  return filterJobsByIntent(jobs, MANUAL_INTENTS);
}

export function mapStatusForFilter(status) {
  if (status === "completed") return "completed";
  if (status === "cancelled") return "cancelled";
  if (status === "dead_letter") return "failed";
  if (status === "pending") return "queued";
  return status;
}

export function jobStatusLabel(status) {
  const map = {
    queued: "排队中",
    pending: "排队中",
    running: "抓取中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已关闭",
    dead_letter: "失败",
  };
  return map[status] || status || "未知";
}

export function jobStatusTagType(status) {
  if (status === "completed") return "success";
  if (status === "running" || status === "queued" || status === "pending") return "warning";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  return "";
}

export function platformLabel(platform) {
  if (platform === "xiaohongshu") return "小红书";
  if (platform === "kuaishou") return "快手";
  if (platform === "douyin") return "抖音";
  return platform || "—";
}

export function manualIntentLabel(intent) {
  if (intent === "single_video") return "单条视频获客";
  if (intent === "account_home") return "账号客户";
  return intent || "—";
}

export function manualAccountLabel(row) {
  if (row.account_label) return row.account_label;
  if (row.name && row.name !== row.job?.job_id) return row.name;
  const url = row.input_url || "";
  if (!url) return "博主主页获客";
  try {
    const slug = decodeURIComponent(new URL(url).pathname.split("/").filter(Boolean).pop() || "").slice(0, 24);
    return slug ? `博主-${slug}` : "博主主页获客";
  } catch {
    return "博主主页获客";
  }
}

export function avatarInitial(text) {
  const value = String(text || "?").trim();
  return value ? value.slice(0, 1) : "?";
}

export function formatJobTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

export function jobSummaryLine(job) {
  const row = getJobRowModel(job);
  if (row.keywords.length) {
    const region = row.config.region ? ` · ${row.config.region}` : "";
    return `关键词：${row.keywords.join("、")}${region}`;
  }
  if (row.input_url) return row.input_url;
  return job?.message || job?.job_id || "";
}

export function matchesJobFilter(job, filter) {
  const row = getJobRowModel(job);
  if (filter.platform && row.platform !== filter.platform) return false;
  if (filter.status) {
    const mapped = mapStatusForFilter(job.status);
    if (mapped !== filter.status && job.status !== filter.status) return false;
  }
  if (filter.keyword?.trim()) {
    const kw = filter.keyword.trim().toLowerCase();
    const haystack = [
      row.name,
      row.account_label,
      ...(row.keywords || []),
      row.input_url,
      job?.message,
      job?.job_id,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(kw)) return false;
  }
  return true;
}

export function sortJobsByCreated(jobs, sort = "desc") {
  return [...(jobs || [])].sort((a, b) => {
    const ta = new Date(a.created_at || a.updated_at || 0).getTime();
    const tb = new Date(b.created_at || b.updated_at || 0).getTime();
    return sort === "asc" ? ta - tb : tb - ta;
  });
}

export function computeDashboardFromJobs(jobs) {
  const rows = (jobs || []).map((job) => getJobRowModel(job));
  return {
    running_tasks: rows.filter((row) => row.status === "running").length,
    queued_tasks: rows.filter((row) => ["queued", "pending"].includes(row.status)).length,
    precise_customers: rows.reduce((sum, row) => sum + Number(row.metrics.progress_precise || 0), 0),
    total_leads: rows.reduce((sum, row) => sum + Number(row.metrics.produced_total || 0), 0),
    dm_count: rows.reduce((sum, row) => sum + Number(row.metrics.dm_count || 0), 0),
    follow_count: rows.reduce((sum, row) => sum + Number(row.metrics.follow_count || 0), 0),
  };
}

export function getOutreachRows(job) {
  const sync = job?.sync && typeof job.sync === "object" ? job.sync : {};
  const leads = Array.isArray(sync.leads) ? sync.leads : [];
  const events = Array.isArray(sync.outreach_events) ? sync.outreach_events : [];
  if (events.length) {
    return events.map((event) => ({
      id: event.id || `${event.lead_id || ""}-${event.executed_at || ""}`,
      nickname: event.nickname || event.user_nickname || event.author_nickname || "—",
      avatar: event.avatar_url || event.author_avatar || "",
      comment_at: event.comment_at || event.source_comment_at || "",
      video_title: event.video_title || "",
      comment_content: event.comment_content || event.source_comment || "",
      is_precise: event.is_precise ?? event.precise ?? false,
      reply_content: event.reply_content || (event.action === "reply" ? event.content : ""),
      dm_content: event.dm_content || (event.action === "dm" ? event.content : ""),
      location_text: event.location_text || event.location || "",
      executed_at: event.executed_at || event.created_at || "",
      profile_url: event.profile_url || event.user_profile_url || "",
      video_url: event.video_url || "",
    }));
  }
  return leads.map((lead) => ({
    id: lead.id || lead.lead_id || lead.comment_id || Math.random().toString(36).slice(2),
    nickname: lead.nickname || lead.user_nickname || lead.author_nickname || "—",
    avatar: lead.avatar_url || lead.author_avatar || "",
    comment_at: lead.comment_at || lead.created_at || "",
    video_title: lead.video_title || "",
    comment_content: lead.comment_content || lead.comment || "",
    is_precise: lead.is_precise ?? lead.qualified ?? false,
    reply_content: lead.reply_content || "",
    dm_content: lead.dm_content || "",
    location_text: lead.location_text || lead.location || "",
    executed_at: lead.outreach_at || "",
    profile_url: lead.profile_url || lead.user_profile_url || "",
    video_url: lead.video_url || "",
  }));
}

export function filterOutreachRows(rows, { keyword = "", actionType = "all" } = {}) {
  const kw = keyword.trim().toLowerCase();
  return (rows || []).filter((row) => {
    if (actionType !== "all") {
      if (actionType === "comment" && !row.reply_content) return false;
      if (actionType === "dm" && !row.dm_content) return false;
      if (actionType === "follow" && !row.executed_at) return false;
    }
    if (!kw) return true;
    const haystack = [row.nickname, row.comment_content, row.reply_content, row.dm_content, row.video_title]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(kw);
  });
}
