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

## 本地开发（Mac M 系列）

### 1) 启动 MySQL（Docker）

```bash
docker compose up -d mysql
```

### 2) 启动后端

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3) 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://localhost:5173`  
后端地址：`http://localhost:8000`  
API 文档：`http://localhost:8000/docs`

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

后端已拆为两层镜像：

1. `douyin-backend-base:py312`：系统包 + Python 依赖 + Playwright Chromium
2. `douyin-backend-app:latest`：业务代码层

首次或依赖变更时：

```bash
docker compose --profile build build backend_base
docker compose build backend
docker compose up -d backend
```

仅改后端业务代码时（不改 `requirements.txt`）：

```bash
docker compose build backend
docker compose up -d --no-deps backend
```

### 关于“每次都在下载依赖”的说明

如果看到 backend 构建时反复执行 `playwright install chromium`，通常是因为触发了 backend 重新 build，而不是缓存完全失效。

建议：

1. 前端改动时只更新 frontend（`--no-deps frontend`），不要带动 backend 重建。
2. 后端仅代码改动时只更新 backend（`--no-deps backend`）。
3. 网络不稳定时，`playwright install chromium` 可能因 DNS/超时失败（如 `EAI_AGAIN`），此时先避免全量 rebuild，优先走增量更新。

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

# 发布（仅操作当前项目 compose 名称，不影响其他项目）
./scripts/deploy_backend_prod.sh
```

可选参数：

```bash
# 跳过远端 build，仅重启 backend（前提：镜像已存在）
SKIP_BUILD=1 ./scripts/deploy_backend_prod.sh
```

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
