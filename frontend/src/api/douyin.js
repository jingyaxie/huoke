import { getAccountId, getPlatformId, getTenantId, resolveVncUrl, setTenantId } from "./http";
import {
  fetchAccountPlatformLoginStatus,
  triggerAccountPlatformLogin,
} from "./accounts";

export { getTenantId, setTenantId };

export function fetchLoginStatus() {
  return fetchAccountPlatformLoginStatus(getAccountId(), getPlatformId());
}

export function fetchServerLoginUrl() {
  return Promise.resolve({ url: resolveVncUrl() });
}

export function triggerServerLogin() {
  return triggerAccountPlatformLogin(getAccountId(), getPlatformId());
}
