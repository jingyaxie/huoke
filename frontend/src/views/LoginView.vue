<template>
  <MainLayout>
    <section class="panel login-page">
      <div class="page-title">登录中心</div>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="账号登录" name="account">
          <el-form label-width="90px" class="login-form" @submit.prevent>
            <el-form-item label="用户名">
              <el-input v-model="username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="password" show-password type="password" placeholder="请输入密码" />
            </el-form-item>
            <el-form-item>
              <el-button :loading="accountLoading" type="primary" @click="onAccountLogin">登录</el-button>
              <el-button :loading="meLoading" @click="loadMe">查询当前登录</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="meText" :title="meText" type="success" :closable="false" />
        </el-tab-pane>

        <el-tab-pane label="抖音扫码登录" name="douyin">
          <div class="row">
            <el-button :loading="serverLoading" type="primary" @click="openServerLogin">打开扫码窗口</el-button>
            <el-button :loading="statusLoading" @click="refreshStatus">刷新登录状态</el-button>
          </div>
          <el-alert
            v-if="statusMessage"
            :title="statusMessage"
            :type="loginStatus === 'ready' ? 'success' : 'warning'"
            :closable="false"
          />
          <ServerLoginDialog
            v-model="dialogVisible"
            :url="serverLoginUrl"
            :tenant-id="tenantId"
            :account-id="accountId"
            platform-label="抖音"
          />
        </el-tab-pane>
      </el-tabs>
    </section>
  </MainLayout>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import MainLayout from "../components/MainLayout.vue";
import ServerLoginDialog from "../components/ServerLoginDialog.vue";
import { fetchAuthMe, loginUser } from "../api/auth";
import { fetchLoginStatus, fetchServerLoginUrl, triggerServerLogin } from "../api/douyin";
import { getAccountId, getTenantId } from "../api/http";

const activeTab = ref("account");
const username = ref("");
const password = ref("");
const meText = ref("");
const accountLoading = ref(false);
const meLoading = ref(false);

const serverLoading = ref(false);
const statusLoading = ref(false);
const dialogVisible = ref(false);
const serverLoginUrl = ref("");
const statusMessage = ref("");
const loginStatus = ref("unknown");
const tenantId = ref(getTenantId());
const accountId = ref(getAccountId());

async function onAccountLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning("请先输入用户名和密码");
    return;
  }
  accountLoading.value = true;
  try {
    const data = await loginUser(username.value, password.value);
    ElMessage.success(`登录成功：${data.user?.username || username.value}`);
    await loadMe();
  } catch (err) {
    ElMessage.error(err?.message || "登录失败");
  } finally {
    accountLoading.value = false;
  }
}

async function loadMe() {
  meLoading.value = true;
  try {
    const data = await fetchAuthMe();
    meText.value = `当前用户：${data.user?.username || "-"}，租户：${data.tenant?.tenant_id || "-"}`;
  } catch (err) {
    meText.value = "";
    ElMessage.error(err?.message || "查询失败");
  } finally {
    meLoading.value = false;
  }
}

async function openServerLogin() {
  serverLoading.value = true;
  try {
    tenantId.value = getTenantId();
    accountId.value = getAccountId();
    const data = await fetchServerLoginUrl();
    serverLoginUrl.value = data.url || "";
    dialogVisible.value = true;
    await triggerServerLogin();
    ElMessage.success("请在弹窗内完成扫码/验证");
    await refreshStatus();
  } catch (err) {
    ElMessage.error(err?.message || "打开扫码登录失败");
  } finally {
    serverLoading.value = false;
  }
}

async function refreshStatus() {
  statusLoading.value = true;
  try {
    const data = await fetchLoginStatus();
    loginStatus.value = data.status || "unknown";
    statusMessage.value = data.message || "状态未知";
  } catch (err) {
    statusMessage.value = "登录状态查询失败";
    loginStatus.value = "error";
    ElMessage.error(err?.message || "登录状态查询失败");
  } finally {
    statusLoading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  padding: 18px;
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 14px;
}

.login-form {
  max-width: 520px;
}

.row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
</style>
