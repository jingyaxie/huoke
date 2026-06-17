# Huoke 对外 API 契约

本文档描述 **当前在用的** Huoke 对外集成接口。管理后台「API 文档」页与本文档保持一致。

## 鉴权

请求头（租户 API Key 或用户 JWT 二选一，集成场景用 API Key）：

| Header | 说明 |
|--------|------|
| `X-Tenant-Id` | 租户 ID |
| `X-Platform-Id` | `douyin` / `xiaohongshu` / `kuaishou` |
| `X-Account-Id` | 平台账号 ID，默认 `default` |
| `X-API-Key` | 租户 API Key（启用鉴权时必填） |

管理员创建 Key：`POST /api/admin/tenant-keys`（Header `X-Admin-Secret`）。

---

## 1. 外部获客任务（推荐）

### 1.1 查询能力

`GET /api/agent/external/capabilities`

返回 `huoke.external_task.v1`：支持的 `intent`、`scope_fields`、`field_options`、`sync_schema`。

Intent 与 AISales 任务类型映射：

| intent | AISales type | 说明 |
|--------|--------------|------|
| `keyword_auto` | `home_auto` | 关键词自动获客 |
| `single_video` | `video_manual` | 单视频手动获客 |
| `account_home` | `home_manual` | 账号主页手动获客 |

### 1.2 创建任务

`POST /api/agent/external/jobs`

```json
{
  "intent": "single_video",
  "name": "单视频测试",
  "platform": "douyin",
  "scope": {
    "input_url": "https://www.douyin.com/video/123",
    "comment_days": 5,
    "publish_time_range": "7d"
  },
  "outreach": {
    "constraints": {
      "comment_dm_interval_seconds_min": 30,
      "follow_per_day": 10
    }
  },
  "evaluation": {
    "target_customer": "本地准备装修的业主",
    "accept_description": "询价、预约量房",
    "reject_signals": ["同行", "招聘"]
  },
  "correlation": {
    "external_system": "aisales",
    "external_task_id": "lead-task-uuid",
    "idempotency_key": "optional"
  },
  "auto_execute": true,
  "webhook_url": "https://example.com/api/huoke-agent-bridge/callbacks/jobs"
}
```

Huoke 内部完成：`publish_time_range` → `video_publish_days`、constraints 别名归一、message 生成、brief 补全、**evaluation → lead_evaluation spec 编译冻结**。

创建时可传 `evaluation`（用户草稿）；Huoke 编译为 `huoke.lead_evaluation.v1` 并写入 `task_brief.constraints.lead_evaluation`。

### 1.3 查询任务

`GET /api/agent/jobs/{job_id}`

响应含 `sync` 字段（schema `huoke.agent_job_sync.v1`）：

```json
{
  "job_id": "...",
  "status": "running",
  "sync": {
    "schema": "huoke.agent_job_sync.v1",
    "event": "job.snapshot",
    "job": { "job_id": "...", "platform": "douyin", "status": "running" },
    "progress": {
      "target_leads": 80,
      "leads_collected": 12,
      "comments_captured": 60,
      "comments_evaluated": 55,
      "leads_qualified": 12
    },
    "lead_evaluation": {
      "schema": "huoke.lead_evaluation.v1",
      "source": "auto_generated",
      "criteria": {
        "accept_description": "评论者在咨询价格、预约或留下联系方式",
        "reject_description": "同行广告、招聘、纯玩梗"
      },
      "thresholds": { "precise": 0.72, "outreach": 0.55 },
      "spec_hash": "sha256:..."
    },
    "stats": { "leads_total": 12, "outreach_total": 5 },
    "leads": [],
    "outreach_events": [],
    "correlation": {
      "external_system": "aisales",
      "external_task_id": "lead-task-uuid"
    }
  }
}
```

### 1.4 取消任务

`POST /api/agent/jobs/{job_id}/cancel`

---

## 2. Webhook 同步

Huoke 在终态或计划挂起时向 `webhook_url` POST 与 snapshot 相同 schema 的 payload。

签名 Header：

- `X-Huoke-Sync-Schema: huoke.agent_job_sync.v1`
- `X-Huoke-Sync-Timestamp: <unix seconds>`
- `X-Huoke-Sync-Signature: sha256=<hmac>`

签名字符串：`<timestamp>.<json-body>`（JSON 使用 sorted keys、紧凑分隔符）。密钥为 `HUOKE_BRIDGE_SECRET`。

---

## 3. 关键词 Pipeline（线索来源）

`POST /api/agent/pipeline/keyword-video-comments`

按关键词搜索视频/笔记并抓取评论。PC 客户端【线索来源】使用此接口；`async_job=true` 时返回 `job_id`，轮询 `GET /api/agent/jobs/{job_id}`。

