import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";
export const TENANT_STORAGE_KEY = "douyin_tenant_id";
export const PLATFORM_STORAGE_KEY = "douyin_platform_id";
export const API_KEY_STORAGE_KEY = "douyin_api_key";

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

export function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
}

export function setApiKey(apiKey) {
  localStorage.setItem(API_KEY_STORAGE_KEY, (apiKey || "").trim());
}

http.interceptors.request.use((config) => {
  config.headers["X-Tenant-Id"] = getTenantId();
  config.headers["X-Platform-Id"] = getPlatformId();
  const apiKey = getApiKey();
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }
  return config;
});

export default http;
