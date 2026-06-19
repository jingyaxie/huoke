/** 盈小蚁 iframe 嵌入 Huoke 壳层时的 postMessage 协议 */
import { getPortalBaseUrl } from "../config/cloudNav";

export const PORTAL_AUTH_MESSAGE = "huoke:portal-authenticated";
export const PORTAL_PING_MESSAGE = "huoke:shell-ping";
export const PORTAL_PONG_MESSAGE = "huoke:shell-pong";
export const PORTAL_NAVIGATE_MESSAGE = "huoke:navigate";
export const PORTAL_AUTH_STORAGE_KEY = "huoke_portal_auth";
export const PORTAL_SHELL_STORAGE_KEY = "huoke_shell_app";

const PORTAL_ORIGIN_SUFFIXES = ["tanjiyunai.com"];

export function isPortalEnabled() {
  const flag = import.meta.env.VITE_PORTAL_ENABLED;
  if (flag === "0" || flag === "false") return false;
  return true;
}

export function buildPortalEmbedUrl(baseUrl) {
  const resolved = baseUrl || `${getPortalBaseUrl()}/customer/dashboard`;
  try {
    const url = new URL(resolved);
    url.searchParams.set("huoke_embed", "1");
    return url.toString();
  } catch {
    const joiner = resolved.includes("?") ? "&" : "?";
    return `${resolved}${joiner}huoke_embed=1`;
  }
}

export function buildPortalLoginUrl() {
  return buildPortalEmbedUrl(`${getPortalBaseUrl()}/customer/login`);
}

export function isPortalMessageOrigin(origin) {
  if (!origin || typeof origin !== "string") return false;
  if (origin === "null") return false;
  try {
    const { hostname, protocol } = new URL(origin);
    if (protocol !== "https:" && protocol !== "http:") return false;
    return PORTAL_ORIGIN_SUFFIXES.some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`));
  } catch {
    return false;
  }
}

export function isPortalAuthMessage(data) {
  if (!data || typeof data !== "object") return false;
  if (data.type === PORTAL_AUTH_MESSAGE || data.type === "yingxiaoyi:login-success") {
    return data.authenticated !== false;
  }
  return data.type === PORTAL_PONG_MESSAGE && data.authenticated === true;
}

export function readPortalAuth() {
  try {
    const raw = sessionStorage.getItem(PORTAL_AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.authenticated !== true) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function isPortalAuthenticated() {
  return Boolean(readPortalAuth()?.authenticated);
}

export function setPortalAuthenticated(payload = {}) {
  const next = {
    authenticated: true,
    displayName: payload.displayName || "",
    path: payload.path || "",
    at: Date.now(),
  };
  sessionStorage.setItem(PORTAL_AUTH_STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent("huoke-portal-auth-changed", { detail: next }));
  return next;
}

export function clearPortalAuth() {
  sessionStorage.removeItem(PORTAL_AUTH_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent("huoke-portal-auth-changed", { detail: null }));
}

export function getPortalDisplayName() {
  return readPortalAuth()?.displayName || "";
}

/** Tauri 桌面（withGlobalTauri 可能为 false）或本地 FastAPI 托管的前端 */
export function detectNativeShell() {
  if (typeof window === "undefined") return false;
  if (window.__TAURI__ || window.__TAURI_INTERNALS__) return true;
  const { hostname, port } = window.location;
  return (hostname === "127.0.0.1" || hostname === "localhost") && (port === "8000" || port === "18765");
}

/** 仅云端 H5 嵌入页需盈小蚁登录；本地获客/编排/设置不拦截 */
export function requiresPortalAuth(path) {
  const normalized = String(path || "").trim();
  return normalized === "/cloud" || normalized.startsWith("/cloud/");
}

export function handlePortalMessage(event) {
  if (!isPortalMessageOrigin(event.origin)) return null;
  const data = event.data;
  if (!data || typeof data !== "object") return null;

  if (isPortalAuthMessage(data)) {
    return setPortalAuthenticated({
      displayName: data.displayName || data.userName || "",
      path: data.path || "",
    });
  }

  if (data.type === PORTAL_NAVIGATE_MESSAGE && typeof data.path === "string" && data.path.startsWith("/")) {
    return { navigate: data.path };
  }

  return null;
}
