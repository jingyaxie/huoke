const AUTO_INTENTS = new Set(["keyword_auto"]);
const MANUAL_INTENTS = new Set(["single_video", "account_home"]);

export const DEFAULT_ACQUISITION_FILTER = {
  keyword: "",
  platform: "",
  status: "",
  sort: "desc",
  dateRange: null,
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

function parseJsonMessage(message) {
  const text = String(message || "").trim();
  if (!text.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function configFromTaskBrief(brief) {
  if (!brief || typeof brief !== "object") return null;
  const goals = brief.goals && typeof brief.goals === "object" ? brief.goals : {};
  const constraints = brief.constraints && typeof brief.constraints === "object" ? brief.constraints : {};
  const inputUrl = goals.input_url || goals.video_url || goals.profile_url || "";
  const acquisitionMode = String(goals.acquisition_mode || "").trim().toLowerCase();
  let intent = acquisitionMode;
  if (!intent) {
    if (goals.video_url || (inputUrl && !goals.profile_url && acquisitionMode !== "account_home")) {
      intent = "single_video";
    } else if (goals.profile_url) {
      intent = "account_home";
    } else if (brief.keyword) {
      intent = "keyword_auto";
    }
  }
  return {
    intent,
    acquisition_mode: acquisitionMode || intent,
    task_name: brief.title,
    keyword: brief.keyword,
    keywords: brief.keyword ? [brief.keyword] : [],
    platform: brief.platform,
    region: brief.region,
    target_count: goals.target_leads ?? goals.target_count,
    comment_days: goals.comment_days,
    input_url: inputUrl,
    video_url: goals.video_url,
    profile_url: goals.profile_url,
    constraints,
  };
}

function configFromMessagePayload(payload) {
  if (!payload || typeof payload !== "object") return null;
  const constraints = payload.constraints && typeof payload.constraints === "object" ? payload.constraints : {};
  const inputUrl = payload.input_url || payload.video_url || payload.profile_url || "";
  let intent = String(payload.intent || payload.acquisition_mode || "").trim().toLowerCase();
  if (!intent) {
    if (payload.video_url || inputUrl.includes("/video/")) {
      intent = "single_video";
    } else if (payload.profile_url || (inputUrl && !payload.keyword)) {
      intent = "account_home";
    } else if (payload.keyword) {
      intent = "keyword_auto";
    }
  }
  return {
    ...payload,
    intent,
    acquisition_mode: payload.acquisition_mode || intent,
    task_name: payload.task_name || payload.name,
    keywords: payload.keyword ? [payload.keyword] : payload.keywords,
    target_count: payload.target_count ?? payload.target_leads,
    constraints,
  };
}

export function getJobIntent(job) {
  const config = getJobConfig(job);
  const intent = String(config.intent || config.acquisition_mode || "").trim().toLowerCase();
  if (intent) return intent;

  const brief = job?.result?.orchestration?.task_brief;
  const briefConfig = configFromTaskBrief(brief);
  if (briefConfig?.intent) return briefConfig.intent;

  const message = String(job?.message || "");
  if (message.includes("单条视频")) return "single_video";
  if (message.includes("账号主页")) return "account_home";
  if (message.includes("关键词获客")) return "keyword_auto";
  return null;
}

export function getJobConfig(job) {
  const orchConfig = job?.result?.orchestration?.config;
  if (orchConfig && typeof orchConfig === "object") return orchConfig;

  const briefConfig = configFromTaskBrief(job?.result?.orchestration?.task_brief);
  if (briefConfig) return briefConfig;

  const messageConfig = configFromMessagePayload(parseJsonMessage(job?.message));
  if (messageConfig) return messageConfig;

  const syncOrch = job?.sync?.summary?.orchestration;
  if (syncOrch?.config && typeof syncOrch.config === "object") return syncOrch.config;
  const syncBriefConfig = configFromTaskBrief(syncOrch?.task_brief);
  if (syncBriefConfig) return syncBriefConfig;
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

export function isJobSuspended(job) {
  const state = job?.result?.supervisor_state;
  return job?.status === "pending" && state?.suspended === true;
}

export function getJobSuspendReason(job) {
  if (!isJobSuspended(job)) return "";
  const state = job?.result?.supervisor_state || {};
  const wake = String(
    state.wake_reason
    || job?.result?.summary
    || job?.result?.orchestration?.execution_note
    || "任务已挂起，等待恢复",
  ).trim();
  if (wake.includes("连续") && wake.includes("无进展")) {
    const stats = job?.result?.execution_stats || {};
    const comments = stats.comments_captured || stats.comments_persisted || 0;
    const qualified = stats.progress_precise || state.leads_qualified || 0;
    if (comments > 0 && qualified === 0) {
      return `${wake}。已抓取 ${comments} 条评论但暂无精准线索，请点击「继续执行」浏览更多视频，或放宽评估标准。`;
    }
  }
  return wake;
}

export function getJobDisplayStatus(job) {
  const status = job?.status || "";
  if (status === "retrying") return "retrying";
  if (status === "pending") {
    return isJobSuspended(job) ? "suspended" : "waiting_start";
  }
  return status;
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
  const displayStatus = getJobDisplayStatus(job);
  const suspendReason = getJobSuspendReason(job);
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
    display_status: displayStatus,
    suspend_reason: suspendReason,
    error: job?.error || job?.dead_letter_reason || suspendReason,
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
  if (status === "suspended" || status === "waiting_start") return "queued";
  if (status === "pending") return "queued";
  return status;
}

export function jobStatusLabel(status) {
  const map = {
    queued: "排队中",
    pending: "待启动",
    waiting_start: "待启动",
    suspended: "已挂起",
    running: "抓取中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已关闭",
    dead_letter: "失败",
    retrying: "重试中",
  };
  return map[status] || status || "未知";
}

export function jobStatusTagType(status) {
  if (status === "running" || status === "retrying") return "primary";
  if (status === "queued") return "warning";
  if (status === "suspended") return "suspended";
  if (status === "pending" || status === "waiting_start") return "waiting";
  if (status === "completed") return "success";
  if (status === "cancelled") return "info";
  if (status === "failed" || status === "dead_letter") return "danger";
  return "info";
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
    const mapped = mapStatusForFilter(row.display_status || job.status);
    if (mapped !== filter.status && (row.display_status || job.status) !== filter.status) return false;
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
  if (Array.isArray(filter.dateRange) && filter.dateRange.length === 2) {
    const [start, end] = filter.dateRange;
    const created = new Date(job.created_at || job.updated_at || 0).getTime();
    if (!Number.isFinite(created)) return false;
    const startMs = new Date(start).setHours(0, 0, 0, 0);
    const endMs = new Date(end).setHours(23, 59, 59, 999);
    if (created < startMs || created > endMs) return false;
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
    running_tasks: rows.filter((row) => ["running", "retrying"].includes(row.status)).length,
    queued_tasks: rows.filter((row) => ["queued", "waiting_start"].includes(row.display_status)).length,
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
