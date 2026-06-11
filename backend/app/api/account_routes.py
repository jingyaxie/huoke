from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_authenticated_tenant_id
from app.core.antibot import LoginRequiredError
from app.core.config import Settings, get_settings
from app.platforms.account_id import normalize_account_id
from app.platforms.constants import BINDABLE_PLATFORMS, PLATFORM_LABELS
from app.platforms.registry import get_session_store
from app.schemas.account_dashboard import AccountDashboardRequest, AccountDashboardResponse
from app.schemas.qr_login import QrLoginCreateRequest, QrLoginCreateResponse, QrLoginStatusResponse
from app.schemas.platform_account import (
    PlatformAccountBindingsOut,
    PlatformAccountCreate,
    PlatformAccountListResponse,
    PlatformAccountOut,
    UploadAccountStorageStateRequest,
)
from app.services.account_dashboard_service import AccountDashboardService
from app.services.qr_login_service import QrLoginService
from app.services.platform_account_store import PlatformAccountStore


router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _store(settings: Settings = Depends(get_settings)) -> PlatformAccountStore:
    return PlatformAccountStore(settings)


@router.get("/platforms/supported")
def list_bindable_platforms() -> dict:
    return {
        "items": [
            {"id": pid, "label": PLATFORM_LABELS.get(pid, pid)}
            for pid in sorted(BINDABLE_PLATFORMS)
        ]
    }


