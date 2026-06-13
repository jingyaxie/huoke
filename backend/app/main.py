from contextlib import asynccontextmanager
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account_routes import router as account_router
from app.api.agent_routes import router as agent_router
from app.api.agent_ws_routes import router as agent_ws_router
from app.api.antibot_routes import router as antibot_router
from app.api.auth_routes import router as auth_router
from app.api.douyin_routes import router as douyin_router
from app.api.xiaohongshu_routes import router as xiaohongshu_router
from app.api.kuaishou_routes import router as kuaishou_router
from app.api.platform_routes import router as platform_router
from app.api.tenant_routes import router as tenant_router
from app.api.user_routes import router as user_router
from app.api.v1_routes import router
from app.task_platform.api.open_task_routes import router as open_task_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.services.agent_browser_session import AgentSessionManager
from app.services.playwright_pool import PlaywrightPool
from app.services.bootstrap_service import ensure_bootstrap_admin
from app.services.font_bootstrap import ensure_cjk_fonts
from app.services.tenant_auth_service import TenantAuthService
from app.desktop_static import mount_desktop_frontend
from app.task_platform import bootstrap_task_platform
from app.task_platform.services.task_runtime_service import TaskWorkerPool
from app.task_platform.services.task_scheduler_service import TaskSchedulerService


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    bootstrap_task_platform()
    TaskWorkerPool.get(settings).start()
    if not settings.desktop_mode:
        Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if ensure_bootstrap_admin(session, settings):
            session.commit()
        if settings.tenant_bootstrap_api_keys:
            auth = TenantAuthService(session, settings)
            for tenant_id, api_key in json.loads(settings.tenant_bootstrap_api_keys).items():
                auth.ensure_api_key(tenant_id, api_key)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    await AgentSessionManager.get_instance().sync_browser_render_epoch()
    await PlaywrightPool.get().sync_browser_render_epoch()
    await ensure_cjk_fonts()

    scheduler = TaskSchedulerService.get(settings)
    scheduler.start()
    await scheduler.dispatch_due_tasks()

    yield
    await scheduler.stop()
    await AgentSessionManager.get_instance().shutdown_all()
    await PlaywrightPool.get().shutdown()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

cors_origins = [settings.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"]
if settings.desktop_mode:
    cors_origins.extend(
        [
            f"http://127.0.0.1:{settings.desktop_port}",
            f"http://localhost:{settings.desktop_port}",
            "tauri://localhost",
        ]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(tenant_router)
app.include_router(platform_router)
app.include_router(douyin_router)
app.include_router(xiaohongshu_router)
app.include_router(kuaishou_router)
app.include_router(antibot_router)
app.include_router(account_router)
app.include_router(agent_router)
app.include_router(agent_ws_router)
app.include_router(open_task_router)

if settings.desktop_mode:
    mount_desktop_frontend(app, settings.frontend_dist_dir)
