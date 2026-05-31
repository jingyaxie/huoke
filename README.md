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

