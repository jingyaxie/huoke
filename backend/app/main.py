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
from app.api.platform_routes import router as platform_router
from app.api.tenant_routes import router as tenant_router
from app.api.user_routes import router as user_router
from app.api.v1_routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.services.crawl_service import CrawlService
from app.services.agent_browser_session import AgentSessionManager
from app.services.playwright_pool import PlaywrightPool
from app.services.scheduler import build_scheduler
from app.services.tenant_auth_service import TenantAuthService


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if settings.tenant_bootstrap_api_keys:
            auth = TenantAuthService(session, settings)
            for tenant_id, api_key in json.loads(settings.tenant_bootstrap_api_keys).items():
                auth.ensure_api_key(tenant_id, api_key)
            session.commit()
    finally:
        session.close()

    async def scheduled_crawl() -> None:
        session = SessionLocal()
        try:
            await CrawlService(
                session,
                tenant_id=settings.default_tenant_id,
                platform=settings.default_platform,
            ).crawl_hot(limit=100)
        finally:
            session.close()

    scheduler = build_scheduler(settings, scheduled_crawl)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)
    await AgentSessionManager.get_instance().shutdown_all()
    await PlaywrightPool.get().shutdown()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"],
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
app.include_router(antibot_router)
app.include_router(account_router)
app.include_router(agent_router)
app.include_router(agent_ws_router)
