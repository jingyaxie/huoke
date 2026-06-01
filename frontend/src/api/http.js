import axios from "axios";

export function getApiBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";
}

/** 将 HTTP API base 转为 WebSocket base（支持相对路径 /api） */
export function getWsApiBaseUrl() {
  const base = getApiBaseUrl();
  if (base.startsWith("/")) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${base}`;
  }
  return base.replace(/^http/, "ws");
}

const baseURL = getApiBaseUrl();
export const TENANT_STORAGE_KEY = "douyin_tenant_id";
export const PLATFORM_STORAGE_KEY = "douyin_platform_id";
export const ACCOUNT_STORAGE_KEY = "huoke_account_id";
export const API_KEY_STORAGE_KEY = "douyin_api_key";
export const ACCESS_TOKEN_STORAGE_KEY = "huoke_access_token";

const http = axios.create({
  baseURL,
  timeout: 30000,
});

export function getTenantId() {
  return localStorage.getItem(TENANT_STORAGE_KEY) || "default";
}

export function setTenantId(tenantId) {
  localStorage.setItem(TENANT_STORAGE_KEY, (tenantId || "default").trim() || "default");
}

export function getPlatformId() {
  return localStorage.getItem(PLATFORM_STORAGE_KEY) || "douyin";
}

export function setPlatformId(platformId) {
  localStorage.setItem(PLATFORM_STORAGE_KEY, (platformId || "douyin").trim().toLowerCase() || "douyin");
}

export function getAccountId() {
  return localStorage.getItem(ACCOUNT_STORAGE_KEY) || "default";
}

export function setAccountId(accountId) {
  localStorage.setItem(ACCOUNT_STORAGE_KEY, (accountId || "default").trim() || "default");
}

export function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
}

export function setApiKey(apiKey) {
  localStorage.setItem(API_KEY_STORAGE_KEY, (apiKey || "").trim());
}

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) || "";
}

export function setAccessToken(token) {
  localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, (token || "").trim());
}

/** 将后端返回的 localhost:6080 VNC 地址转为同源 /vnc/ 代理，避免 WebSocket 连接失败 */
export function resolveVncUrl(backendUrl = "") {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const proxyUrl = `${origin}/vnc/vnc.html?autoconnect=true&resize=scale&path=websockify`;
  if (!backendUrl) return proxyUrl;
  try {
    const u = new URL(backendUrl, origin || "http://localhost");
    if (u.port === "6080" || u.pathname.includes("vnc.html")) {
      return proxyUrl;
    }
  } catch {
    return proxyUrl;
  }
  return backendUrl;
}

http.interceptors.request.use((config) => {
  config.headers["X-Tenant-Id"] = getTenantId();
  config.headers["X-Platform-Id"] = getPlatformId();
  config.headers["X-Account-Id"] = getAccountId();
  const apiKey = getApiKey();
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }
  const accessToken = getAccessToken();
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

export default http;
