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
from app.api.preset_routes import router as preset_router
from app.api.platform_routes import router as platform_router
from app.api.tenant_routes import router as tenant_router
from app.api.user_routes import router as user_router
from app.api.v1_routes import router
from app.api.settings_routes import router as settings_router
from app.api.v3_tikhub_compat_routes import router as v3_compat_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.bootstrap import ensure_database_schema
from app.db.session import SessionLocal
from app.models import *  # noqa: F401,F403
from app.services.agent_browser_session import AgentSessionManager
from app.services.playwright_pool import PlaywrightPool
from app.services.agent_async_job_service import AgentAsyncJobService
from app.services.bootstrap_service import ensure_bootstrap_admin
from app.services.font_bootstrap import ensure_cjk_fonts
from app.services.tenant_auth_service import TenantAuthService
from app.desktop_static import mount_desktop_frontend


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    ensure_database_schema()
    session = SessionLocal()
    try:
        if ensure_bootstrap_admin(session, settings):
            session.commit()
        auth = TenantAuthService(session, settings)
        for tenant_id in ("default", "t1", "aisales_global_vnc"):
            auth.ensure_api_key(tenant_id, settings.huoke_bridge_secret, label="aisales-bridge")
        if settings.tenant_bootstrap_api_keys:
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
    AgentAsyncJobService.get(settings)._ensure_workers()

    yield
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
app.include_router(settings_router)
app.include_router(preset_router)
app.include_router(agent_ws_router)
app.include_router(v3_compat_router)

if settings.desktop_mode:
    mount_desktop_frontend(app, settings.frontend_dist_dir)
