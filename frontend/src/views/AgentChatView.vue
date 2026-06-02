<template>
  <div class="agent-page">
      <aside class="history-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <router-link to="/videos" class="sidebar-brand" :title="`返回主应用 · 租户 ${tenantId}`">
          <span class="brand-mark">火</span>
          <span class="brand-text">抖音热点 · 智能体</span>
        </router-link>
        <div class="sidebar-head">
          <button type="button" class="new-chat-btn" :disabled="running" @click="newChat">
            <el-icon><Plus /></el-icon>
            <span>新对话</span>
          </button>
          <button
            type="button"
            class="sidebar-collapse-btn"
            :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <el-icon><DArrowLeft v-if="!sidebarCollapsed" /><DArrowRight v-else /></el-icon>
          </button>
        </div>

        <div v-if="!sidebarCollapsed" class="history-scroll">
          <div v-if="historyLoading" class="history-empty">加载中…</div>
          <div v-else-if="groupedChatHistory.length === 0" class="history-empty">暂无历史对话</div>
          <template v-else>
            <section v-for="group in groupedChatHistory" :key="group.label" class="history-group">
              <div class="history-group-label">{{ group.label }}</div>
              <button
                v-for="item in group.items"
                :key="item.run_id"
                type="button"
                class="history-item"
                :class="{ active: item.run_id === runId, running: running && item.run_id === runId }"
                :disabled="running && item.run_id !== runId"
                @click="selectChat(item.run_id)"
              >
                <span class="history-title">{{ item.title }}</span>
                <span
                  class="history-delete"
                  title="删除对话"
                  @click.stop="deleteChat(item.run_id)"
                >
                  <el-icon><Delete /></el-icon>
                </span>
              </button>
            </section>
          </template>
        </div>

        <div v-if="!sidebarCollapsed" class="sidebar-tenant">
          <div class="sidebar-account-label">租户 ID</div>
          <el-input
            v-model="tenantId"
            size="small"
            placeholder="default"
            :disabled="running"
            @change="onTenantChange"
          />
          <div class="sidebar-account-label sidebar-tenant-gap">API Key</div>
          <el-input
            v-model="apiKey"
            size="small"
            type="password"
            show-password
            placeholder="启用鉴权时填写"
            @change="onApiKeyChange"
          />
        </div>

        <div v-if="!sidebarCollapsed" class="sidebar-account">
          <div class="sidebar-account-label">当前账号</div>
          <el-select
            v-model="activeAccountId"
            size="small"
            class="sidebar-account-select"
            :disabled="running"
            @change="onActiveAccountChange"
          >
            <el-option v-for="item in accounts" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
        </div>

        <div v-if="!sidebarCollapsed" class="sidebar-foot">
          <button type="button" class="sidebar-link" @click="openAccountsDrawer">绑定</button>
          <button type="button" class="sidebar-link" @click="skillsDrawerVisible = true">技能</button>
          <button type="button" class="sidebar-link" @click="orchestrationDrawerVisible = true">编排</button>
          <button type="button" class="sidebar-link" @click="experiencesDrawerVisible = true">经验</button>
          <button type="button" class="sidebar-link" @click="rulesDrawerVisible = true">规则</button>
        </div>
      </aside>

      <div class="main-shell">
        <div class="workspace">
        <section class="chat-panel">
          <div class="chat-header">
            <div class="chat-header-left">
              <button
                type="button"
                class="mobile-sidebar-toggle"
                title="对话历史"
                @click="sidebarCollapsed = false"
              >
                <el-icon><ChatLineRound /></el-icon>
              </button>
              <h2 class="title">{{ currentChatTitle }}</h2>
              <div class="status-chips">
                <span class="chip chip-tenant" :title="`当前租户: ${tenantId}`">{{ tenantId }}</span>
                <span v-if="running" class="chip chip-live">运行中</span>
                <span v-if="steps.length" class="chip">{{ steps.length }} 步</span>
              </div>
            </div>
            <div class="chat-header-actions">
              <el-button
                v-if="running && runId"
                size="small"
                type="danger"
                plain
                @click="stopRun"
              >
                停止
              </el-button>
            </div>
          </div>

          <div v-if="runResumable && !running" class="resume-banner">
            <div class="resume-banner-text">
              <strong>任务已暂停</strong>
              <span>网络中断或连接断开后，可从上次进度继续执行</span>
            </div>
            <el-button type="primary" size="small" @click="resumeRun">继续执行</el-button>
          </div>

          <div ref="messagesRef" class="chat-scroll">
            <div v-if="displayMessages.length === 0 && !running" class="thread-welcome">
              <div class="welcome-logo">AI</div>
              <h3 class="welcome-title">有什么可以帮忙的？</h3>
              <p class="welcome-desc">描述任务，Agent 将自动操作浏览器完成</p>
              <div class="quick-prompts">
                <button
                  v-for="item in quickPrompts"
                  :key="item"
                  type="button"
                  class="prompt-chip"
                  @click="applyQuickPrompt(item)"
                >
                  {{ item }}
                </button>
              </div>
            </div>

            <div v-else class="thread">
              <AgentMessageBlock
                v-for="(msg, idx) in displayMessages"
                :key="messageKey(msg, idx)"
                :message="msg"
                :expanded="expandedChatTools.has(idx)"
                @toggle="toggleChatToolExpand(idx)"
              />
              <AgentStreamingBlock v-if="running" :html="streamingHtml" />
            </div>
          </div>

          <div class="composer-dock">
            <div class="composer-inner">
              <el-input
                v-model="inputText"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 6 }"
                placeholder="描述任务，Agent 将自动操作浏览器…"
                :disabled="running"
                resize="none"
                class="composer-textarea"
                @keydown.ctrl.enter="sendMessage"
              />
              <div class="composer-toolbar">
                <div class="toolbar-pills">
                  <el-popover placement="top-start" :width="280" trigger="click">
                    <template #reference>
                      <button type="button" class="pill-btn pill-icon" title="更多设置">
                        <el-icon><Setting /></el-icon>
                      </button>
                    </template>
                    <div class="settings-popover">
                      <div class="settings-row">
                        <span>浏览器可见</span>
                        <el-switch v-model="headless" size="small" inline-prompt active-text="无头" inactive-text="可见" />
                      </div>
                      <div class="settings-row">
                        <span>传输协议</span>
                        <el-switch v-model="useWebSocket" size="small" inline-prompt active-text="WS" inactive-text="SSE" />
                      </div>
                      <el-divider style="margin: 10px 0" />
                      <el-button size="small" text @click="rulesDrawerVisible = true">规则管理</el-button>
                      <el-button size="small" text @click="skillsDrawerVisible = true">技能管理</el-button>
                      <el-button
                        size="small"
                        text
                        :disabled="recordedSteps.length === 0"
                        @click="openRecordDialog"
                      >
                        录制技能 ({{ recordedSteps.length }})
                      </el-button>
                      <el-button
                        size="small"
                        text
                        :disabled="running"
                        @click="newChat"
                      >
                        新会话
                      </el-button>
                    </div>
                  </el-popover>

                  <el-select v-model="agentMode" size="small" class="pill-select pill-mode">
                    <el-option label="Agent" value="agent" />
                    <el-option label="Plan" value="plan" />
                    <el-option label="Ask" value="ask" />
                  </el-select>
                  <el-select v-model="runMode" size="small" class="pill-select pill-run">
                    <el-option label="自动" value="auto" />
                    <el-option label="审批" value="confirm" />
                  </el-select>
                  <el-select v-model="provider" size="small" class="pill-select pill-provider">
                    <el-option label="DeepSeek" value="deepseek" :disabled="!providerOptions.deepseek?.configured" />
                    <el-option label="OpenAI" value="openai" :disabled="!providerOptions.openai?.configured" />
                  </el-select>
                </div>

                <div class="toolbar-send">
                  <span v-if="finalStatus" class="composer-status" :class="finalStatus.status">
                    {{ truncateText(finalStatus.summary, 48) }}
                  </span>
                  <button
                    type="button"
                    class="send-btn"
                    :class="{ active: inputText.trim() && !running, loading: running }"
                    :disabled="!inputText.trim() || running"
                    @click="sendMessage"
                  >
                    <el-icon v-if="running" class="is-loading"><Loading /></el-icon>
                    <el-icon v-else><Top /></el-icon>
                  </button>
                </div>
              </div>
            </div>
            <p v-if="providerNote" class="composer-hint">{{ providerNote }}</p>
          </div>
        </section>

        <aside class="panel side-panel">
          <el-tabs v-model="sideTab" class="side-tabs" stretch>
            <el-tab-pane label="预览" name="preview">
              <div class="side-scroll">
                <div class="preview-frame">
                  <img v-if="screenshot" :src="screenshot" alt="页面截图" class="preview-img" />
                  <div v-else class="preview-empty">
                    <span>暂无截图</span>
                    <small>1440×900 桌面视口 · browser_screenshot 后显示</small>
                  </div>
                </div>
                <dl v-if="pageInfo.url || pageInfo.title" class="meta-list">
                  <template v-if="pageInfo.title">
                    <dt>标题</dt>
                    <dd>{{ pageInfo.title }}</dd>
                  </template>
                  <template v-if="pageInfo.url">
                    <dt>URL</dt>
                    <dd class="url-text">{{ pageInfo.url }}</dd>
                  </template>
                </dl>
                <div class="agent-meta-card">
                  <div class="agent-meta-title">智能体调度状态</div>
                  <div class="agent-meta-row">
                    <span>阶段</span>
                    <code>{{ formatPhase(agentPhase) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>预算</span>
                    <code>{{ formatBudget(agentMeta.budget_limits) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>消耗</span>
                    <code>{{ formatBudget(agentMeta.tool_usage) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>失败分类</span>
                    <code>{{ formatBudget(agentMeta.failure_streak) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>技能优先级</span>
                    <code>{{ formatSkillPriority(agentMeta.skill_priority) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>任务快照</span>
                    <code>{{ formatSnapshot(taskSnapshot) }}</code>
                  </div>
                </div>
                <div class="agent-meta-card">
                  <div class="agent-meta-title">任务复盘</div>
                  <div class="agent-meta-row">
                    <span>校验分</span>
                    <code>{{ validationReport.score ?? "-" }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>置信度</span>
                    <code>{{ validationReport.confidence || "-" }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>状态</span>
                    <code>{{ reviewReport.status || "-" }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>工具消耗</span>
                    <code>{{ reviewReport.total_tools ?? "-" }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>失败类型</span>
                    <code>{{ formatTopFailures(reviewReport.top_failures) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>建议</span>
                    <code>{{ reviewReport.advice || "-" }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>问题</span>
                    <code>{{ formatIssueList(validationReport.issues) }}</code>
                  </div>
                  <div class="agent-meta-row">
                    <span>校验建议</span>
                    <code>{{ formatIssueList(validationReport.suggestions) }}</code>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="`步骤 ${steps.length || ''}`" name="steps">
              <div class="side-scroll">
                <div v-if="steps.length === 0" class="side-empty">工具调用记录将显示在此</div>
                <div
                  v-for="(step, idx) in steps"
                  :key="idx"
                  class="step-item"
                  :class="[step.status, { open: expandedSteps.has(idx) }]"
                >
                  <div class="step-head" @click="toggleStepExpand(idx)">
                    <span class="step-dot" />
                    <span class="step-line">
                      <span class="step-num">#{{ step.step }}</span>
                      <code class="step-tool">{{ step.tool }}</code>
                      <span class="step-sep">·</span>
                      <span class="step-summary">{{ formatStepSummary(step) }}</span>
                      <el-tag v-if="step.subagent" size="small" type="info" class="step-tag">子</el-tag>
                      <el-tag v-if="step.isSkill" size="small" type="warning" class="step-tag">技</el-tag>
                    </span>
                    <el-icon class="step-chevron" :class="{ open: expandedSteps.has(idx) }">
                      <ArrowDown />
                    </el-icon>
                  </div>
                  <pre v-if="expandedSteps.has(idx) && step.detail" class="step-json">{{ step.detail }}</pre>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="`检查点 ${checkpoints.length || ''}`" name="checkpoints">
              <div class="side-scroll">
                <div class="cp-toolbar">
                  <span class="cp-hint">操作前自动保存，可回滚</span>
                  <el-button v-if="runId" size="small" text @click="loadCheckpoints">刷新</el-button>
                </div>
                <div v-if="checkpoints.length === 0" class="side-empty">暂无检查点</div>
                <div
                  v-for="cp in checkpoints"
                  :key="cp.checkpoint_id"
                  class="cp-item"
                  :class="{ open: expandedCheckpoints.has(cp.checkpoint_id) }"
                >
                  <div class="cp-head" @click="toggleCheckpointExpand(cp.checkpoint_id)">
                    <span class="cp-dot" />
                    <span class="cp-line">
                      <span class="cp-num">#{{ cp.step }}</span>
                      <code class="cp-tool">{{ cp.tool }}</code>
                      <template v-if="cp.title">
                        <span class="cp-sep">·</span>
                        <span class="cp-title-inline">{{ truncateText(cp.title, 36) }}</span>
                      </template>
                    </span>
                    <el-button
                      size="small"
                      type="primary"
                      link
                      class="cp-restore"
                      :disabled="running"
                      @click.stop="doRestoreCheckpoint(cp.checkpoint_id)"
                    >
                      恢复
                    </el-button>
                    <el-icon class="cp-chevron" :class="{ open: expandedCheckpoints.has(cp.checkpoint_id) }">
                      <ArrowDown />
                    </el-icon>
                  </div>
                  <div v-if="expandedCheckpoints.has(cp.checkpoint_id)" class="cp-detail">
                    <p v-if="cp.title">{{ cp.title }}</p>
                    <p v-if="cp.url" class="cp-url">{{ cp.url }}</p>
                  </div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </aside>
        </div>
      </div>

      <el-drawer v-model="skillsDrawerVisible" title="技能管理" size="640px" @open="onSkillsDrawerOpen">
        <el-collapse v-model="skillHubConfigOpen" style="margin-bottom: 12px">
          <el-collapse-item title="SkillHub 注册中心" name="hub">
            <el-form label-width="100px" size="small">
              <el-form-item label="Registry URL">
                <el-input v-model="skillHubConfig.registry" placeholder="https://skill.xfyun.cn" />
              </el-form-item>
              <el-form-item label="API Token">
                <el-input
                  v-model="skillHubTokenInput"
                  type="password"
                  show-password
                  :placeholder="skillHubConfig.token_configured ? '已配置（留空不修改）' : 'sk_...'"
                />
              </el-form-item>
              <el-form-item label="对话自动安装">
                <el-switch v-model="skillHubConfig.auto_install_enabled" />
              </el-form-item>
              <el-button size="small" type="primary" :loading="skillHubConfigSaving" @click="saveSkillHubConfig">
                保存配置
              </el-button>
            </el-form>
            <div class="skills-toolbar" style="margin-top: 8px">
              <el-input
                v-model="skillHubSearchQuery"
                size="small"
                placeholder="搜索 SkillHub 技能..."
                style="width: 200px"
                @keyup.enter="doSkillHubSearch"
              />
              <el-button size="small" :loading="skillHubSearching" @click="doSkillHubSearch">搜索</el-button>
              <input ref="skillHubZipInput" type="file" accept=".zip,application/zip" hidden @change="onSkillHubZipSelected" />
              <el-button size="small" @click="skillHubZipInput?.click()">上传 zip 安装</el-button>
            </div>
            <el-table
              v-if="skillHubSearchResults.length"
              :data="skillHubSearchResults"
              size="small"
              stripe
              style="width: 100%; margin-top: 8px"
            >
              <el-table-column prop="slug" label="技能" width="140" />
              <el-table-column prop="namespace" label="空间" width="80" />
              <el-table-column prop="summary" label="描述" min-width="160" show-overflow-tooltip />
              <el-table-column label="操作" width="88">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :loading="skillHubInstalling === row.slug"
                    @click="installFromHub(row)"
                  >
                    安装
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
        <div class="skills-toolbar">
          <el-button type="primary" size="small" @click="openSkillForm()">新建技能</el-button>
          <el-button size="small" @click="openImportDialog">导入</el-button>
          <el-button size="small" @click="exportAllSkills">导出 JSON</el-button>
          <el-button size="small" @click="loadSkills">刷新</el-button>
        </div>
        <el-table :data="skills" stripe size="small" style="width: 100%">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column prop="type" label="类型" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="skillTypeTag(row.type)">{{ skillTypeLabel(row.type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="scope" label="范围" width="70">
            <template #default="{ row }">
              <span v-if="row.source === 'skillhub'">SkillHub</span>
              <span v-else>{{ row.scope === "global" ? "全局" : "租户" }}</span>
            </template>
          </el-table-column>
          <el-table-column label="包" width="52">
            <template #default="{ row }">
              <el-tag v-if="row.package_path" size="small" type="info">包</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="enabled" label="启用" width="70">
            <template #default="{ row }">
              <el-switch
                v-model="row.enabled"
                size="small"
                :disabled="row.scope === 'global'"
                @change="toggleSkill(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="评分" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="skillScoreTag(row.effect?.average_score)">
                {{ formatSkillScore(row.effect?.average_score) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="成功率" width="90">
            <template #default="{ row }">
              {{ row.effect?.success_rate != null ? `${row.effect.success_rate}%` : "-" }}
            </template>
          </el-table-column>
          <el-table-column label="拦截风险" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="riskTagType(row.effect?.risk_level)">
                {{ riskLabel(row.effect?.risk_level, row.effect?.blocked_rate) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="250" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="invokeSkill(row)">调用</el-button>
              <el-button link type="primary" size="small" @click="openSkillEffect(row)">效果</el-button>
              <el-button link type="primary" size="small" @click="exportSkillMd(row)">MD</el-button>
              <el-button
                v-if="row.scope === 'tenant'"
                link
                type="primary"
                size="small"
                @click="openSkillForm(row)"
              >编辑</el-button>
              <el-button
                v-if="row.scope === 'tenant'"
                link
                type="danger"
                size="small"
                @click="removeSkill(row)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="skills-hint">
          SkillHub：<code>skillhub:install pdf-parser</code> 或说「安装 xxx 技能」可自动安装；对话中可用
          <code>skillhub_search</code> / <code>skillhub_install</code>。
          抖音：<code>/douyin-reply-comment</code> 等（需已登录）
        </p>
      </el-drawer>

      <el-drawer
        v-model="skillEffectVisible"
        :title="`技能效果：${selectedSkillEffect?.skill_id || ''}`"
        size="680px"
      >
        <div v-if="selectedSkillEffect" class="skills-toolbar">
          <el-tag size="small">均分 {{ selectedSkillEffect.stats.average_score ?? "-" }}</el-tag>
          <el-tag size="small" type="success">成功 {{ selectedSkillEffect.stats.success ?? 0 }}</el-tag>
          <el-tag size="small" type="danger">失败 {{ selectedSkillEffect.stats.failed ?? 0 }}</el-tag>
          <el-tag size="small" type="info">成功率 {{ selectedSkillEffect.stats.success_rate ?? 0 }}%</el-tag>
          <el-tag size="small" :type="riskTagType(selectedSkillEffect.stats.risk_level)">
            拦截率 {{ selectedSkillEffect.stats.blocked_rate ?? 0 }}%
          </el-tag>
        </div>
        <el-table :data="selectedSkillEffect?.records || []" stripe size="small" style="width: 100%">
          <el-table-column prop="timestamp" label="时间" width="168" />
          <el-table-column prop="status" label="结果" width="88" />
          <el-table-column prop="score" label="评分" width="72" />
          <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
          <el-table-column prop="summary" label="摘要" min-width="180" show-overflow-tooltip />
        </el-table>
      </el-drawer>

      <el-drawer v-model="accountsDrawerVisible" title="平台账号绑定" size="640px" @open="loadAccountBindings">
        <p class="skills-hint">
          当前租户：<strong>{{ tenantId }}</strong> · 账号 <strong>{{ activeAccountId }}</strong>。每个租户、每个账号可独立绑定抖音、小红书、快手。
        </p>
        <div class="skills-toolbar">
          <el-input v-model="newAccountId" size="small" placeholder="账号 ID，如 user-alice" style="width: 160px" />
          <el-input v-model="newAccountLabel" size="small" placeholder="显示名称" style="width: 140px" />
          <el-button type="primary" size="small" :loading="accountCreating" @click="createNewAccount">新建</el-button>
          <el-button size="small" @click="loadAccounts">刷新</el-button>
        </div>
        <el-table :data="accountBindings" stripe size="small" style="width: 100%">
          <el-table-column prop="platform_label" label="平台" width="88" />
          <el-table-column prop="status" label="状态" width="88">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'ready' ? 'success' : row.status === 'missing' ? 'info' : 'warning'"
              >
                {{ { ready: '已绑定', missing: '未绑定', incomplete: '不完整', error: '错误' }[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" size="small" :loading="bindingLoginPlatform === row.platform" @click="bindPlatformLogin(row)">
                扫码登录
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-drawer>

      <ServerLoginDialog
        v-model="loginDialogVisible"
        :url="serverLoginUrl"
        :tenant-id="tenantId"
        :account-id="activeAccountId"
        :platform-label="bindingLoginPlatformLabel"
      />

      <el-drawer v-model="experiencesDrawerVisible" title="经验库（做梦）" size="620px" @open="loadExperiences">
        <p class="skills-hint">
          任务完成后自动从成功/失败记录中提炼经验，并在相似新任务时注入系统提示。
        </p>
        <div class="skills-toolbar">
          <el-button type="primary" size="small" :loading="dreamConsolidating" @click="runDreamConsolidate">
            整理历史对话
          </el-button>
          <el-button size="small" :disabled="!runId" :loading="dreamRunLoading" @click="dreamCurrentRun">
            提炼当前对话
          </el-button>
          <el-button size="small" @click="loadExperiences">刷新</el-button>
        </div>
        <el-table
          :data="experiences"
          stripe
          size="small"
          style="width: 100%"
          highlight-current-row
          @current-change="(row) => (selectedExperience = row)"
        >
          <el-table-column prop="title" label="任务" min-width="160" show-overflow-tooltip />
          <el-table-column prop="outcome" label="结果" width="72">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.outcome === 'success' ? 'success' : row.outcome === 'failure' ? 'danger' : 'warning'"
              >
                {{ { success: '成功', failure: '失败', partial: '部分' }[row.outcome] || row.outcome }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="enabled" label="启用" width="70">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" size="small" @change="toggleExperience(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="removeExperience(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="selectedExperience" class="experience-detail">
          <h4>{{ selectedExperience.title }}</h4>
          <p>{{ selectedExperience.lesson }}</p>
          <div v-if="selectedExperience.do_tips?.length">
            <strong>建议做法</strong>
            <ul>
              <li v-for="(tip, i) in selectedExperience.do_tips" :key="'do-' + i">{{ tip }}</li>
            </ul>
          </div>
          <div v-if="selectedExperience.avoid_tips?.length">
            <strong>应避免</strong>
            <ul>
              <li v-for="(tip, i) in selectedExperience.avoid_tips" :key="'av-' + i">{{ tip }}</li>
            </ul>
          </div>
        </div>
      </el-drawer>

      <el-dialog v-model="importDialogVisible" title="导入技能" width="640px" destroy-on-close>
        <el-tabs v-model="importTab">
          <el-tab-pane label="SKILL.md" name="markdown">
            <el-input
              v-model="importMarkdown"
              type="textarea"
              :rows="12"
              placeholder="粘贴 SKILL.md 内容，或选择文件..."
            />
            <div class="import-actions">
              <input ref="mdFileInput" type="file" accept=".md,text/markdown" hidden @change="onMdFileSelected" />
              <el-button size="small" @click="mdFileInput?.click()">选择文件</el-button>
              <el-button size="small" @click="previewMarkdown">预览解析</el-button>
            </div>
            <pre v-if="importPreview" class="import-preview">{{ importPreview }}</pre>
          </el-tab-pane>
          <el-tab-pane label="JSON 包" name="json">
            <input ref="jsonFileInput" type="file" accept=".json,application/json" hidden @change="onJsonFileSelected" />
            <el-button size="small" @click="jsonFileInput?.click()">选择 JSON 文件</el-button>
            <p v-if="importJsonCount" class="import-meta">已加载 {{ importJsonCount }} 个技能</p>
          </el-tab-pane>
        </el-tabs>
        <el-checkbox v-model="importOverwrite" style="margin-top: 12px">覆盖已存在的同名技能</el-checkbox>
        <template #footer>
          <el-button @click="importDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="importLoading" @click="confirmImport">导入</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="recordDialogVisible" title="从对话录制 actions 技能" width="560px">
        <el-alert
          type="info"
          :closable="false"
          :title="`已捕获 ${recordedSteps.length} 个 browser 操作步骤`"
          style="margin-bottom: 12px"
        />
        <el-form label-width="88px">
          <el-form-item label="技能 ID" required>
            <el-input v-model="recordForm.id" placeholder="如 recorded-hot-list" />
          </el-form-item>
          <el-form-item label="名称" required>
            <el-input v-model="recordForm.name" placeholder="显示名称" />
          </el-form-item>
          <el-form-item label="描述" required>
            <el-input v-model="recordForm.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <el-collapse>
          <el-collapse-item title="查看录制的步骤" name="steps">
            <pre class="record-preview">{{ JSON.stringify(recordedSteps, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
        <template #footer>
          <el-button @click="recordDialogVisible = false">取消</el-button>
          <el-button @click="clearRecordedSteps">清空录制</el-button>
          <el-button type="primary" :loading="recordSaving" @click="saveRecordedSkill">保存技能</el-button>
        </template>
      </el-dialog>

      <el-dialog
        v-model="skillFormVisible"
        :title="editingSkill ? '编辑技能' : '新建技能'"
        width="640px"
        destroy-on-close
      >
        <el-form label-width="100px">
          <el-form-item label="录入方式">
            <el-radio-group v-model="skillFormMode">
              <el-radio-button value="form">表单</el-radio-button>
              <el-radio-button value="markdown">SKILL.md</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <template v-if="skillFormMode === 'markdown'">
            <el-input
              v-model="skillForm.markdown"
              type="textarea"
              :rows="16"
              placeholder="粘贴 SKILL.md，点击解析预览后保存"
            />
            <div class="import-actions">
              <el-button size="small" @click="parseSkillFormMarkdown">解析预览</el-button>
            </div>
            <pre v-if="skillForm.markdownPreview" class="import-preview">{{ skillForm.markdownPreview }}</pre>
          </template>
          <template v-else>
          <el-form-item label="技能 ID" required>
            <el-input v-model="skillForm.id" :disabled="!!editingSkill" placeholder="如 my-search-flow" />
          </el-form-item>
          <el-form-item label="名称" required>
            <el-input v-model="skillForm.name" placeholder="显示名称" />
          </el-form-item>
          <el-form-item label="描述" required>
            <el-input v-model="skillForm.description" type="textarea" :rows="2" placeholder="LLM 据此判断何时调用" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="skillForm.type" style="width: 100%">
              <el-option label="指令型 (instruction)" value="instruction" />
              <el-option label="动作流 (actions)" value="actions" />
              <el-option label="内置能力 (builtin)" value="builtin" />
            </el-select>
          </el-form-item>
          <el-form-item label="仅手动触发">
            <el-switch v-model="skillForm.disable_model_invocation" />
            <span class="field-hint">开启后模型不会自动调用，需 /skill-id 或 invoke_skill</span>
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'builtin'" label="内置处理器">
            <el-select v-model="skillForm.builtin_handler" style="width: 100%">
              <el-option
                v-for="h in builtinHandlers"
                :key="h.id"
                :label="`${h.id} — ${h.description}`"
                :value="h.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'instruction'" label="指令内容">
            <el-input
              v-model="skillForm.content"
              type="textarea"
              :rows="8"
              placeholder="支持 {{param}} 占位符，激活后注入给智能体执行"
            />
          </el-form-item>
          <el-form-item v-if="skillForm.type === 'actions'" label="动作 JSON">
            <el-input
              v-model="skillForm.actionsJson"
              type="textarea"
              :rows="10"
              placeholder='[{"tool":"browser_goto","args":{"url":"https://..."}}]'
            />
          </el-form-item>
          <el-form-item label="参数 JSON">
            <el-input
              v-model="skillForm.parametersJson"
              type="textarea"
              :rows="4"
              placeholder='[{"name":"keyword","type":"string","description":"关键词","required":true}]'
            />
          </el-form-item>
          </template>
        </el-form>
        <template #footer>
          <el-button @click="skillFormVisible = false">取消</el-button>
          <el-button type="primary" :loading="skillSaving" @click="saveSkill">
            {{ skillFormMode === 'markdown' ? '解析并保存' : '保存' }}
          </el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="approvalDialogVisible" title="工具操作审批" width="520px" :close-on-click-modal="false">
        <p v-if="pendingApproval">即将执行：<strong>{{ pendingApproval.tool }}</strong></p>
        <pre v-if="pendingApproval" class="record-preview">{{ JSON.stringify(pendingApproval.arguments, null, 2) }}</pre>
        <template #footer>
          <el-button @click="respondApproval(false)">拒绝</el-button>
          <el-button type="primary" :loading="running" @click="respondApproval(true)">批准执行</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="planDialogVisible" title="执行计划确认" width="560px" :close-on-click-modal="false">
        <p v-if="pendingPlan"><strong>{{ pendingPlan.summary }}</strong></p>
        <el-timeline v-if="pendingPlan">
          <el-timeline-item v-for="(s, i) in pendingPlan.steps" :key="i" :timestamp="`步骤 ${s.step || i + 1}`">
            {{ s.action }} — {{ s.detail }}
          </el-timeline-item>
        </el-timeline>
        <template #footer>
          <el-button @click="respondPlan(false)">拒绝</el-button>
          <el-button type="primary" :loading="running" @click="respondPlan(true)">批准并执行</el-button>
        </template>
      </el-dialog>

      <el-drawer v-model="orchestrationDrawerVisible" title="任务编排与评测" size="760px" @open="loadAgentJobs">
        <div class="skills-toolbar">
          <el-button type="primary" size="small" :loading="jobSubmitting" @click="submitOrchestrationJob">提交异步任务</el-button>
          <el-button size="small" @click="loadAgentJobs">刷新队列</el-button>
        </div>
        <el-form label-width="92px" class="orchestration-form">
          <el-form-item label="任务内容">
            <el-input v-model="jobForm.message" type="textarea" :rows="3" placeholder="输入要后台执行的任务" />
          </el-form-item>
          <el-form-item label="Provider">
            <el-select v-model="jobForm.provider" style="width: 140px">
              <el-option label="DeepSeek" value="deepseek" />
              <el-option label="OpenAI" value="openai" />
            </el-select>
            <el-select v-model="jobForm.mode" style="width: 110px; margin-left: 8px">
              <el-option label="Agent" value="agent" />
              <el-option label="Plan" value="plan" />
              <el-option label="Ask" value="ask" />
            </el-select>
            <el-select v-model="jobForm.run_mode" style="width: 110px; margin-left: 8px">
              <el-option label="自动" value="auto" />
              <el-option label="审批" value="confirm" />
            </el-select>
          </el-form-item>
          <el-form-item label="调度参数">
            <el-input-number v-model="jobForm.priority" :min="1" :max="10" size="small" />
            <span class="field-hint">优先级</span>
            <el-input-number v-model="jobForm.max_retries" :min="0" :max="5" size="small" style="margin-left: 10px" />
            <span class="field-hint">重试次数</span>
            <el-input-number v-model="jobForm.timeout_seconds" :min="10" :max="3600" size="small" style="margin-left: 10px" />
            <span class="field-hint">超时(秒)</span>
          </el-form-item>
        </el-form>
        <el-table :data="agentJobs" stripe size="small" style="width: 100%; margin-top: 8px">
          <el-table-column prop="job_id" label="Job ID" min-width="180" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="92" />
          <el-table-column prop="stage" label="阶段" width="92" />
          <el-table-column prop="retry_count" label="重试" width="70" />
          <el-table-column prop="run_id" label="Run ID" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="refreshOneJob(row.job_id)">刷新</el-button>
              <el-button
                v-if="row.status === 'queued' || row.status === 'running'"
                link
                type="danger"
                size="small"
                @click="cancelOneJob(row.job_id)"
              >取消</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-divider />
        <div class="skills-toolbar">
          <el-button type="primary" size="small" :loading="benchmarkRunning" @click="runBenchmarkNow">运行基准评测</el-button>
        </div>
        <el-input
          v-model="benchmarkCasesText"
          type="textarea"
          :rows="6"
          placeholder='[{"name":"case-1","message":"搜索淋浴房近3天热门并总结"}]'
        />
        <pre v-if="benchmarkResult" class="import-preview">{{ JSON.stringify(benchmarkResult, null, 2) }}</pre>
      </el-drawer>

      <el-drawer v-model="rulesDrawerVisible" title="Rules 规则管理" size="520px" @open="loadRules">
        <div class="skills-toolbar">
          <el-button type="primary" size="small" @click="openRuleForm()">新建规则</el-button>
          <el-button size="small" @click="loadRules">刷新</el-button>
        </div>
        <el-table :data="rules" stripe size="small">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column prop="scope" label="范围" width="70">
            <template #default="{ row }">{{ row.scope === "global" ? "全局" : "租户" }}</template>
          </el-table-column>
          <el-table-column prop="always_apply" label="始终" width="60">
            <template #default="{ row }">{{ row.always_apply ? "是" : "否" }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button v-if="row.scope === 'tenant'" link type="primary" size="small" @click="openRuleForm(row)">编辑</el-button>
              <el-button v-if="row.scope === 'tenant'" link type="danger" size="small" @click="removeRule(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-drawer>

      <el-dialog v-model="ruleFormVisible" :title="editingRule ? '编辑规则' : '新建规则'" width="560px">
        <el-form label-width="100px">
          <el-form-item label="规则 ID" required>
            <el-input v-model="ruleForm.id" :disabled="!!editingRule" />
          </el-form-item>
          <el-form-item label="名称" required>
            <el-input v-model="ruleForm.name" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="ruleForm.description" />
          </el-form-item>
          <el-form-item label="始终应用">
            <el-switch v-model="ruleForm.always_apply" />
          </el-form-item>
          <el-form-item label="平台">
            <el-input v-model="ruleForm.platformsText" placeholder="留空=全部，逗号分隔如 douyin,xiaohongshu,kuaishou" />
          </el-form-item>
          <el-form-item label="规则内容" required>
            <el-input v-model="ruleForm.content" type="textarea" :rows="8" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="ruleFormVisible = false">取消</el-button>
          <el-button type="primary" :loading="ruleSaving" @click="saveRule">保存</el-button>
        </template>
      </el-dialog>
    </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowDown, ChatLineRound, DArrowLeft, DArrowRight, Delete, Loading, Plus, Setting, Top } from "@element-plus/icons-vue";
import AgentMessageBlock from "../components/AgentMessageBlock.vue";
import AgentStreamingBlock from "../components/AgentStreamingBlock.vue";
import ServerLoginDialog from "../components/ServerLoginDialog.vue";
import { getAccountId, getApiKey, getTenantId, setAccountId, setApiKey, setTenantId } from "../api/http";
import {
  createAccount,
  fetchAccountBindings,
  fetchAccounts,
  setActiveAccount,
  triggerAccountPlatformLogin,
} from "../api/accounts";
import { renderChatMarkdown } from "../utils/chatMarkdown";
import {
  cancelAgentJobTask,
  cancelAgentRun,
  consolidateDreams,
  createAgentWebSocket,
  createRule,
  createSkill,
  deleteAgentRun,
  deleteExperience,
  deleteRule,
  deleteSkill,
  downloadWithAuth,
  dreamFromRun,
  exportSkillsJson,
  fetchAgentConfig,
  fetchAgentJob,
  fetchAgentJobs,
  fetchAgentRun,
  fetchAgentRuns,
  fetchExperiences,
  fetchBuiltinHandlers,
  fetchCheckpoints,
  fetchRules,
  fetchSkillEffectDetail,
  fetchSkillEffects,
  fetchSkills,
  fetchSkillHubConfig,
  updateSkillHubConfig,
  searchSkillHub,
  installSkillHub,
  installSkillHubZip,
  fetchSkillHubInstalled,
  uninstallSkillHub,
  submitAgentJob,
  importSkillMarkdown,
  importSkillsJson,
  parseSkillMarkdown,
  recordSkillFromSteps,
  restoreCheckpoint,
  resumeApproval,
  resumePlan,
  resumeAgentRun,
  runAgentBenchmark,
  sendAgentWsMessage,
  skillMarkdownDownloadUrl,
  streamAgentChat,
  toggleExperienceEnabled,
  updateRule,
  updateSkill,
} from "../api/agent";

const RUN_STORAGE_KEY = "huoke_agent_run_id";
const SESSION_STORAGE_KEY = "huoke_agent_session_id";

function emptyRuleForm() {
  return {
    id: "",
    name: "",
    description: "",
    content: "",
    always_apply: true,
    platformsText: "",
  };
}

function emptySkillForm() {
  return {
    id: "",
    name: "",
    description: "",
    type: "instruction",
    content: "",
    actionsJson: "[]",
    parametersJson: "[]",
    builtin_handler: null,
    disable_model_invocation: false,
    markdown: "",
    markdownPreview: "",
  };
}

const RECORDABLE_TOOLS = new Set([
  "browser_goto",
  "browser_click",
  "browser_fill",
  "browser_press",
  "browser_scroll",
  "browser_wait",
  "browser_get_text",
  "browser_get_page_info",
  "browser_get_network_data",
  "browser_screenshot",
]);

const provider = ref("deepseek");
const providerOptions = ref({});
const providerNote = ref("");
const PROVIDER_STORAGE_KEY = "huoke_agent_provider";
const agentMode = ref("agent");
const runMode = ref("auto");
const headless = ref(true);
const useWebSocket = ref(false);
const inputText = ref("");
const running = ref(false);
const sessionId = ref(localStorage.getItem(SESSION_STORAGE_KEY) || null);
const runId = ref(localStorage.getItem(RUN_STORAGE_KEY) || null);
const visionEnabled = ref(false);
const streamEnabled = ref(false);
const messages = ref([]);
const steps = ref([]);
const streamingText = ref("");
const screenshot = ref(null);
const pageInfo = ref({ url: "", title: "" });
const agentPhase = ref("plan");
const taskSnapshot = ref({});
const reviewReport = ref({});
const validationReport = ref({});
const agentMeta = ref({
  budget_limits: {},
  tool_usage: {},
  failure_streak: {},
  skill_priority: [],
});
const finalStatus = ref(null);
const messagesRef = ref(null);
const skillsDrawerVisible = ref(false);
const skillHubConfigOpen = ref(["hub"]);
const skillHubConfig = ref({
  registry: "https://skill.xfyun.cn",
  token_configured: false,
  auto_install_enabled: true,
});
const skillHubTokenInput = ref("");
const skillHubConfigSaving = ref(false);
const skillHubSearchQuery = ref("");
const skillHubSearchResults = ref([]);
const skillHubSearching = ref(false);
const skillHubInstalling = ref(null);
const skillHubZipInput = ref(null);
const skills = ref([]);
const skillEffectVisible = ref(false);
const selectedSkillEffect = ref(null);
const skillFormVisible = ref(false);
const skillSaving = ref(false);
const editingSkill = ref(null);
const builtinHandlers = ref([]);
const skillFormMode = ref("form");
const skillForm = ref(emptySkillForm());
const recordedSteps = ref([]);
const pendingToolArgs = ref({});
const recordDialogVisible = ref(false);
const recordSaving = ref(false);
const recordForm = ref({ id: "", name: "", description: "" });
const importDialogVisible = ref(false);
const importTab = ref("markdown");
const importMarkdown = ref("");
const importPreview = ref("");
const importJsonSkills = ref([]);
const importJsonCount = ref(0);
const importOverwrite = ref(false);
const importLoading = ref(false);
const mdFileInput = ref(null);
const jsonFileInput = ref(null);
const approvalDialogVisible = ref(false);
const planDialogVisible = ref(false);
const pendingApproval = ref(null);
const pendingPlan = ref(null);
const rulesDrawerVisible = ref(false);
const experiencesDrawerVisible = ref(false);
const orchestrationDrawerVisible = ref(false);
const accountsDrawerVisible = ref(false);
const accounts = ref([]);
const tenantId = ref(getTenantId());
const apiKey = ref(getApiKey());
const activeAccountId = ref(getAccountId());
const accountBindings = ref([]);
const newAccountId = ref("");
const newAccountLabel = ref("");
const accountCreating = ref(false);
const bindingLoginPlatform = ref("");
const bindingLoginPlatformLabel = ref("");
const loginDialogVisible = ref(false);
const serverLoginUrl = ref("");
const experiences = ref([]);
const selectedExperience = ref(null);
const dreamConsolidating = ref(false);
const dreamRunLoading = ref(false);
const dreamAutoLoading = ref(false);
const rules = ref([]);
const agentJobs = ref([]);
const jobSubmitting = ref(false);
const benchmarkRunning = ref(false);
const benchmarkResult = ref(null);
const benchmarkCasesText = ref('[{"name":"douyin-comments","message":"关键词淋浴房，抓取前3个视频评论并汇总"}]');
const jobForm = ref({
  message: "",
  provider: "deepseek",
  mode: "agent",
  run_mode: "auto",
  timeout_seconds: 600,
  max_retries: 1,
  priority: 5,
});
const ruleFormVisible = ref(false);
const ruleSaving = ref(false);
const editingRule = ref(null);
const ruleForm = ref(emptyRuleForm());
const checkpoints = ref([]);
const sideTab = ref("preview");
const expandedSteps = ref(new Set());
const expandedCheckpoints = ref(new Set());
const expandedChatTools = ref(new Set());
const runResumable = ref(false);
const runStatus = ref(null);
const chatHistory = ref([]);
const historyLoading = ref(false);
const sidebarCollapsed = ref(false);
const quickPrompts = [
  "/search-videos 搜索关键词「淋浴房」并列出视频",
  "/crawl-video-comments 抓取这个视频评论",
  "/crawl-keyword-comments 关键词批量抓取评论",
];

const displayMessages = computed(() =>
  messages.value
    .filter((m) => !shouldHideMessage(m))
    .map((m) => enrichMessage(m)),
);

const currentChatTitle = computed(() => {
  if (runId.value) {
    const found = chatHistory.value.find((item) => item.run_id === runId.value);
    if (found?.title) return found.title;
  }
  const firstUser = messages.value.find((m) => m.role === "user" && m.content?.trim());
  if (firstUser?.content) return truncateText(firstUser.content.trim(), 32);
  return "新对话";
});

const groupedChatHistory = computed(() => {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfWeek = new Date(startOfToday);
  startOfWeek.setDate(startOfWeek.getDate() - 7);

  const buckets = {
    今天: [],
    昨天: [],
    "过去 7 天": [],
    更早: [],
  };

  for (const item of chatHistory.value) {
    const raw = item.updated_at || item.created_at;
    const date = raw ? new Date(raw) : startOfToday;
    if (date >= startOfToday) buckets["今天"].push(item);
    else if (date >= startOfYesterday) buckets["昨天"].push(item);
    else if (date >= startOfWeek) buckets["过去 7 天"].push(item);
    else buckets["更早"].push(item);
  }

  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
});

const streamingHtml = computed(() => {
  if (!streamingText.value) return "";
  return `${renderChatMarkdown(streamingText.value)}<span class="stream-cursor">▍</span>`;
});
let abortController = null;
let agentWs = null;
let wsChatResolver = null;
let wsChatRejector = null;
let wsChatWatchdog = null;
const WS_IDLE_TIMEOUT_MS = 45000;

function clearWsWatchdog() {
  if (wsChatWatchdog) {
    clearTimeout(wsChatWatchdog);
    wsChatWatchdog = null;
  }
}

function touchWsWatchdog() {
  if (!wsChatResolver || !wsChatRejector) return;
  clearWsWatchdog();
  wsChatWatchdog = setTimeout(() => {
    const reject = wsChatRejector;
    wsChatResolver = null;
    wsChatRejector = null;
    reject?.(new Error("WebSocket 长时间无响应，任务已暂停，可点击「继续执行」恢复"));
  }, WS_IDLE_TIMEOUT_MS);
}

function skillTypeLabel(type) {
  return { instruction: "指令", actions: "动作", builtin: "内置" }[type] || type;
}

function skillTypeTag(type) {
  return { instruction: "primary", actions: "success", builtin: "info" }[type] || "";
}

async function loadAgentConfig() {
  try {
    const config = await fetchAgentConfig();
    providerOptions.value = config.providers || {};
    const saved = localStorage.getItem(PROVIDER_STORAGE_KEY);
    const defaultProvider = config.default_provider || "deepseek";
    if (saved && config.providers?.[saved]?.configured) {
      provider.value = saved;
    } else if (config.providers?.[defaultProvider]?.configured) {
      provider.value = defaultProvider;
    } else if (config.providers?.deepseek?.configured) {
      provider.value = "deepseek";
    } else if (config.providers?.openai?.configured) {
      provider.value = "openai";
    }
    updateProviderNote();
    if (config.default_run_mode === "auto" || config.default_run_mode === "confirm") {
      runMode.value = config.default_run_mode;
    }
  } catch (err) {
    ElMessage.error(err.message || "加载 Agent 配置失败");
  }
}

function updateProviderNote() {
  const info = providerOptions.value[provider.value];
  providerNote.value = info?.note || (info?.vision ? "Vision 已启用" : "");
}

async function loadRules() {
  try {
    const data = await fetchRules();
    rules.value = data.items || [];
  } catch (err) {
    ElMessage.error(err.message || "加载规则失败");
  }
}

async function loadAgentJobs() {
  try {
    const data = await fetchAgentJobs(50);
    agentJobs.value = Array.isArray(data) ? data : [];
  } catch (err) {
    ElMessage.error(err.message || "加载任务队列失败");
  }
}

async function submitOrchestrationJob() {
  if (!jobForm.value.message.trim()) {
    ElMessage.warning("请先填写任务内容");
    return;
  }
  jobSubmitting.value = true;
  try {
    await submitAgentJob({
      message: jobForm.value.message.trim(),
      provider: jobForm.value.provider,
      mode: jobForm.value.mode,
      run_mode: jobForm.value.run_mode,
      timeout_seconds: jobForm.value.timeout_seconds,
      max_retries: jobForm.value.max_retries,
      priority: jobForm.value.priority,
    });
    ElMessage.success("异步任务已提交");
    await loadAgentJobs();
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  } finally {
    jobSubmitting.value = false;
  }
}

async function refreshOneJob(jobId) {
  try {
    const data = await fetchAgentJob(jobId);
    const idx = agentJobs.value.findIndex((item) => item.job_id === jobId);
    if (idx >= 0) agentJobs.value[idx] = data;
    else agentJobs.value.unshift(data);
  } catch (err) {
    ElMessage.error(err.message || "刷新任务失败");
  }
}

async function cancelOneJob(jobId) {
  try {
    await cancelAgentJobTask(jobId);
    ElMessage.success("已取消任务");
    await refreshOneJob(jobId);
  } catch (err) {
    ElMessage.error(err.message || "取消任务失败");
  }
}

async function runBenchmarkNow() {
  let cases = [];
  try {
    cases = JSON.parse(benchmarkCasesText.value || "[]");
  } catch {
    ElMessage.error("评测 cases JSON 格式无效");
    return;
  }
  if (!Array.isArray(cases) || !cases.length) {
    ElMessage.warning("请至少提供一个评测用例");
    return;
  }
  benchmarkRunning.value = true;
  try {
    benchmarkResult.value = await runAgentBenchmark(cases);
    ElMessage.success("评测完成");
  } catch (err) {
    ElMessage.error(err.message || "评测失败");
  } finally {
    benchmarkRunning.value = false;
  }
}

async function loadAccounts() {
  try {
    const data = await fetchAccounts();
    accounts.value = data.items || [];
    if (data.active_account_id) {
      activeAccountId.value = data.active_account_id;
      setAccountId(data.active_account_id);
    }
  } catch (err) {
    accounts.value = [];
    ElMessage.error(err.message || "加载账号失败");
  }
}

async function switchTenantContext() {
  sessionId.value = null;
  runId.value = null;
  persistSessionIds();
  clearChatUiState();
  await Promise.all([loadChatHistory(), loadAccounts(), loadRules(), loadExperiences()]);
}

async function onTenantChange() {
  const next = (tenantId.value || "default").trim() || "default";
  tenantId.value = next;
  if (next === getTenantId()) return;
  if (running.value) {
    tenantId.value = getTenantId();
    ElMessage.warning("任务运行中，请先停止再切换租户");
    return;
  }
  setTenantId(next);
  window.dispatchEvent(new CustomEvent("huoke-tenant-changed", { detail: next }));
  await switchTenantContext();
  ElMessage.success(`已切换到租户「${next}」`);
}

function onApiKeyChange() {
  setApiKey(apiKey.value);
}

function onExternalTenantChange(event) {
  const next = (event.detail || getTenantId()).trim() || "default";
  if (next === tenantId.value) return;
  tenantId.value = next;
  if (running.value) return;
  switchTenantContext();
}

async function loadAccountBindings() {
  await loadAccounts();
  try {
    const data = await fetchAccountBindings(activeAccountId.value);
    accountBindings.value = data.platforms || [];
  } catch (err) {
    ElMessage.error(err.message || "加载绑定状态失败");
  }
}

function openAccountsDrawer() {
  accountsDrawerVisible.value = true;
}

async function onActiveAccountChange(accountId) {
  if (running.value) {
    activeAccountId.value = getAccountId();
    ElMessage.warning("任务运行中，请先停止再切换账号");
    return;
  }
  try {
    await setActiveAccount(accountId);
    setAccountId(accountId);
    ElMessage.success("已切换账号");
    await loadAccountBindings();
  } catch (err) {
    ElMessage.error(err.message || "切换账号失败");
  }
}

async function createNewAccount() {
  const id = newAccountId.value.trim();
  const label = newAccountLabel.value.trim();
  if (!id || !label) {
    ElMessage.warning("请填写账号 ID 和名称");
    return;
  }
  accountCreating.value = true;
  try {
    await createAccount(id, label);
    newAccountId.value = "";
    newAccountLabel.value = "";
    await loadAccounts();
    ElMessage.success("账号已创建");
  } catch (err) {
    ElMessage.error(err.message || "创建失败");
  } finally {
    accountCreating.value = false;
  }
}

async function bindPlatformLogin(row) {
  bindingLoginPlatform.value = row.platform;
  bindingLoginPlatformLabel.value = row.platform_label || row.platform;
  try {
    const result = await triggerAccountPlatformLogin(activeAccountId.value, row.platform);
    serverLoginUrl.value = result.vnc_url || row.vnc_url || "";
    loginDialogVisible.value = true;
    ElMessage.success(result.message || "请在 VNC 窗口完成扫码登录");
  } catch (err) {
    ElMessage.error(err.message || "启动登录失败");
  } finally {
    bindingLoginPlatform.value = "";
    bindingLoginPlatformLabel.value = "";
  }
}

async function loadExperiences() {
  try {
    if (!dreamAutoLoading.value) {
      dreamAutoLoading.value = true;
      try {
        await consolidateDreams(40, false);
      } catch (_) {
        // 自动整理失败不阻断经验列表加载
      } finally {
        dreamAutoLoading.value = false;
      }
    }
    const data = await fetchExperiences();
    experiences.value = data.items || [];
    if (!selectedExperience.value && experiences.value.length) {
      selectedExperience.value = experiences.value[0];
    }
  } catch (err) {
    ElMessage.error(err.message || "加载经验库失败");
  }
}

async function runDreamConsolidate() {
  dreamConsolidating.value = true;
  try {
    const result = await consolidateDreams(40, false);
    ElMessage.success(`已提炼 ${result.created?.length || 0} 条经验，跳过 ${result.skipped?.length || 0} 条`);
    await loadExperiences();
  } catch (err) {
    ElMessage.error(err.message || "整理失败");
  } finally {
    dreamConsolidating.value = false;
  }
}

async function dreamCurrentRun() {
  if (!runId.value) return;
  dreamRunLoading.value = true;
  try {
    await dreamFromRun(runId.value, false);
    ElMessage.success("已从当前对话提炼经验");
    await loadExperiences();
  } catch (err) {
    ElMessage.error(err.message || "提炼失败");
  } finally {
    dreamRunLoading.value = false;
  }
}

async function toggleExperience(row) {
  try {
    await toggleExperienceEnabled(row.id, row.enabled);
  } catch (err) {
    row.enabled = !row.enabled;
    ElMessage.error(err.message || "更新失败");
  }
}

async function removeExperience(row) {
  try {
    await ElMessageBox.confirm("确定删除这条经验？", "删除经验", { type: "warning" });
    await deleteExperience(row.id);
    if (selectedExperience.value?.id === row.id) selectedExperience.value = null;
    await loadExperiences();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

function openRuleForm(row = null) {
  editingRule.value = row;
  if (row) {
    ruleForm.value = {
      id: row.id,
      name: row.name,
      description: row.description || "",
      content: row.content,
      always_apply: row.always_apply,
      platformsText: (row.platforms || []).join(","),
    };
  } else {
    ruleForm.value = emptyRuleForm();
  }
  ruleFormVisible.value = true;
}

async function saveRule() {
  const platforms = ruleForm.value.platformsText
    ? ruleForm.value.platformsText.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const payload = {
    name: ruleForm.value.name.trim(),
    description: ruleForm.value.description.trim(),
    content: ruleForm.value.content.trim(),
    always_apply: ruleForm.value.always_apply,
    platforms,
  };
  ruleSaving.value = true;
  try {
    if (editingRule.value) {
      await updateRule(editingRule.value.id, payload);
    } else {
      await createRule({ ...payload, id: ruleForm.value.id.trim() });
    }
    ElMessage.success("规则已保存");
    ruleFormVisible.value = false;
    await loadRules();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    ruleSaving.value = false;
  }
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确定删除规则「${row.name}」？`, "确认");
    await deleteRule(row.id);
    await loadRules();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

async function respondApproval(approved) {
  if (!runId.value || !pendingApproval.value) return;
  running.value = true;
  approvalDialogVisible.value = false;
  abortController = new AbortController();
  try {
    await resumeApproval(runId.value, approved, handleEvent, abortController.signal);
  } catch (err) {
    if (err.name !== "AbortError") ElMessage.error(err.message || "审批失败");
  } finally {
    running.value = false;
    pendingApproval.value = null;
    abortController = null;
  }
}

async function respondPlan(approved) {
  if (!runId.value || !pendingPlan.value) return;
  running.value = true;
  planDialogVisible.value = false;
  abortController = new AbortController();
  try {
    await resumePlan(runId.value, approved, handleEvent, abortController.signal);
  } catch (err) {
    if (err.name !== "AbortError") ElMessage.error(err.message || "计划确认失败");
  } finally {
    running.value = false;
    if (!approved) pendingPlan.value = null;
    abortController = null;
  }
}

async function onSkillsDrawerOpen() {
  await Promise.all([loadSkills(), loadSkillHubConfig()]);
}

async function loadSkillHubConfig() {
  try {
    skillHubConfig.value = await fetchSkillHubConfig();
  } catch {
    /* ignore */
  }
}

async function saveSkillHubConfig() {
  skillHubConfigSaving.value = true;
  try {
    const payload = {
      registry: skillHubConfig.value.registry,
      auto_install_enabled: skillHubConfig.value.auto_install_enabled,
    };
    if (skillHubTokenInput.value.trim()) {
      payload.token = skillHubTokenInput.value.trim();
    }
    skillHubConfig.value = await updateSkillHubConfig(payload);
    skillHubTokenInput.value = "";
    ElMessage.success("SkillHub 配置已保存");
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    skillHubConfigSaving.value = false;
  }
}

async function doSkillHubSearch() {
  const q = skillHubSearchQuery.value.trim();
  if (!q) {
    ElMessage.warning("请输入搜索关键词");
    return;
  }
  skillHubSearching.value = true;
  try {
    const data = await searchSkillHub(q, 20);
    skillHubSearchResults.value = data.items || [];
    if (!skillHubSearchResults.value.length) {
      ElMessage.info("未找到匹配技能");
    }
  } catch (err) {
    ElMessage.error(err.message || "搜索失败");
  } finally {
    skillHubSearching.value = false;
  }
}

async function installFromHub(row) {
  const coord =
    row.namespace && row.namespace !== "global"
      ? `@${row.namespace}/${row.slug}`
      : row.slug;
  skillHubInstalling.value = row.slug;
  try {
    await installSkillHub({ coordinate: coord, overwrite: false });
    ElMessage.success(`已安装 ${coord}`);
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "安装失败");
  } finally {
    skillHubInstalling.value = null;
  }
}

async function onSkillHubZipSelected(ev) {
  const file = ev.target?.files?.[0];
  if (!file) return;
  try {
    await installSkillHubZip(file, false);
    ElMessage.success(`已从 zip 安装技能`);
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "安装失败");
  }
  ev.target.value = "";
}

async function loadSkills() {
  try {
    const data = await fetchSkills();
    const effects = await fetchSkillEffects().catch(() => []);
    const effectMap = new Map((effects || []).map((item) => [item.skill_id, item]));
    skills.value = (data.items || []).map((item) => ({
      ...item,
      effect: effectMap.get(item.id) || null,
    }));
  } catch (err) {
    ElMessage.error(err.message || "加载技能失败");
  }
}

function formatSkillScore(score) {
  if (score == null) return "-";
  return `${Math.round(Number(score))}`;
}

function skillScoreTag(score) {
  const n = Number(score ?? 0);
  if (n >= 85) return "success";
  if (n >= 60) return "warning";
  return "danger";
}

function riskTagType(level) {
  if (level === "high") return "danger";
  if (level === "medium") return "warning";
  return "success";
}

function riskLabel(level, rate) {
  const n = Number(rate ?? 0);
  if (level === "high") return `高(${n}%)`;
  if (level === "medium") return `中(${n}%)`;
  return `低(${n}%)`;
}

async function openSkillEffect(row) {
  skillEffectVisible.value = true;
  selectedSkillEffect.value = { skill_id: row.id, stats: row.effect || {}, records: [] };
  try {
    const data = await fetchSkillEffectDetail(row.id, 30);
    selectedSkillEffect.value = data;
  } catch (err) {
    ElMessage.error(err.message || "加载技能效果失败");
  }
}

async function loadBuiltinHandlers() {
  try {
    builtinHandlers.value = await fetchBuiltinHandlers();
  } catch {
    builtinHandlers.value = [];
  }
}

function openSkillForm(row = null) {
  editingSkill.value = row;
  skillFormMode.value = "form";
  if (row) {
    skillForm.value = {
      id: row.id,
      name: row.name,
      description: row.description,
      type: row.type,
      content: row.content || "",
      actionsJson: JSON.stringify(row.actions || [], null, 2),
      parametersJson: JSON.stringify(row.parameters || [], null, 2),
      builtin_handler: row.builtin_handler,
      disable_model_invocation: row.disable_model_invocation || false,
      markdown: "",
      markdownPreview: "",
    };
  } else {
    skillForm.value = emptySkillForm();
  }
  skillFormVisible.value = true;
}

async function parseSkillFormMarkdown() {
  if (!skillForm.value.markdown.trim()) {
    ElMessage.warning("请先粘贴 SKILL.md");
    return;
  }
  try {
    const data = await parseSkillMarkdown(skillForm.value.markdown);
    skillForm.value.markdownPreview = JSON.stringify(data.skill, null, 2);
  } catch (err) {
    ElMessage.error(err.message || "解析失败");
  }
}

async function saveSkill() {
  if (skillFormMode.value === "markdown") {
    if (!skillForm.value.markdown.trim()) {
      ElMessage.warning("请粘贴 SKILL.md");
      return;
    }
    skillSaving.value = true;
    try {
      await importSkillMarkdown(skillForm.value.markdown, false);
      ElMessage.success("技能已从 SKILL.md 导入");
      skillFormVisible.value = false;
      await loadSkills();
    } catch (err) {
      ElMessage.error(err.message || "导入失败");
    } finally {
      skillSaving.value = false;
    }
    return;
  }

  let parameters = [];
  let actions = [];
  try {
    parameters = JSON.parse(skillForm.value.parametersJson || "[]");
    if (skillForm.value.type === "actions") {
      actions = JSON.parse(skillForm.value.actionsJson || "[]");
    }
  } catch {
    ElMessage.error("参数或动作 JSON 格式无效");
    return;
  }

  const payload = {
    name: skillForm.value.name.trim(),
    description: skillForm.value.description.trim(),
    type: skillForm.value.type,
    parameters,
    content: skillForm.value.content,
    actions,
    builtin_handler: skillForm.value.type === "builtin" ? skillForm.value.builtin_handler : null,
    disable_model_invocation: skillForm.value.disable_model_invocation,
  };

  skillSaving.value = true;
  try {
    if (editingSkill.value) {
      await updateSkill(editingSkill.value.id, payload);
      ElMessage.success("技能已更新");
    } else {
      await createSkill({ ...payload, id: skillForm.value.id.trim() });
      ElMessage.success("技能已创建");
    }
    skillFormVisible.value = false;
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    skillSaving.value = false;
  }
}

async function toggleSkill(row) {
  if (row.scope === "global") return;
  try {
    await updateSkill(row.id, { enabled: row.enabled });
  } catch (err) {
    row.enabled = !row.enabled;
    ElMessage.error(err.message || "更新失败");
  }
}

async function removeSkill(row) {
  try {
    await ElMessageBox.confirm(`确定删除技能「${row.name}」？`, "确认");
    await deleteSkill(row.id);
    ElMessage.success("已删除");
    await loadSkills();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

function invokeSkill(row) {
  inputText.value = `/${row.id} 请执行「${row.name}」`;
  skillsDrawerVisible.value = false;
}

function openImportDialog() {
  importTab.value = "markdown";
  importMarkdown.value = "";
  importPreview.value = "";
  importJsonSkills.value = [];
  importJsonCount.value = 0;
  importOverwrite.value = false;
  importDialogVisible.value = true;
}

async function previewMarkdown() {
  if (!importMarkdown.value.trim()) {
    ElMessage.warning("请先粘贴 SKILL.md");
    return;
  }
  try {
    const data = await parseSkillMarkdown(importMarkdown.value);
    importPreview.value = JSON.stringify(data.skill, null, 2);
  } catch (err) {
    ElMessage.error(err.message || "解析失败");
  }
}

async function onMdFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  importMarkdown.value = await file.text();
  event.target.value = "";
}

async function onJsonFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const raw = JSON.parse(await file.text());
    const list = raw.skills || raw.items || (Array.isArray(raw) ? raw : []);
    importJsonSkills.value = list;
    importJsonCount.value = list.length;
  } catch {
    ElMessage.error("JSON 格式无效");
  }
  event.target.value = "";
}

async function confirmImport() {
  importLoading.value = true;
  try {
    if (importTab.value === "markdown") {
      await importSkillMarkdown(importMarkdown.value, importOverwrite.value);
      ElMessage.success("SKILL.md 导入成功");
    } else {
      if (!importJsonSkills.value.length) {
        ElMessage.warning("请先选择 JSON 文件");
        return;
      }
      const result = await importSkillsJson(importJsonSkills.value, importOverwrite.value);
      ElMessage.success(`导入 ${result.imported.length} 个，跳过 ${result.skipped.length} 个`);
      if (result.errors?.length) ElMessage.warning(result.errors.join("; "));
    }
    importDialogVisible.value = false;
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "导入失败");
  } finally {
    importLoading.value = false;
  }
}

async function exportAllSkills() {
  try {
    const bundle = await exportSkillsJson();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "skills-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    ElMessage.error(err.message || "导出失败");
  }
}

async function exportSkillMd(row) {
  try {
    await downloadWithAuth(skillMarkdownDownloadUrl(row.id), `${row.id}-SKILL.md`);
  } catch (err) {
    ElMessage.error(err.message || "导出失败");
  }
}

function openRecordDialog() {
  recordForm.value = {
    id: `recorded-${Date.now().toString(36)}`,
    name: "",
    description: "从对话录制的浏览器操作流",
  };
  recordDialogVisible.value = true;
}

function clearRecordedSteps() {
  recordedSteps.value = [];
  pendingToolArgs.value = {};
  ElMessage.success("已清空录制");
}

async function saveRecordedSkill() {
  const { id, name, description } = recordForm.value;
  if (!id.trim() || !name.trim() || !description.trim()) {
    ElMessage.warning("请填写完整信息");
    return;
  }
  recordSaving.value = true;
  try {
    await recordSkillFromSteps({
      id: id.trim(),
      name: name.trim(),
      description: description.trim(),
      steps: recordedSteps.value,
    });
    ElMessage.success("actions 技能已保存");
    recordDialogVisible.value = false;
    await loadSkills();
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    recordSaving.value = false;
  }
}

function persistSessionIds() {
  if (sessionId.value) localStorage.setItem(SESSION_STORAGE_KEY, sessionId.value);
  else localStorage.removeItem(SESSION_STORAGE_KEY);
  if (runId.value) localStorage.setItem(RUN_STORAGE_KEY, runId.value);
  else localStorage.removeItem(RUN_STORAGE_KEY);
}

function runMessagesToUi(runMessages) {
  const ui = [];
  for (const msg of runMessages || []) {
    if (msg.role === "user" && typeof msg.content === "string") {
      if (msg.content.startsWith("【技能") || msg.content.startsWith("这是 browser_screenshot")) continue;
      ui.push({ role: "user", content: msg.content });
    } else if (msg.role === "assistant" && msg.content) {
      ui.push({ role: "assistant", content: msg.content });
    }
  }
  return ui;
}

async function restoreRunIfNeeded() {
  if (!runId.value) return;
  try {
    await syncRunState();
  } catch {
    runId.value = null;
    runResumable.value = false;
    persistSessionIds();
  }
}

async function syncRunState() {
  if (!runId.value) {
    runResumable.value = false;
    runStatus.value = null;
    return;
  }
  const run = await fetchAgentRun(runId.value);
  runStatus.value = run.status;
  runResumable.value = !!run.resumable;
  if (run.messages?.length) {
    messages.value = runMessagesToUi(run.messages);
  }
  if (run.browser_session_id) {
    sessionId.value = run.browser_session_id;
    persistSessionIds();
  }
  if (run.pending_plan) {
    pendingPlan.value = run.pending_plan;
    planDialogVisible.value = true;
  }
  if (run.pending_approval) {
    pendingApproval.value = run.pending_approval;
    approvalDialogVisible.value = true;
  }
  if (runResumable.value) {
    agentMode.value = run.mode || agentMode.value;
    runMode.value = run.run_mode || runMode.value;
    if (run.provider) provider.value = run.provider;
  }
  reviewReport.value = run.review_report || {};
  validationReport.value = run.validation_report || {};
}

function statusAlertType(status) {
  if (status === "completed") return "success";
  if (status === "cancelled" || status === "waiting_plan" || status === "waiting_approval") return "warning";
  return "error";
}

function ensureAgentWebSocket() {
  if (!useWebSocket.value) return null;
  if (agentWs && agentWs.readyState === WebSocket.OPEN) return agentWs;
  if (agentWs && agentWs.readyState === WebSocket.CONNECTING) return agentWs;
  agentWs = createAgentWebSocket({
    onEvent: (event) => {
      if (wsChatResolver) {
        handleEvent(event);
        touchWsWatchdog();
        const isSubagent = event.data?.subagent;
        if (event.type === "done" || (event.type === "error" && !isSubagent)) {
          clearWsWatchdog();
          wsChatResolver();
          wsChatResolver = null;
          wsChatRejector = null;
        }
      } else {
        handleEvent(event);
      }
    },
    onClose: () => {
      if (wsChatRejector) {
        clearWsWatchdog();
        const reject = wsChatRejector;
        wsChatResolver = null;
        wsChatRejector = null;
        reject(new Error("WebSocket 连接已断开，任务可继续执行"));
      }
      agentWs = null;
    },
  });
  return agentWs;
}

async function loadCheckpoints() {
  if (!runId.value) return;
  try {
    const data = await fetchCheckpoints(runId.value);
    checkpoints.value = data.items || [];
  } catch (err) {
    ElMessage.error(err.message || "加载检查点失败");
  }
}

async function doRestoreCheckpoint(checkpointId) {
  if (!runId.value || running.value) return;
  try {
    const result = await restoreCheckpoint(runId.value, checkpointId);
    if (result.url) pageInfo.value.url = result.url;
    if (result.title) pageInfo.value.title = result.title;
    ElMessage.success("已恢复到检查点");
  } catch (err) {
    ElMessage.error(err.message || "恢复失败");
  }
}

async function stopRun() {
  if (!runId.value) return;
  try {
    if (useWebSocket.value && agentWs?.readyState === WebSocket.OPEN) {
      sendAgentWsMessage(agentWs, "cancel", { run_id: runId.value });
    } else {
      await cancelAgentRun(runId.value);
    }
    if (abortController) abortController.abort();
    ElMessage.warning("已发送停止请求");
  } catch (err) {
    ElMessage.error(err.message || "停止失败");
  }
}

function truncateText(text, max = 96) {
  if (!text) return "";
  const s = String(text).replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

function formatBudget(value) {
  const obj = value && typeof value === "object" ? value : {};
  const keys = Object.keys(obj);
  if (!keys.length) return "-";
  return keys.map((k) => `${k}:${obj[k]}`).join(" · ");
}

function formatSkillPriority(value) {
  if (!Array.isArray(value) || !value.length) return "-";
  return value.slice(0, 8).join(" > ");
}

function formatPhase(value) {
  if (!value) return "-";
  return { plan: "Plan", act: "Act", review: "Review" }[value] || value;
}

function formatSnapshot(value) {
  const obj = value && typeof value === "object" ? value : {};
  const keys = Object.keys(obj);
  if (!keys.length) return "-";
  return keys
    .slice(0, 8)
    .map((k) => `${k}:${truncateText(obj[k], 42)}`)
    .join(" · ");
}

function formatTopFailures(value) {
  if (!Array.isArray(value) || !value.length) return "-";
  return value.map((item) => `${item.type}:${item.count}`).join(" · ");
}

function formatIssueList(value) {
  if (!Array.isArray(value) || !value.length) return "-";
  return value.slice(0, 4).join("；");
}

function tryParseJson(text) {
  if (!text?.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function formatJson(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function shouldHideMessage(msg) {
  if (msg.role !== "user" || typeof msg.content !== "string") return false;
  return msg.content.startsWith("【技能") || msg.content.startsWith("这是 browser_screenshot");
}

function formatToolSummary(toolName, data) {
  if (!data) return "完成";
  if (data.error) return truncateText(data.error, 100);
  if (data.summary) return truncateText(data.summary, 100);
  if (data.api_capture_count != null) return `接口 ${data.api_capture_count} 条`;
  if (data.count != null && data.items) return `网络数据 ${data.count} 条`;
  if (data.url) return truncateText(data.url, 100);
  if (data.title) return truncateText(data.title, 100);
  if (data.text) return truncateText(data.text, 100);
  if (data.status === "completed") return "已完成";
  if (toolName === "task_complete") return "任务完成";
  return "完成";
}

function buildResultCard(content) {
  const data = tryParseJson(content);
  if (!data || typeof data !== "object") return null;
  const summary =
    data.summary ||
    (typeof data.result === "string" ? data.result : "") ||
    "";
  if (!(data.status === "completed" || summary || data.result)) return null;
  return {
    status: data.status || "",
    summary,
    summaryHtml: renderChatMarkdown(summary),
    raw: data,
    rawText: formatJson(data),
  };
}

function buildSkillResultCard(parsed) {
  if (!parsed || parsed.type !== "builtin" || parsed.status !== "completed") return null;
  const lines = [];
  if (parsed.summary) lines.push(parsed.summary);
  if (parsed.video_url) lines.push(`**视频**: ${parsed.video_url}`);
  if (parsed.output_file) lines.push(`**输出文件**: \`${parsed.output_file}\``);
  if (parsed.output_files?.length) {
    lines.push("**输出文件**:");
    parsed.output_files.forEach((f) => lines.push(`- \`${f}\``));
  }
  if (parsed.total_comments_captured != null) {
    lines.push(`**抓到评论数**: ${parsed.total_comments_captured}`);
  }
  if (parsed.api_total_top_comments != null) {
    lines.push(`**接口总数**: ${parsed.api_total_top_comments}`);
  }
  if (parsed.video_count != null) {
    lines.push(`**视频数**: ${parsed.video_count}`);
  }
  if (parsed.videos_preview?.length) {
    lines.push("**视频预览**:");
    parsed.videos_preview.slice(0, 5).forEach((v, i) => {
      const title = v.title || v.video_url || v.aweme_id || "未命名";
      const author = v.author ? ` · @${v.author}` : "";
      const stats = v.digg_count ? ` · ${v.digg_count} 赞` : "";
      lines.push(`${i + 1}. ${title}${author}${stats}`);
    });
  }
  const summaryMd = lines.join("\n\n");
  return {
    badge: parsed.skill_name || "内置技能",
    status: parsed.status || "",
    summary: parsed.summary || "",
    summaryHtml: renderChatMarkdown(summaryMd),
    raw: parsed,
    rawText: formatJson(parsed),
  };
}

function enrichMessage(msg) {
  if (msg.role === "user") {
    return { ...msg, kind: "user", text: msg.content };
  }

  if (msg.role === "tool") {
    const parsed = tryParseJson(msg.content);
    if (msg.toolName === "task_complete") {
      const resultCard = buildResultCard(msg.content);
      if (resultCard) return { ...msg, kind: "result", resultCard };
    }
    const skillCard = buildSkillResultCard(parsed);
    if (skillCard) {
      return { ...msg, kind: "skill_result", resultCard: skillCard };
    }
    return {
      ...msg,
      kind: "tool",
      parsed,
      summary: formatToolSummary(msg.toolName, parsed),
      hasError: !!parsed?.error,
    };
  }

  if (msg.error || msg.isError) {
    return {
      ...msg,
      kind: "error",
      text: msg.content,
    };
  }

  const resultCard = buildResultCard(msg.content);
  if (resultCard) {
    return { ...msg, kind: "result", resultCard };
  }

  const subagentMatch = msg.content?.match(/^\[子任务\]\s*([\s\S]*)$/);
  if (subagentMatch) {
    const text = subagentMatch[1].trim();
    return {
      ...msg,
      kind: "subagent",
      text,
      html: renderChatMarkdown(text),
    };
  }

  return {
    ...msg,
    kind: "assistant",
    text: msg.content,
    html: renderChatMarkdown(msg.content),
  };
}

function toggleChatToolExpand(idx) {
  const next = new Set(expandedChatTools.value);
  if (next.has(idx)) next.delete(idx);
  else next.add(idx);
  expandedChatTools.value = next;
}

function messageKey(msg, idx) {
  const head = String(msg.content || msg.text || "").slice(0, 24);
  return `${idx}-${msg.role}-${msg.kind || ""}-${head}`;
}

function formatStepSummary(step) {
  if (step.status === "running") {
    const args = tryParseJson(step.detail);
    if (args?.url) return truncateText(args.url, 72);
    if (args?.selector) return truncateText(args.selector, 72);
    return "执行中…";
  }
  const data = tryParseJson(step.detail);
  if (!data) return truncateText(step.detail, 96);
  if (data.error) return `错误：${truncateText(data.error, 80)}`;
  if (data.summary) return truncateText(data.summary, 96);
  if (data.url) return truncateText(data.url, 72);
  if (data.title) return truncateText(data.title, 72);
  if (data.text) return truncateText(data.text, 96);
  if (data.status === "completed") return "已完成";
  const preview = Object.entries(data)
    .slice(0, 2)
    .map(([k, v]) => `${k}: ${truncateText(v, 40)}`)
    .join(" · ");
  return preview || "完成";
}

function toggleStepExpand(idx) {
  const next = new Set(expandedSteps.value);
  if (next.has(idx)) next.delete(idx);
  else next.add(idx);
  expandedSteps.value = next;
}

function toggleCheckpointExpand(id) {
  const next = new Set(expandedCheckpoints.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedCheckpoints.value = next;
}

function applyQuickPrompt(text) {
  inputText.value = text;
}

async function scrollToBottom() {
  await nextTick();
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight;
  }
}

async function loadChatHistory() {
  historyLoading.value = true;
  try {
    const data = await fetchAgentRuns(50);
    chatHistory.value = data.items || [];
  } catch {
    chatHistory.value = [];
  } finally {
    historyLoading.value = false;
  }
}

function clearChatUiState() {
  runResumable.value = false;
  runStatus.value = null;
  messages.value = [];
  steps.value = [];
  expandedChatTools.value = new Set();
  recordedSteps.value = [];
  pendingToolArgs.value = {};
  screenshot.value = null;
  pageInfo.value = { url: "", title: "" };
  agentPhase.value = "plan";
  taskSnapshot.value = {};
  reviewReport.value = {};
  validationReport.value = {};
  agentMeta.value = { budget_limits: {}, tool_usage: {}, failure_streak: {}, skill_priority: [] };
  finalStatus.value = null;
  streamingText.value = "";
  checkpoints.value = [];
  expandedSteps.value = new Set();
  expandedCheckpoints.value = new Set();
  pendingPlan.value = null;
  pendingApproval.value = null;
}

async function newChat() {
  if (running.value) return;
  sessionId.value = null;
  runId.value = null;
  visionEnabled.value = false;
  persistSessionIds();
  clearChatUiState();
  if (window.innerWidth <= 960) sidebarCollapsed.value = true;
}

async function selectChat(id) {
  if (running.value || !id || id === runId.value) return;
  runId.value = id;
  persistSessionIds();
  clearChatUiState();
  await restoreRunIfNeeded();
  await loadCheckpoints();
  await scrollToBottom();
  if (window.innerWidth <= 960) sidebarCollapsed.value = true;
}

async function deleteChat(id) {
  if (!id) return;
  try {
    await ElMessageBox.confirm("确定删除这条对话记录？", "删除对话", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteAgentRun(id);
    if (runId.value === id) {
      sessionId.value = null;
      runId.value = null;
      persistSessionIds();
      clearChatUiState();
    }
    await loadChatHistory();
    ElMessage.success("已删除");
  } catch (err) {
    ElMessage.error(err.message || "删除失败");
  }
}

function handleEvent(event) {
  const { type, data } = event;
  switch (type) {
    case "session":
      sessionId.value = data.session_id;
      if (data.run_id) runId.value = data.run_id;
      if (data.provider) provider.value = data.provider;
      if (data.vision_enabled) visionEnabled.value = data.vision_enabled;
      if (data.stream_enabled !== undefined) streamEnabled.value = data.stream_enabled;
      if (data.provider_note) providerNote.value = data.provider_note;
      if (data.phase) agentPhase.value = data.phase;
      if (data.task_snapshot) taskSnapshot.value = data.task_snapshot;
      if (data.agent_meta) agentMeta.value = data.agent_meta;
      persistSessionIds();
      loadCheckpoints();
      loadChatHistory();
      break;
    case "plan":
      pendingPlan.value = { summary: data.summary, steps: data.steps || [] };
      planDialogVisible.value = true;
      break;
    case "approval_request":
      pendingApproval.value = {
        tool: data.tool,
        arguments: data.arguments,
        tool_call_id: data.tool_call_id,
      };
      approvalDialogVisible.value = true;
      break;
    case "message_delta":
      streamingText.value += data.delta || "";
      break;
    case "message":
      if (data.content) {
        streamingText.value = "";
        messages.value.push({
          role: "assistant",
          content: data.subagent ? `[子任务] ${data.content}` : data.content,
        });
      } else if (data.final) {
        streamingText.value = "";
      }
      break;
    case "context_compressed":
      ElMessage.info(`上下文已压缩：${data.before} → ${data.after} 条消息`);
      break;
    case "skill_installed":
      ElMessage.success(data.message || `已安装技能 ${data.slug || ""}`);
      loadSkills();
      break;
    case "skill_install_failed":
      ElMessage.warning(data.error || "技能自动安装失败");
      break;
    case "step":
      break;
    case "tool_start":
      pendingToolArgs.value[data.tool_call_id] = {
        tool: data.tool,
        arguments: data.arguments || {},
      };
      steps.value.push({
        step: steps.value.length + 1,
        tool: data.tool,
        detail: JSON.stringify(data.arguments, null, 2),
        status: "running",
        isSkill: data.is_skill,
        subagent: data.subagent,
        toolCallId: data.tool_call_id,
      });
      sideTab.value = "steps";
      break;
    case "tool_result": {
      const pending = pendingToolArgs.value[data.tool_call_id];
      if (
        pending &&
        RECORDABLE_TOOLS.has(pending.tool) &&
        !data.is_skill &&
        !data.result?.error
      ) {
        recordedSteps.value.push({
          tool: pending.tool,
          arguments: pending.arguments,
          args: pending.arguments,
        });
      }
      delete pendingToolArgs.value[data.tool_call_id];
      const last = steps.value[steps.value.length - 1];
      if (last) {
        last.status = data.result?.error ? "error" : "done";
        last.detail = JSON.stringify(data.result, null, 2);
      }
      messages.value.push({
        role: "tool",
        toolName: data.tool,
        content: JSON.stringify(data.result, null, 2),
      });
      if (data.result?.url) pageInfo.value.url = data.result.url;
      if (data.result?.title) pageInfo.value.title = data.result.title;
      if (data.phase) agentPhase.value = data.phase;
      if (data.task_snapshot) taskSnapshot.value = data.task_snapshot;
      if (data.agent_meta) agentMeta.value = data.agent_meta;
      break;
    }
    case "screenshot":
      screenshot.value = `data:image/png;base64,${data.base64}`;
      sideTab.value = "preview";
      break;
    case "checkpoint":
      checkpoints.value.unshift({
        checkpoint_id: data.checkpoint_id,
        step: data.step,
        tool: data.tool,
        url: data.url,
        title: data.title,
      });
      break;
    case "cancelled":
      finalStatus.value = { status: "cancelled", summary: data.summary || "任务已取消" };
      break;
    case "done":
      streamingText.value = "";
      if (data.phase) agentPhase.value = data.phase;
      if (data.task_snapshot) taskSnapshot.value = data.task_snapshot;
      if (data.review_report) reviewReport.value = data.review_report;
      if (data.validation_report) validationReport.value = data.validation_report;
      finalStatus.value = { status: data.status, summary: data.summary };
      if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
        runResumable.value = false;
      }
      if (
        data.summary &&
        !messages.value.some((m) => m.content === data.summary) &&
        data.status !== "waiting_approval" &&
        data.status !== "waiting_plan"
      ) {
        messages.value.push({ role: "assistant", content: data.summary });
      }
      loadChatHistory();
      break;
    case "error":
      if (data.code === "binding_required") {
        ElMessageBox.confirm(
          `${data.message || "请先绑定平台账号"}\n\n租户: ${data.tenant_id || tenantId.value}\n账号: ${data.account_id || activeAccountId.value}\n平台: ${data.platform_label || data.platform || ""}`,
          "需要绑定平台账号",
          {
            confirmButtonText: "去绑定",
            cancelButtonText: "知道了",
            type: "warning",
          },
        )
          .then(() => {
            accountsDrawerVisible.value = true;
          })
          .catch(() => {});
      } else {
        ElMessage.error(data.message || "发生错误");
      }
      messages.value.push({
        role: "assistant",
        content: data.message || "发生错误",
        error: true,
      });
      break;
    default:
      break;
  }
  scrollToBottom();
}

async function sendMessageViaSse(text, onEvent, signal) {
  await streamAgentChat({
    message: text,
    sessionId: sessionId.value,
    runId: runId.value,
    provider: provider.value,
    headless: headless.value,
    mode: agentMode.value,
    runMode: runMode.value,
    signal: signal || abortController?.signal,
    onEvent: onEvent || handleEvent,
  });
}

async function sendMessageViaWs(text) {
  const ws = ensureAgentWebSocket();
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, arg) => {
      if (settled) return;
      settled = true;
      clearWsWatchdog();
      if (wsChatResolver || wsChatRejector) {
        wsChatResolver = null;
        wsChatRejector = null;
      }
      fn(arg);
    };
    const onOpen = () => {
      wsChatResolver = resolve;
      wsChatRejector = reject;
      touchWsWatchdog();
      try {
        sendAgentWsMessage(ws, "chat", {
          message: text,
          session_id: sessionId.value,
          run_id: runId.value,
          provider: provider.value,
          headless: headless.value,
          mode: agentMode.value,
          run_mode: runMode.value,
        });
      } catch (err) {
        clearWsWatchdog();
        wsChatResolver = null;
        wsChatRejector = null;
        finish(reject, err);
      }
    };
    const onFail = () => finish(reject, new Error("WebSocket 连接失败"));
    if (ws.readyState === WebSocket.OPEN) {
      onOpen();
    } else if (ws.readyState === WebSocket.CONNECTING) {
      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onFail, { once: true });
    } else {
      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onFail, { once: true });
    }
  });
}

async function runAgentStream(streamFn) {
  abortController = new AbortController();
  try {
    await streamFn(handleEvent, abortController.signal);
    await syncRunState();
    await loadChatHistory();
  } catch (err) {
    if (err.name !== "AbortError") {
      try {
        await syncRunState();
      } catch {
        // ignore
      }
      if (runResumable.value) {
        ElMessage.warning(err.message || "连接中断，可点击「继续执行」恢复任务");
      } else {
        ElMessage.error(err.message || "请求失败");
      }
    }
  } finally {
    running.value = false;
    streamingText.value = "";
    abortController = null;
  }
}

async function resumeRun() {
  if (!runId.value || running.value || !runResumable.value) return;
  running.value = true;
  streamingText.value = "";
  finalStatus.value = null;
  runResumable.value = false;
  await scrollToBottom();
  await runAgentStream((onEvent, signal) => resumeAgentRun(runId.value, onEvent, signal));
}

async function sendMessage() {
  const text = inputText.value.trim();
  if (!text || running.value) return;

  messages.value.push({ role: "user", content: text });
  inputText.value = "";
  running.value = true;
  streamingText.value = "";
  finalStatus.value = null;
  runResumable.value = false;
  await scrollToBottom();

  if (useWebSocket.value) {
    abortController = new AbortController();
    try {
      await sendMessageViaWs(text);
      await syncRunState();
    } catch (wsErr) {
      if (agentWs) {
        agentWs.close();
        agentWs = null;
      }
      try {
        await syncRunState();
      } catch {
        // ignore
      }
      if (runResumable.value) {
        ElMessage.warning("连接中断，可点击「继续执行」恢复任务");
      } else {
        ElMessage.warning("WebSocket 不可用，已切换为 SSE");
        useWebSocket.value = false;
        await runAgentStream((onEvent, signal) =>
          sendMessageViaSse(text, onEvent, signal),
        );
      }
    } finally {
      running.value = false;
      streamingText.value = "";
      abortController = null;
    }
    return;
  }

  await runAgentStream((onEvent, signal) =>
    sendMessageViaSse(text, onEvent, signal),
  );
}

onMounted(async () => {
  tenantId.value = getTenantId();
  apiKey.value = getApiKey();
  window.addEventListener("huoke-tenant-changed", onExternalTenantChange);
  await loadAgentConfig();
  loadSkills();
  loadRules();
  loadAccounts();
  loadBuiltinHandlers();
  await loadChatHistory();
  await restoreRunIfNeeded();
  if (runId.value) loadCheckpoints();
});

watch(provider, (value) => {
  localStorage.setItem(PROVIDER_STORAGE_KEY, value);
  updateProviderNote();
});

onBeforeUnmount(() => {
  window.removeEventListener("huoke-tenant-changed", onExternalTenantChange);
  if (abortController) abortController.abort();
  if (agentWs) {
    agentWs.close();
    agentWs = null;
  }
});
</script>

<style scoped>
.agent-page {
  --agent-primary: var(--primary, #0f766e);
  --agent-primary-soft: #ecfdf5;
  --agent-primary-muted: #ccfbf1;
  --agent-bg: #ffffff;
  --agent-surface: #f8fafb;
  --agent-border: #e5e7eb;
  --agent-text: var(--text, #1f2937);
  --agent-muted: var(--muted, #6b7280);
  --el-color-primary: var(--agent-primary);

  position: relative;
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100vh;
  min-height: 0;
  background: var(--agent-bg);
  overflow: hidden;
}

/* ── History sidebar ── */
.history-sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--agent-surface);
  color: var(--agent-text);
  border-right: 1px solid var(--agent-border);
  transition: width 0.2s ease;
  min-height: 0;
}

.history-sidebar.collapsed {
  width: 56px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 12px 10px;
  text-decoration: none;
  color: var(--agent-text);
  flex-shrink: 0;
  border-bottom: 1px solid var(--agent-border);
}

.sidebar-brand:hover {
  color: var(--agent-primary);
}

.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--agent-primary);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-text {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-sidebar.collapsed .brand-text {
  display: none;
}

.history-sidebar.collapsed .sidebar-brand {
  justify-content: center;
  padding: 12px 8px;
}

.sidebar-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  flex-shrink: 0;
}

.new-chat-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--agent-border);
  border-radius: 10px;
  background: var(--agent-bg);
  color: var(--agent-text);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.new-chat-btn:hover:not(:disabled) {
  background: var(--agent-primary-soft);
  border-color: var(--agent-primary-muted);
  color: var(--agent-primary);
}

.new-chat-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.history-sidebar.collapsed .new-chat-btn {
  flex: 0;
  width: 36px;
  min-height: 36px;
  padding: 0;
  justify-content: center;
}

.history-sidebar.collapsed .new-chat-btn span {
  display: none;
}

.sidebar-collapse-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--agent-muted);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sidebar-collapse-btn:hover {
  background: var(--agent-primary-soft);
  color: var(--agent-primary);
}

.history-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px 8px;
  min-height: 0;
}

.history-empty {
  padding: 24px 12px;
  font-size: 13px;
  color: var(--agent-muted);
  text-align: center;
}

.history-group {
  margin-bottom: 12px;
}

.history-group-label {
  padding: 6px 10px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--agent-muted);
  letter-spacing: 0.02em;
}

.history-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px;
  margin-bottom: 2px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--agent-text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
}

.history-item:hover {
  background: var(--agent-bg);
}

.history-item.active {
  background: var(--agent-bg);
  box-shadow: inset 3px 0 0 var(--agent-primary);
}

.history-item.running {
  box-shadow: inset 3px 0 0 var(--agent-primary);
}

.history-item:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.history-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.35;
}

.history-delete {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: transparent;
  transition: color 0.15s, background 0.15s;
}

.history-item:hover .history-delete {
  color: var(--agent-muted);
}

.history-delete:hover {
  color: #ef4444 !important;
  background: rgba(239, 68, 68, 0.12);
}

.sidebar-foot {
  flex-shrink: 0;
  display: flex;
  gap: 6px;
  padding: 10px;
  border-top: 1px solid var(--agent-border);
}

.sidebar-tenant {
  flex-shrink: 0;
  padding: 8px 10px 4px;
  border-top: 1px solid var(--agent-border);
}

.sidebar-tenant-gap {
  margin-top: 8px;
}

.sidebar-account {
  flex-shrink: 0;
  padding: 8px 10px 4px;
  border-top: 1px solid var(--agent-border);
}

.sidebar-account-label {
  font-size: 11px;
  color: var(--agent-muted);
  margin-bottom: 6px;
}

.sidebar-account-select {
  width: 100%;
}

.sidebar-link {
  flex: 1;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--agent-muted);
  font-size: 12px;
  padding: 8px;
  cursor: pointer;
}

.sidebar-link:hover {
  background: var(--agent-bg);
  color: var(--agent-primary);
}

.main-shell {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--agent-bg);
}

/* ── Workspace ── */
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 0;
  flex: 1;
  min-height: 0;
}

/* ── Chat panel ── */
.chat-panel {
  --chat-thread-width: 768px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: var(--agent-bg);
  border-right: 1px solid var(--agent-border);
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--agent-border);
  flex-shrink: 0;
  background: var(--agent-bg);
  z-index: 2;
}

.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.resume-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 16px 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.resume-banner-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #92400e;
}

.resume-banner-text strong {
  font-size: 13px;
  color: #78350f;
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
  background: var(--agent-bg);
}

.thread {
  min-height: 100%;
}

.thread-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: min(520px, calc(100vh - 280px));
  text-align: center;
  padding: 40px 24px;
  max-width: var(--chat-thread-width);
  margin: 0 auto;
}

.welcome-logo {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--agent-primary);
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.welcome-title {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 600;
  color: var(--agent-text);
  letter-spacing: -0.02em;
}

.welcome-desc {
  margin: 0 0 24px;
  font-size: 15px;
  color: var(--agent-muted);
}

.composer-dock {
  flex-shrink: 0;
  padding: 12px 16px 20px;
  background: var(--agent-bg);
  border-top: none;
}

.composer-inner {
  max-width: var(--chat-thread-width);
  margin: 0 auto;
  border: 1px solid var(--agent-border);
  border-radius: 24px;
  background: var(--agent-bg);
  box-shadow: 0 2px 12px rgba(15, 118, 110, 0.06);
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-inner:focus-within {
  border-color: var(--agent-primary-muted);
  box-shadow: 0 4px 20px rgba(15, 118, 110, 0.1);
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.mobile-sidebar-toggle {
  display: none;
  width: 34px;
  height: 34px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.mobile-sidebar-toggle:hover {
  background: #f9fafb;
}

.title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(420px, 50vw);
  color: var(--agent-text);
}

.status-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.chip {
  font-size: 10px;
  line-height: 1;
  padding: 3px 7px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.chip-live {
  background: var(--agent-primary-soft);
  color: var(--agent-primary);
  animation: pulse 1.6s ease-in-out infinite;
}

.chip-tenant {
  background: #eff6ff;
  color: #1d4ed8;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-accent {
  background: var(--agent-primary-soft);
  color: var(--agent-primary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  max-width: 720px;
}

.prompt-chip {
  padding: 10px 14px;
  border: 1px solid var(--agent-border);
  border-radius: 12px;
  background: var(--agent-bg);
  color: var(--agent-text);
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
  max-width: 280px;
  text-align: left;
}

.prompt-chip:hover {
  border-color: var(--agent-primary-muted);
  background: var(--agent-primary-soft);
  box-shadow: 0 1px 3px rgba(15, 118, 110, 0.08);
}

.step-json {
  margin: 0;
  border-top: 1px solid #f0f0f0;
  border-radius: 0;
  max-height: 140px;
  padding: 10px;
  background: #1e293b;
  color: #e2e8f0;
  font-size: 11px;
  line-height: 1.5;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── Composer ── */
.composer-box {
  border: 1px solid #d9d9e3;
  border-radius: 26px;
  background: #fff;
  box-shadow: 0 0 0 0 transparent, 0 0 12px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-box:focus-within {
  border-color: #c5c5d2;
  box-shadow: 0 0 0 0 transparent, 0 0 20px rgba(0, 0, 0, 0.06);
}

.composer-textarea :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 14px 16px 6px;
  font-size: 14px;
  line-height: 1.55;
  background: transparent;
  resize: none;
}

.composer-textarea :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px 10px;
}

.toolbar-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.pill-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--agent-border);
  border-radius: 999px;
  background: var(--agent-surface);
  color: var(--agent-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.pill-btn:hover {
  background: var(--agent-primary-soft);
  border-color: var(--agent-primary-muted);
  color: var(--agent-primary);
}

.pill-select {
  flex-shrink: 0;
}

.pill-mode {
  width: 84px;
}

.pill-run {
  width: 76px;
}

.pill-provider {
  width: 110px;
}

.pill-select :deep(.el-select__wrapper) {
  min-height: 30px;
  height: 30px;
  padding: 0 22px 0 10px;
  border-radius: 999px;
  box-shadow: none !important;
  border: 1px solid var(--agent-border);
  background: var(--agent-surface);
  font-size: 12px;
}

.pill-select :deep(.el-select__wrapper:hover),
.pill-select :deep(.el-select__wrapper.is-focused) {
  border-color: var(--agent-primary-muted);
  background: var(--agent-primary-soft);
}

.pill-select :deep(.el-select__selection) {
  flex: 1;
  min-width: 0;
}

.pill-select :deep(.el-select__selected-item),
.pill-select :deep(.el-select__placeholder) {
  color: #374151;
  font-size: 12px;
  line-height: 28px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pill-select :deep(.el-select__suffix) {
  right: 6px;
}

.pill-select :deep(.el-select__caret) {
  font-size: 12px;
  color: #9ca3af;
}

.settings-popover {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #374151;
}

.toolbar-send {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.composer-status {
  font-size: 11px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-status.completed { color: #059669; }
.composer-status.cancelled,
.composer-status.waiting_plan,
.composer-status.waiting_approval { color: #d97706; }
.composer-status.failed,
.composer-status.error { color: #dc2626; }

.send-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 10px;
  background: #e5e7eb;
  color: #9ca3af;
  cursor: not-allowed;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s, transform 0.1s;
}

.send-btn.active {
  background: var(--agent-primary);
  color: #fff;
  cursor: pointer;
}

.send-btn.active:hover {
  background: #0d9488;
}

.send-btn.active:active {
  transform: scale(0.96);
}

.send-btn.loading {
  background: var(--agent-primary);
  color: #fff;
  cursor: wait;
}

.composer-hint {
  margin: 6px 4px 0;
  font-size: 11px;
  color: #9ca3af;
  line-height: 1.4;
}

/* ── Side panel ── */
.side-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 0;
  background: var(--agent-surface);
  border-left: 1px solid var(--agent-border);
}

.side-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.side-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 12px;
  border-bottom: 1px solid var(--agent-border);
  background: var(--agent-bg);
}

.side-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.side-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.side-scroll {
  height: 100%;
  overflow-y: auto;
  padding: 10px 12px 14px;
}

.side-empty {
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
  padding: 32px 12px;
}

/* Preview — 16:10 桌面浏览器视口 (1440×900) */
.preview-frame {
  width: 100%;
  aspect-ratio: 16 / 10;
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #334155;
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: top center;
  background: #0f172a;
}

.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: #6b7280;
  font-size: 13px;
}

.preview-empty small {
  font-size: 11px;
  color: #4b5563;
}

.meta-list {
  margin: 10px 0 0;
  font-size: 12px;
}

.meta-list dt {
  color: #9ca3af;
  font-size: 11px;
  margin-top: 8px;
}

.meta-list dt:first-child {
  margin-top: 0;
}

.meta-list dd {
  margin: 2px 0 0;
  color: #374151;
  line-height: 1.45;
}

.url-text {
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: #6b7280;
}

.agent-meta-card {
  margin-top: 10px;
  border: 1px solid var(--agent-border);
  border-radius: 8px;
  padding: 8px;
  background: #ffffff;
}

.agent-meta-title {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 6px;
}

.agent-meta-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 11px;
  margin-top: 5px;
}

.agent-meta-row span {
  width: 64px;
  color: #6b7280;
  flex: none;
}

.agent-meta-row code {
  color: #374151;
  white-space: normal;
  word-break: break-word;
}

/* Steps — single line */
.step-item {
  border-radius: 6px;
  margin-bottom: 3px;
  overflow: hidden;
  background: var(--agent-bg);
}

.step-item.running { background: var(--agent-primary-soft); }
.step-item.error { background: #fef2f2; }
.step-item.done { background: #ecfdf5; }
.step-item.open { background: var(--agent-bg); border: 1px solid var(--agent-border); }

.step-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  cursor: pointer;
  user-select: none;
  min-height: 28px;
}

.step-head:hover {
  background: rgba(0, 0, 0, 0.03);
}

.step-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--agent-primary);
}

.step-item.done .step-dot { background: #10b981; }
.step-item.error .step-dot { background: #ef4444; }
.step-item.running .step-dot {
  background: var(--agent-primary);
  animation: pulse 1s infinite;
}

.step-line {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  line-height: 1;
  overflow: hidden;
}

.step-num {
  flex-shrink: 0;
  color: #9ca3af;
  font-weight: 600;
  font-size: 10px;
}

.step-tool {
  flex-shrink: 0;
  font-size: 10px;
  background: #e5e7eb;
  padding: 1px 5px;
  border-radius: 3px;
  color: #374151;
}

.step-sep {
  flex-shrink: 0;
  color: #d1d5db;
}

.step-summary {
  flex: 1;
  min-width: 0;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-tag {
  flex-shrink: 0;
  transform: scale(0.85);
  transform-origin: center;
}

.step-chevron {
  flex-shrink: 0;
  font-size: 12px;
  color: #c4c4c4;
  transition: transform 0.2s;
}

.step-chevron.open {
  transform: rotate(180deg);
}

.step-json {
  margin: 0;
  border-top: 1px solid #f0f0f0;
  border-radius: 0;
  max-height: 140px;
}

/* Checkpoints — single line */
.cp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.cp-hint {
  font-size: 10px;
  color: #9ca3af;
}

.cp-item {
  border-radius: 6px;
  margin-bottom: 3px;
  background: var(--agent-bg);
}

.cp-item.open {
  background: var(--agent-bg);
  border: 1px solid var(--agent-border);
}

.cp-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px 5px 8px;
  cursor: pointer;
  min-height: 28px;
}

.cp-head:hover {
  background: rgba(0, 0, 0, 0.03);
}

.cp-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d1d5db;
}

.cp-line {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  overflow: hidden;
}

.cp-num {
  flex-shrink: 0;
  color: #9ca3af;
  font-weight: 600;
  font-size: 10px;
}

.cp-tool {
  flex-shrink: 0;
  font-size: 10px;
  background: #e5e7eb;
  padding: 1px 5px;
  border-radius: 3px;
}

.cp-sep {
  flex-shrink: 0;
  color: #d1d5db;
}

.cp-title-inline {
  flex: 1;
  min-width: 0;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cp-restore {
  flex-shrink: 0;
  font-size: 11px;
  padding: 0 4px;
}

.cp-chevron {
  flex-shrink: 0;
  font-size: 12px;
  color: #c4c4c4;
  transition: transform 0.2s;
}

.cp-chevron.open {
  transform: rotate(180deg);
}

.cp-detail {
  padding: 6px 10px 8px 20px;
  border-top: 1px solid #f0f0f0;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.45;
}

.cp-detail p {
  margin: 0 0 4px;
}

.cp-url {
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  color: #9ca3af;
}

/* ── Drawers / dialogs (unchanged helpers) ── */
.field-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #888;
}

.skills-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.skills-hint {
  margin-top: 12px;
  font-size: 12px;
  color: #888;
}

.experience-detail {
  margin-top: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.experience-detail h4 {
  margin: 0 0 8px;
  font-size: 14px;
}

.experience-detail ul {
  margin: 6px 0 12px;
  padding-left: 18px;
}

.skill-tag {
  margin-left: 6px;
  vertical-align: middle;
}

.import-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.import-preview,
.record-preview {
  margin-top: 10px;
  padding: 10px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}

.import-meta {
  margin-top: 10px;
  font-size: 13px;
  color: #666;
}

@media (max-width: 1200px) {
  .workspace {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
}

@media (max-width: 960px) {
  .mobile-sidebar-toggle {
    display: inline-flex;
  }

  .history-sidebar {
    position: absolute;
    z-index: 20;
    height: 100vh;
    box-shadow: 4px 0 24px rgba(15, 118, 110, 0.12);
  }

  .history-sidebar.collapsed {
    width: 0;
    border: none;
    overflow: hidden;
  }

  .workspace {
    grid-template-columns: 1fr;
  }

  .side-panel {
    display: none;
  }
}
</style>
