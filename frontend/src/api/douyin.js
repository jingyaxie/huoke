import http, { getAccountId, getPlatformId, getTenantId, resolveVncUrl, setTenantId } from "./http";
import {
  fetchAccountPlatformLoginStatus,
  triggerAccountPlatformLogin,
} from "./accounts";

export { getTenantId, setTenantId };

function platformPath(suffix = "") {
  const platform = getPlatformId();
  return `/platforms/${platform}${suffix}`;
}

export function fetchPlatforms() {
  return http.get("/platforms").then((res) => res.data);
}

export function fetchOverview(days = 7) {
  return http.get(platformPath("/overview"), { params: { days } }).then((res) => res.data);
}

export function triggerCrawl(limit = 100) {
  return http.post(platformPath("/crawl/hot"), null, { params: { limit } }).then((res) => res.data);
}

export function triggerLogin(showBrowser = true) {
  return http
    .post(platformPath("/login"), { show_browser: showBrowser, tenant_id: getTenantId() })
    .then((res) => res.data);
}

export function fetchLoginStatus() {
  return fetchAccountPlatformLoginStatus(getAccountId(), getPlatformId());
}

export function fetchServerLoginUrl() {
  return Promise.resolve({ url: resolveVncUrl() });
}

export function triggerServerLogin() {
  return triggerAccountPlatformLogin(getAccountId(), getPlatformId());
}

export function uploadStorageState(storageState) {
  const tenantId = getTenantId();
  const platform = getPlatformId();
  return http
    .put(`/platforms/${platform}/tenants/${encodeURIComponent(tenantId)}/storage-state`, {
      storage_state: storageState,
    })
    .then((res) => res.data);
}

function normalizeVideoCommentResponse(data, fallbackUrl) {
  const payload = data.data || data;
  return {
    video_url: payload.video_url || payload.note_url || fallbackUrl,
    output_file: data.report_file || "",
    total_comments_captured: payload.total_comments_captured ?? 0,
    api_total_top_comments: payload.api_total_top_comments ?? 0,
    cache: data.cache,
  };
}

function normalizeKeywordCommentResponse(data) {
  const payload = data.data || data;
  const items = (payload.items || []).map((item) => ({
    video_url: item.video_url || item.note_url || "",
    output_file: item.report_file || "",
    total_comments_captured: item.total_comments_captured ?? 0,
    api_total_top_comments: item.api_total_top_comments ?? 0,
  }));
  return {
    keyword: payload.keyword,
    videos_found: payload.videos_found ?? items.length,
    crawled: items.length,
    diagnostic: data.diagnostic,
    guest_mode: payload.guest_mode,
    session_mode: payload.session_mode,
    items,
    cache: data.cache,
  };
}

export function crawlVideoComments(videoUrl, showBrowser = false, maxComments = 200) {
  const platform = getPlatformId();
  const path =
    platform === "xiaohongshu"
      ? `/platforms/${platform}/comments/notes`
      : `/platforms/${platform}/comments/videos`;
  const body =
    platform === "xiaohongshu"
      ? { note_url: videoUrl, max_comments: maxComments, show_browser: showBrowser }
      : { video_url: videoUrl, max_comments: maxComments, show_browser: showBrowser };
  return http.post(path, body).then((res) => normalizeVideoCommentResponse(res.data, videoUrl));
}

export function crawlKeywordComments(
  keyword,
  limit = 3,
  showBrowser = false,
  days = 3,
  region = "",
  maxComments = 200,
  guestMode = false
) {
  const platform = getPlatformId();
  return http
    .post(`/platforms/${platform}/comments/keyword`, {
      keyword,
      limit,
      max_comments: maxComments,
      show_browser: showBrowser,
      days,
      region: region || null,
      guest_mode: guestMode,
    })
    .then((res) => normalizeKeywordCommentResponse(res.data));
}

export function commentFileDownloadUrl(fileName) {
  return `${http.defaults.baseURL}/comments/download?file_name=${encodeURIComponent(fileName)}`;
}

export function fetchHotVideos(snapshotDate, limit = 100) {
  return http
    .get(platformPath("/hot/videos"), { params: { snapshot_date: snapshotDate, limit } })
    .then((res) => res.data);
}

export function fetchHotAuthors(snapshotDate, limit = 50) {
  return http
    .get(platformPath("/hot/authors"), { params: { snapshot_date: snapshotDate, limit } })
    .then((res) => res.data);
}

export function fetchVideoTrend(videoId, days = 30) {
  return http.get(platformPath(`/videos/${videoId}/trend`), { params: { days } }).then((res) => res.data);
}

export function generateDailyReport(reportDate, provider = "template") {
  return http
    .post(platformPath("/reports/daily"), null, { params: { report_date: reportDate, provider } })
    .then((res) => res.data);
}

export function fetchReports() {
  return http.get(platformPath("/reports")).then((res) => res.data);
}

export function reportPdfUrl(reportDate) {
  const platform = getPlatformId();
  return `${http.defaults.baseURL}/platforms/${platform}/reports/${reportDate}/pdf`;
}
