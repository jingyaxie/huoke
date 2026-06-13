# 抖音热点监控分析平台

基于 `Python 3.12 + FastAPI + SQLAlchemy + Playwright + MySQL8 + Vue3 + Element Plus + Docker Compose` 的热点监控系统，支持抖音热榜抓取、趋势分析、AI 日报生成、PDF 导出。

## 功能覆盖

1. Playwright 自动登录抖音网页版（扫码登录）
2. Cookie 持久化（`storage/douyin/storage_state.json`）
3. 每日定时抓取热榜前 100
4. 保存标题、作者、点赞、评论、分享、发布时间
5. 记录每日排名变化
6. REST API
7. Vue 后台管理系统
8. 热门视频排行
9. 热门作者排行
10. 趋势图（ECharts）
11. 对接 OpenAI / DeepSeek
12. 自动热点日报
13. PDF 导出
14. Docker Compose 一键部署
15. 完整 README
16. 数据库初始化 SQL
17. Repository 模式
18. Alembic 迁移
19. 单元测试
20. `.env` 配置

## Skill 统一架构（2026-06）

业务能力统一通过 **Skill** 暴露，REST / Agent / Pipeline 共用 `SkillRunnerService`：

| 入口 | 说明 |
|------|------|
| `POST /api/agent/skills/execute` | 直接执行任意 Skill |
| `POST /api/platforms/{platform}/...` | 平台 REST（内部适配为 Skill） |
| `POST /api/agent/pipeline/keyword-video-comments` | 对外 Pipeline（`pipeline-keyword-video-comments`） |
| Agent 对话 `/skill-id` | invoke_skill 与上述同源 |

核心 Skill：`douyin-keyword-comments`、`xhs-keyword-comments`、`follow-user`、`send-dm`、`pipeline-keyword-video-comments`。  
Skill 定义：`backend/storage/skills/global.json`。

## 目录结构

```text
.
├── backend
│   ├── app
│   │   ├── api
│   │   ├── core
│   │   ├── crawler
│   │   ├── db
│   │   ├── models
│   │   ├── repositories
│   │   ├── schemas
│   │   └── services
│   ├── alembic
│   ├── sql/init.sql
│   └── tests
├── frontend
└── docker-compose.yml
```

## 本地开发（Mac，系统 Chrome）

Docker 容器内只能使用 Playwright 内置 Chromium，**无法调用 macOS 系统浏览器**。本地测试请用宿主机跑后端 + 系统 Chrome：

### 1) 配置

```bash
cp .env.local.example .env.local
# 编辑 .env.local，填入 DEEPSEEK_API_KEY 等密钥
```

关键项：

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 指向 `127.0.0.1:3306`（非 Docker 内 `mysql` 主机名） |
| `ANTIBOT_BROWSER_CHANNEL=chrome` | 使用本机 Google Chrome |
| `ANTIBOT_PLAYWRIGHT_FALLBACK=false` | 禁止回退 Playwright Chromium |
| `AGENT_HEADLESS=false` | Agent 可见浏览器窗口 |

