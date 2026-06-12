import { ref } from "vue";
import { ElMessage } from "element-plus";
import { triggerAccountPlatformLogin } from "../api/accounts";

export function usePlatformVnc(getAccountId) {
  const vncDialogVisible = ref(false);
  const vncDialogUrl = ref("");
  const vncDialogTitle = ref("VNC 浏览器");
  const vncDialogPlatformLabel = ref("");
  const vncDialogTenantId = ref("");
  const vncLoginLoading = ref("");

  function resolveAccountId() {
    if (typeof getAccountId === "function") {
      return getAccountId();
    }
    return getAccountId?.value || getAccountId || "default";
  }

  function openVncView(row, tenantId = "") {
    vncDialogUrl.value = row?.vnc_url || "";
    vncDialogTitle.value = `${row?.platform_label || "平台"} · VNC 桌面`;
    vncDialogPlatformLabel.value = row?.platform_label || "";
    vncDialogTenantId.value = tenantId;
    vncDialogVisible.value = true;
  }

  async function openVncLogin(row, tenantId = "") {
    if (!row?.platform) return;
    vncLoginLoading.value = row.platform;
    try {
      const data = await triggerAccountPlatformLogin(resolveAccountId(), row.platform);
      vncDialogUrl.value = data.vnc_url || row.vnc_url || "";
      vncDialogTitle.value = `${row.platform_label || row.platform} · VNC 浏览器登录`;
      vncDialogPlatformLabel.value = row.platform_label || "";
      vncDialogTenantId.value = tenantId || data.tenant_id || "";
      vncDialogVisible.value = true;
      ElMessage.success(
        data.message || "已在 VNC 中打开浏览器，请查看是否仍显示登录框并完成扫码",
      );
    } catch (err) {
      ElMessage.error(err?.message || "启动 VNC 登录失败");
    } finally {
      vncLoginLoading.value = "";
    }
  }

  return {
    vncDialogVisible,
    vncDialogUrl,
    vncDialogTitle,
    vncDialogPlatformLabel,
    vncDialogTenantId,
    vncLoginLoading,
    openVncView,
    openVncLogin,
  };
}