@router.get("", response_model=PlatformAccountListResponse)
def list_accounts(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> PlatformAccountListResponse:
    items = store.list_accounts(tenant_id)
    return PlatformAccountListResponse(
        items=items,
        total=len(items),
        active_account_id=store.get_active_account_id(tenant_id),
    )


@router.post("", response_model=PlatformAccountOut)
def create_account(
    payload: PlatformAccountCreate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> PlatformAccountOut:
    try:
        return store.create_account(tenant_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/active/{account_id}")
def set_active_account(
    account_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> dict[str, str]:
    try:
        active = store.set_active_account(tenant_id, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    return {"active_account_id": active}


@router.delete("/{account_id}")
def delete_account(
    account_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> dict[str, bool]:
    try:
        deleted = store.delete_account(tenant_id, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"deleted": True}


@router.get("/{account_id}/bindings", response_model=PlatformAccountBindingsOut)
def get_account_bindings(
    account_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> PlatformAccountBindingsOut:
    account = store.get_account(tenant_id, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return PlatformAccountBindingsOut(
        account_id=account.id,
        label=account.label,
        platforms=store.platform_bindings(tenant_id, account.id),
    )


@router.get("/{account_id}/platforms/{platform}/login-status")
def account_platform_login_status(
    account_id: str,
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
    store: PlatformAccountStore = Depends(_store),
) -> dict:
    platform = platform.strip().lower()
    if platform not in BINDABLE_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if store.get_account(tenant_id, account_id) is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    session_store = get_session_store(settings, platform)
    return session_store.login_status(tenant_id, normalize_account_id(account_id))


@router.post("/{account_id}/platforms/{platform}/server-login")
async def account_platform_server_login(
    account_id: str,
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> dict:
    try:
        return await store.start_server_login(tenant_id, platform, account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{account_id}/platforms/{platform}/dashboard",
    response_model=AccountDashboardResponse,
    summary="已登录账号主页监控",
)
async def fetch_account_dashboard(
    account_id: str,
    platform: str,
    payload: AccountDashboardRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> AccountDashboardResponse:
    platform = platform.strip().lower()
    if platform not in BINDABLE_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if store.get_account(tenant_id, account_id) is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    service = AccountDashboardService(tenant_id=tenant_id, account_id=normalize_account_id(account_id))
    try:
        result, output = await service.fetch_dashboard(
            platform,
            show_browser=payload.show_browser,
            works_limit=payload.works_limit,
        )
    except LoginRequiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = {
        "account": result.get("account") or {},
        "notifications": result.get("notifications") or {},
        "im": result.get("im") or {},
        "works": result.get("works") or [],
        "works_count": len(result.get("works") or []),
        "capture_method": result.get("capture_method"),
        "works_limit": result.get("works_limit"),
        "logged_in": result.get("logged_in"),
        "profile_url": result.get("profile_url"),
    }
    return AccountDashboardResponse(
        ok=bool(result.get("ok")),
        platform=platform,
        tenant_id=tenant_id,
        account_id=normalize_account_id(account_id),
        data=data,
        diagnostic=result.get("diagnostic"),
        report_file=str(output),
    )


@router.post(
    "/{account_id}/platforms/{platform}/qr-login",
    response_model=QrLoginCreateResponse,
    summary="获取平台登录二维码（可远程扫码）",
)
async def create_platform_qr_login(
    account_id: str,
    platform: str,
    payload: QrLoginCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> QrLoginCreateResponse:
    platform = platform.strip().lower()
    if platform not in BINDABLE_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if store.get_account(tenant_id, account_id) is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    service = QrLoginService(tenant_id=tenant_id, account_id=normalize_account_id(account_id))
    try:
        session = await service.create_qr_login(platform, refresh=payload.refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = service.session_payload(session)
    return QrLoginCreateResponse(
        ok=bool(data.get("ok")),
        platform=platform,
        tenant_id=tenant_id,
        account_id=normalize_account_id(account_id),
        session_id=session.session_id,
        status=session.status,
        qr_image_url=session.qr_image_url,
        qr_image_base64=session.qr_image_base64,
        qr_scan_url=session.qr_scan_url,
        expires_at=data.get("expires_at"),
        expires_in_seconds=data.get("expires_in_seconds"),
        validity_hint=session.validity_hint,
        poll_interval_seconds=2,
        diagnostic=session.message,
    )


@router.get(
    "/{account_id}/platforms/{platform}/qr-login/{session_id}",
    response_model=QrLoginStatusResponse,
    summary="轮询二维码登录状态",
)
async def get_platform_qr_login_status(
    account_id: str,
    platform: str,
    session_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> QrLoginStatusResponse:
    platform = platform.strip().lower()
    if platform not in BINDABLE_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if store.get_account(tenant_id, account_id) is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    service = QrLoginService(tenant_id=tenant_id, account_id=normalize_account_id(account_id))
    try:
        session = await service.get_status(platform, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    data = service.session_payload(session, include_login=True)
    return QrLoginStatusResponse(
        ok=bool(data.get("ok")),
        platform=platform,
        tenant_id=tenant_id,
        account_id=normalize_account_id(account_id),
        session_id=session.session_id,
        status=session.status,
        expires_at=data.get("expires_at"),
        expires_in_seconds=data.get("expires_in_seconds"),
        validity_hint=session.validity_hint,
        poll_interval_seconds=2,
        message=session.message,
        login_ready=bool(data.get("login_ready")),
        login_status=data.get("login_status"),
    )


@router.delete(
    "/{account_id}/platforms/{platform}/qr-login/{session_id}",
    summary="取消二维码登录会话",
)
async def cancel_platform_qr_login(
    account_id: str,
    platform: str,
    session_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> dict:
    platform = platform.strip().lower()
    if platform not in BINDABLE_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if store.get_account(tenant_id, account_id) is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    service = QrLoginService(tenant_id=tenant_id, account_id=normalize_account_id(account_id))
    try:
        cancelled = await service.cancel(platform, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"cancelled": cancelled}


@router.put("/{account_id}/platforms/{platform}/storage-state")
def account_upload_storage_state(
    account_id: str,
    platform: str,
    payload: UploadAccountStorageStateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: PlatformAccountStore = Depends(_store),
) -> dict:
    try:
        return store.upload_storage_state(tenant_id, platform, account_id, payload.storage_state)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
