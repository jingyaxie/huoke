import http from "./http";

const LIST_TIMEOUT = 15000;

export function fetchContentList(platform, { offset = 0, limit = 50, updatedAfter, updatedBefore } = {}) {
  const params = { offset, limit };
  if (updatedAfter) params.updated_after = updatedAfter;
  if (updatedBefore) params.updated_before = updatedBefore;
  return http.get(`/platforms/${platform}/contents`, { params, timeout: LIST_TIMEOUT });
}

export function fetchContentDetail(platform, contentId, { maxComments } = {}) {
  const params = {};
  if (maxComments != null) params.max_comments = maxComments;
  return http.get(`/platforms/${platform}/contents/${encodeURIComponent(contentId)}`, {
    params,
    timeout: LIST_TIMEOUT,
  });
}
