# 专用任务智能体架构

## 设计目标

| 角色 | 档案 ID | Skill 范围 | 经验存储 |
|------|---------|------------|----------|
| 通用 Chat 智能体 | `default` | 不强制白名单（可手动选档案/Skill） | `agent_sandboxes/default/...` + `experiences.json` |
| 任务专用智能体 | `task-{platform}-skill-flow` | TaskBrief 白名单 Skill（由 AgentStrategy 决定） | `agent_sandboxes/{profile_id}/skills/{skill_id}/page_experience.json` |

二者沙盒隔离：Chat 里积累的通用经验不会污染任务编排；任务中 `browser_remember_page` 与技能学习写入专用沙盒，供 Supervisor 后续轮次复用。

## 执行策略

当前任务只保留 skill-flow 路径。平台策略绑定 playbook + 专用档案 + 抓取 Skill：

| 策略 ID | 平台 | 档案 | 抓取 Skill | 模式 |
|---------|------|------|------------|------|
| `skill-flow-douyin` | douyin | `task-douyin-skill-flow` | `douyin-keyword-comments` | 页面搜索 + 评论采集 |
| `skill-flow-xiaohongshu` | xiaohongshu | `task-xiaohongshu-skill-flow` | `xhs-keyword-comments` | 页面搜索 + 评论采集 |
| `skill-flow-kuaishou` | kuaishou | `task-kuaishou-skill-flow` | `kuaishou-keyword-comments` | 页面搜索 + 评论采集 |

- 创建任务：`POST /api/agent/jobs` 传 `agent_strategy`；或 JSON message 内 `"agent_strategy": "skill-flow-douyin"`
- 列表：`GET /api/agent/strategies?platform=douyin`
- `TaskBrief.agent_strategy` / `goals.execution_mode` / `goals.inline_ui_outreach` 由 `_finalize_brief()` 写入
- 租户自定义档案优先于内置 strategy 模板（`AgentProfileStore.get()` 先查 tenant JSON）

## 调用链

```text
/tasks 创建任务
  -> build_orchestration_plan(agent_strategy=...)
       -> generate_task_brief() -> resolve_agent_strategy()
       -> _finalize_brief() -> build_allowed_skills(platform, strategy)
       -> DedicatedAgentService.attach_to_orchestration_plan()
            strategy_id + profile_id = task-{platform}-skill-flow
  -> AgentAsyncJob 保存 orchestration.dedicated_agent

Job 执行
  -> TaskSupervisorService(agent_profile_id=专用档案)
       -> skill_id_from_brief(brief, action)
       -> SkillRunner / SkillExecutor
            keyword-comments -> builtin crawl_keyword_comments

/agent Chat
  -> DedicatedAgentService.resolve_chat_profile_id()
       task-* 强制回退 default
  -> AgentService.run_chat(profile=default)
```

抖音当前抓取路径：

```text
TaskSupervisorService
  -> crawl_keyword
  -> douyin-keyword-comments
  -> crawl_keyword_comments
  -> CommentCrawlerService / DouyinCommentBackend
  -> DouyinSearchTool.keyword_search
  -> ui_search_only=true
  -> run_searchbar_keyword_search
```

任务计划会为抖音 skill-flow 写入：

```json
{
  "ui_search_only": true,
  "search_url_first": false
}
```

## Skill 类型

- `builtin`：Python 确定性 handler（`SkillExecutor`）
- `instruction`：SKILL.md，由 Agent 读指南执行
- `actions`：录制步骤回放

任务专用智能体只能 invoke 其档案 `skill_ids` 与 TaskBrief `allowed_skills` 交集；Supervisor 战术动作通过 `task_skill_playbook.py` 映射到 skill_id。

## 经验学习

1. 技能学习页 `/tasks/learn`：人类操作 -> `human_observe/*.jsonl` -> 总结写入 `task-{platform}-skill-flow` 的 `page_experience.json`
2. 任务执行中：Agent `browser_remember_page` 写入同一专用沙盒
3. 做梦经验 `experiences.json`：仍主要服务 Chat；任务专用档案 `inherit_experience_prompt=false`

## 代码入口

| 模块 | 职责 |
|------|------|
| `app/services/agent_strategy/` | 内置策略注册表、playbook 绑定 |
| `app/services/dedicated_agent/` | 通用/专用边界、计划绑定、经验 Store 工厂 |
| `app/services/agent_profile_store.py` | `task_agent_profile_from_strategy()`；租户档案优先 |
| `app/services/task_skill_playbook.py` | Supervisor 动作 -> Skill；按 strategy 选 crawl skill |
| `app/services/agent_job_plan_service.py` | 创建任务时绑定 `dedicated_agent` |
| `app/services/task_supervisor_service.py` | 执行时传递 `agent_profile_id` |
| `app/services/ui_flow/platforms/*/*_ui.py` | 搜索/浏览/Feed 侧栏等可复用 DOM 工具 |

已删除：历史状态机、独立 UI 代理档案、旧快速抓取策略、旧模拟触达模式。

## 平台状态

| 平台 | 默认策略 | 专用档案 |
|------|----------|----------|
| douyin | `skill-flow-douyin` | `task-douyin-skill-flow` |
| xiaohongshu | `skill-flow-xiaohongshu` | `task-xiaohongshu-skill-flow` |
| kuaishou | `skill-flow-kuaishou` | `task-kuaishou-skill-flow` |