需已安装 [Google Chrome](https://www.google.com/chrome/)。

### 2) 一键启动

```bash
chmod +x scripts/dev-local.sh
docker compose -f docker-compose.local.yml up -d frontend   # 可选：前端容器
./scripts/dev-local.sh
```

`dev-local.sh` 会：启动 MySQL 容器 → 创建/激活 venv → 迁移数据库 → 用系统 Chrome 启动后端。

### 3) 手动分步（可选）

```bash
docker compose -f docker-compose.local.yml up -d mysql
cd backend && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端地址：`http://localhost:5173`  
后端地址：`http://localhost:8000`  
API 文档：`http://localhost:8000/docs`

> **注意**：`docker compose up`（含 backend 服务）仍会走容器内 Chromium + VNC，仅适用于 Linux 服务器或无 Chrome 的环境。

## Linux 服务器部署

```bash
docker compose up -d --build
```

说明：上面适合生产镜像部署。开发阶段建议使用热更新模式（见下方）。

### 增量更新（推荐）

避免每次都全量重建，按改动范围更新：

```bash
# 仅改前端代码（Vue 页面/API 调用）
docker compose up -d --no-deps frontend

# 仅改后端代码（Python 业务逻辑）
docker compose up -d --no-deps backend

# 仅重启，不重建镜像
docker compose restart frontend
docker compose restart backend
```

只有在以下情况才建议 `--build`：

1. 修改了 `backend/requirements.txt`
2. 修改了 `frontend/package.json` / `package-lock.json`
3. 修改了 Dockerfile 或系统级依赖

### 后端双镜像分层（依赖层 + 业务层）

后端拆为两层镜像，发布脚本会**按需**构建/上传：

| 镜像 | 内容 | 何时重建/上传 |
|------|------|----------------|
| `douyin-backend-base:py312` | apt + pip + Playwright | `requirements.txt` / `Dockerfile` 变更 |
| `douyin-backend-app:latest` | 仅业务代码 | 每次发版（秒级 build） |

本地手动构建：

```bash
# 首次或依赖变更：构建依赖层（慢，约 10–20 分钟）
docker compose --profile build build backend_base
# 或
./scripts/build_prod_images_local.sh backend-base

# 日常发版：只打业务层（快，约 10–30 秒）
BUILD_BACKEND_BASE=0 ./scripts/build_prod_images_local.sh backend-app
docker compose build backend   # 本地 dev 同样走 Dockerfile.app 逻辑
```

**BuildKit 本地缓存**：构建缓存写入 `.docker-build-cache/`（已 gitignore），重复 build 时 pip/apt/playwright 不会从零下载。

**上传优化**：`deploy_local_images.sh` 会对比服务器镜像 ID，未变化则跳过上传；依赖层未变更时不上传 base 镜像。

推荐发版：

```bash
./scripts/deploy_local_images.sh   # 自动：依赖未变则只 build/push 业务层
```

说明：`docker save | ssh docker load` 仍会传输 tar 流；若服务器已有相同 layer，load 时会跳过写入，但网络传输量仍偏大。后续可接私有镜像仓库实现真正的增量 push。

### 开发模式（改完自动生效）

默认 `frontend` 服务已改为 Vite 开发模式，代码改动会自动热更新，不需要重建镜像：

```bash
docker compose up -d mysql backend frontend
```

前端地址：`http://localhost:5173`

如需生产前端镜像（Nginx 静态文件），使用 `frontend_prod`：

```bash
docker compose --profile prod up -d --build frontend_prod
```

生产前端地址：`http://localhost:5174`

### 服务器发布脚本（仅更新当前项目 backend）

新增脚本：

- `scripts/deploy_backend_prod.sh`
- `scripts/lib/load_deploy_env.sh`
- `.env.deploy.example`

使用步骤：

```bash
cp .env.deploy.example .env.deploy.local
# 填写 PROD_SSH_HOST / PROD_SSH_USER / PROD_SSH_PASSWORD

# 发布（默认 auto：只 rsync + 重启，不打包不上传）
./scripts/deploy_backend_prod.sh

# 或显式快速发版（推荐）
./scripts/deploy_fast.sh

# 仅首次部署 / requirements.txt 变更后（本地打镜像上传）
./scripts/deploy_local_images.sh

# 在服务器全量重建镜像
./scripts/deploy_full.sh
```

发布模式说明：

| 命令 | 何时用 | 耗时 |
|------|--------|------|
| `deploy_fast.sh` / `--fast` / `--auto`（业务代码） | **日常发版**，rsync + 重启 | ~1–3 分钟 |
| `deploy_local_images.sh` | 首次部署或 `requirements.txt` 变更 | 视网络 |
| `deploy_full.sh` / `--full` | 在服务器重建镜像 | ~10–30 分钟 |

兼容旧环境变量：`SKIP_BUILD=1` 等同 `--fast`。

## 抖音登录与抓取

1. 将 `.env` 中 `DOUYIN_HEADLESS=false`
2. 调用 `POST /api/douyin/login`，浏览器打开后扫码登录
3. 登录成功后会保存 Cookie
4. 再把 `DOUYIN_HEADLESS=true`，调用 `POST /api/crawl/hot`

## 关键 API

- `GET /api/health`
- `POST /api/douyin/login`
- `POST /api/crawl/hot?limit=100`
- `GET /api/hot/videos`
- `GET /api/hot/authors`
- `GET /api/videos/{video_id}/trend?days=30`
- `GET /api/overview`
- `POST /api/reports/daily?provider=template|openai|deepseek`
- `GET /api/reports`
- `GET /api/reports/{report_date}/pdf`

## AI 日报

在 `.env` 填入：

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`

即可通过 `provider` 切换模型。

## 测试

```bash
cd backend
pytest
```

## 注意事项

1. 抖音页面结构可能变动，`backend/app/services/douyin_crawler.py` 中选择器可按需调整。
2. 生产建议将 MySQL、API Key、跨域域名改为实际值。
3. 如果服务器无图形环境，首次扫码可在开发机生成 Cookie 再同步 `storage_state.json`。
