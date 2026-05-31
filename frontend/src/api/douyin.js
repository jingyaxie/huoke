import http from "./http";

export function fetchOverview(days = 7) {
  return http.get("/overview", { params: { days } }).then((res) => res.data);
}

export function triggerCrawl(limit = 100) {
  return http.post("/crawl/hot", null, { params: { limit } }).then((res) => res.data);
}

export function triggerLogin(showBrowser = true) {
  return http.post("/douyin/login", { show_browser: showBrowser }).then((res) => res.data);
}

export function fetchLoginStatus() {
  return http.get("/douyin/login-status").then((res) => res.data);
}

export function fetchServerLoginUrl() {
  return http.get("/douyin/server-login-url").then((res) => res.data);
}

export function triggerServerLogin() {
  return http.post("/douyin/server-login").then((res) => res.data);
}

export function crawlVideoComments(videoUrl, showBrowser = false) {
  return http.post("/comments/video", { video_url: videoUrl, show_browser: showBrowser }).then((res) => res.data);
}

export function crawlKeywordComments(keyword, limit = 3, showBrowser = false, days = 3, region = "") {
  return http
    .post("/comments/keyword", {
      keyword,
      limit,
      show_browser: showBrowser,
      days,
      region: region || null,
    })
    .then((res) => res.data);
}

export function commentFileDownloadUrl(fileName) {
  return `${http.defaults.baseURL}/comments/download?file_name=${encodeURIComponent(fileName)}`;
}

export function fetchHotVideos(snapshotDate, limit = 100) {
  return http.get("/hot/videos", { params: { snapshot_date: snapshotDate, limit } }).then((res) => res.data);
}

export function fetchHotAuthors(snapshotDate, limit = 50) {
  return http.get("/hot/authors", { params: { snapshot_date: snapshotDate, limit } }).then((res) => res.data);
}

export function fetchVideoTrend(videoId, days = 30) {
  return http.get(`/videos/${videoId}/trend`, { params: { days } }).then((res) => res.data);
}

export function generateDailyReport(reportDate, provider = "template") {
  return http
    .post("/reports/daily", null, { params: { report_date: reportDate, provider } })
    .then((res) => res.data);
}

export function fetchReports() {
  return http.get("/reports").then((res) => res.data);
}

export function reportPdfUrl(reportDate) {
  return `${http.defaults.baseURL}/reports/${reportDate}/pdf`;
}
