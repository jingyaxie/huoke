import http from "./http";

const LONG_TIMEOUT = 120000;

function platformPrefix(platform) {
  return `/platforms/${platform}`;
}

export function followUser(platform, payload) {
  return http.post(`${platformPrefix(platform)}/users/follow`, payload, { timeout: LONG_TIMEOUT });
}

export function unfollowUser(platform, payload) {
  return http.post(`${platformPrefix(platform)}/users/unfollow`, payload, { timeout: LONG_TIMEOUT });
}

export function sendUserMessage(platform, payload) {
  return http.post(`${platformPrefix(platform)}/users/messages`, payload, { timeout: LONG_TIMEOUT });
}
