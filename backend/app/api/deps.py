from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.platforms.constants import DEFAULT_PLATFORM
from app.platforms.registry import get_session_store
from app.platforms.session_store import PlatformSessionStore
from app.platforms.tenant import normalize_tenant_id
from app.platforms.types import normalize_platform
from app.services.tenant_auth_service import TenantAuthService


def db_session(session: Session = Depends(get_db)) -> Session:
    return session


def get_platform_id(
    x_platform_id: str | None = Header(default=None, alias="X-Platform-Id"),
    platform: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    raw = x_platform_id or platform or settings.default_platform
    try:
        return normalize_platform(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_path_platform_id(platform: str) -> str:
    try:
        return normalize_platform(platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_authenticated_tenant_id(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    tenant_id: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> str:
    if settings.tenant_auth_enabled:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="已启用租户鉴权，请提供 X-API-Key")
        resolved = TenantAuthService(session, settings).resolve_tenant(x_api_key)
        if not resolved:
            raise HTTPException(status_code=403, detail="无效的 API Key")
        return resolved

    raw = (x_tenant_id or tenant_id or settings.default_tenant_id).strip()
    try:
        return normalize_tenant_id(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_path_tenant_id(tenant_id: str) -> str:
    try:
        return normalize_tenant_id(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def require_path_tenant(
    path_tenant_id: str,
    authenticated_tenant_id: str,
    settings: Settings,
) -> str:
    tid = resolve_path_tenant_id(path_tenant_id)
    if settings.tenant_auth_enabled and tid != authenticated_tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该租户")
    return tid


def effective_tenant_id(
    authenticated_tenant_id: str,
    override: str | None,
    settings: Settings,
) -> str:
    if override:
        try:
            requested = normalize_tenant_id(override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if settings.tenant_auth_enabled and requested != authenticated_tenant_id:
            raise HTTPException(status_code=403, detail="无权代表其他租户操作")
        if not settings.tenant_auth_enabled:
            return requested
    return authenticated_tenant_id


def effective_platform_id(
    dep_platform_id: str,
    override: str | None,
) -> str:
    if override:
        try:
            return normalize_platform(override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dep_platform_id


def verify_admin_secret(
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_api_secret or x_admin_secret != settings.admin_api_secret:
        raise HTTPException(status_code=403, detail="Admin Secret 无效或未配置")


def platform_session_store(
    platform: str = Depends(get_platform_id),
    settings: Settings = Depends(get_settings),
) -> PlatformSessionStore:
    store = get_session_store(settings, platform)
    store.migrate_legacy_if_needed()
    return store


def douyin_session_store(settings: Settings = Depends(get_settings)) -> PlatformSessionStore:
    store = get_session_store(settings, DEFAULT_PLATFORM)
    store.migrate_legacy_if_needed()
    return store
