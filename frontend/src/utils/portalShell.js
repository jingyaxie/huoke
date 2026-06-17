/** 盈小蚁 iframe 嵌入 Huoke 壳层时的 postMessage 协议 */
export const PORTAL_AUTH_MESSAGE = "huoke:portal-authenticated";
export const PORTAL_PING_MESSAGE = "huoke:shell-ping";
export const PORTAL_PONG_MESSAGE = "huoke:shell-pong";
export const PORTAL_SHELL_STORAGE_KEY = "huoke_shell_app";

const PORTAL_ORIGIN_SUFFIXES = ["tanjiyunai.com"];

export function buildPortalEmbedUrl(baseUrl = "https://www.tanjiyunai.com/customer/platform-bindings") {
  try {
    const url = new URL(baseUrl);
    url.searchParams.set("huoke_embed", "1");
    return url.toString();
  } catch {
    const joiner = baseUrl.includes("?") ? "&" : "?";
    return `${baseUrl}${joiner}huoke_embed=1`;
  }
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

/** Tauri 桌面（withGlobalTauri 可能为 false）或本地 FastAPI 托管的前端 */
export function detectNativeShell() {
  if (typeof window === "undefined") return false;
  if (window.__TAURI__ || window.__TAURI_INTERNALS__) return true;
  const { hostname, port } = window.location;
  return (hostname === "127.0.0.1" || hostname === "localhost") && port === "8000";
}