```json
{
  "keyword": "淋浴房",
  "platforms": ["douyin", "xiaohongshu"],
  "video_limit": 5,
  "region": "辽宁",
  "days": 3,
  "async_job": true,
  "force_refresh": false,
  "cache_ttl_hours": 24
}
```

缓存：默认 24h TTL；`force_refresh=true` 跳过缓存。响应含 `cache.from_cache` / `cache.cache_hit`。

---

## 4. 内容库

Pipeline 或 Agent 抓取入库后，通过内容库读取结构化数据：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/platforms/{platform}/contents` | 列表，`offset` / `limit` / `updated_after` |
| GET | `/api/platforms/{platform}/contents/{content_id}` | 详情，可选 `max_comments` |

---

## 5. Skill 执行

`POST /api/agent/skills/execute` — 同步执行单个 Skill（搜索、抓评、关注、私信等）。

```json
{
  "skill_id": "douyin-keyword-comments",
  "platform": "douyin",
  "params": { "keyword": "护肤", "limit": 3, "days": 3 },
  "timeout_seconds": 600
}
```

---

## 6. AISales Bridge 代理

外层 AISales 后端对外暴露（内部转发至 Huoke `external/*`）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/huoke-agent-bridge/capabilities` | 能力定义（Huoke 不可用时回退静态） |
| POST | `/api/huoke-agent-bridge/tasks` | 创建任务 + 本地 LeadTask |
| GET | `/api/huoke-agent-bridge/tasks/{task_id}` | 查询本地任务 |
| POST | `/api/huoke-agent-bridge/callbacks/jobs` | 接收 webhook |

PC 客户端统一走 `POST /api/lead-tasks`；`config.execution=huoke_agent` 时后端内部分流到 Bridge。

---

## 7. 基础

- `GET /api/health` — 健康检查

---

## 已废弃（勿在新集成中使用）

以下路径仍可能在服务端存在，但**不再对外文档化**，新代码请勿依赖：

| 路径 | 替代方案 |
|------|----------|
| `POST /api/agent/jobs`（message + flat config） | `POST /api/agent/external/jobs` |
| `POST /api/platforms/{platform}/search/*` 等平台工具 REST | `POST /api/agent/skills/execute` |
| `GET /api/agent/skills/builtin-handlers` | 内部调试，集成无需 |
| `GET /api/comments/download` | 使用内容库 API |
| `/api/v3/tikhub-compat/*` | AISales 内部兼容层，非 Huoke 对外契约 |
| `/api/lead-automation/*`、`/api/lead-filter-rules/*` | 社媒旧版 RPA API，生产 410；请用 PC + Huoke Bridge |

---

## 附录 A：AISales 侧数据映射（Bridge sync 落库）

### A.1 `LeadTask.config_json`（社媒 Huoke 任务）

| 字段 | 来源 | 说明 |
|------|------|------|
| `execution` | PC 创建时固定 | 恒为 `huoke_agent` |
| `lead_evaluation` | sync webhook 或 Huoke 创建响应 | 编译后的识别 spec，`schema=huoke.lead_evaluation.v1` |
| `comment_presets` / `dm_presets` | 创建任务时 attach | 评论/私信话术快照，供 Huoke outreach 随机抽取 |
| `huoke_agent` | Bridge 创建后写入 | 含 `job_id`、`remote_status` 等远端关联 |

创建时 PC 可提交 `lead_evaluation` 草稿（模板 + accept/reject 条件）；Huoke 编译后通过 sync 回写完整 spec。

### A.2 `LeadItem` 与 evaluation

| 字段 | 来源 | 说明 |
|------|------|------|
| `precise_score` | sync `leads[].match_score` 或 evaluation 结果 | 与 spec 阈值比较判定精准 |
| `status` | sync + 阈值 | `precise` / `qualified` 等 |
| `raw_json.lead_evaluation` | sync 逐条 evaluation | 单条线索的评估详情（若有） |

精准/触达门槛从 `config.lead_evaluation.thresholds` 读取（默认 precise `0.72`、outreach `0.55`）。

### A.3 sync `progress` → `LeadTask` 列

| webhook `progress` | `LeadTask` 列 | 说明 |
|--------------------|---------------|------|
| `leads_collected` | `progress_total` | 累计线索数 |
| `leads_qualified` | `progress_precise` | 精准/合格线索数 |
| `comments_captured` / `comments_evaluated` | `config` 或进度快照 | 抓评/评估进度（视 payload 版本） |
| `job.status` / `job.stage` | `status` / `workflow_stage` | 任务运行态 |

Huoke 触达结果经 sync `outreach_events` 写入 `OutreachActionLog`；PC「查看数据」读本地聚合，不再走旧 orchestrator/RPA 链。
