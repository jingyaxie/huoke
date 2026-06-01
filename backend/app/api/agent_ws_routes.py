from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.platforms.account_id import normalize_account_id
from app.platforms.tenant import normalize_tenant_id
from app.platforms.types import normalize_platform
from app.services.agent_service import AgentService
from app.services.tenant_auth_service import TenantAuthService
from app.services.user_auth_service import UserAuthError, UserAuthService

router = APIRouter(prefix="/api/agent", tags=["agent-ws"])


def _resolve_ws_tenant_id(
    *,
    tenant_id: str | None,
    api_key: str | None,
    token: str | None,
) -> str:
    settings = get_settings()
    if token:
        session = SessionLocal()
        try:
            auth = UserAuthService(session, settings)
            payload = auth.decode_access_token(token)
            user = auth.get_user_by_id(int(payload["sub"]))
            if user is None or not user.is_active:
                raise PermissionError("登录用户无效或已禁用")
            return user.tenant_id
        except (UserAuthError, ValueError, KeyError) as exc:
            raise PermissionError("无效或已过期的登录令牌") from exc
        finally:
            session.close()

    if settings.tenant_auth_enabled:
        if not api_key:
            raise PermissionError("已启用租户鉴权，WebSocket 请提供 token 或 api_key 参数")
        session = SessionLocal()
        try:
            resolved = TenantAuthService(session, settings).resolve_tenant(api_key)
            if not resolved:
                raise PermissionError("无效的 API Key")
            return resolved
        finally:
            session.close()
    raw_tenant = (tenant_id or settings.default_tenant_id).strip()
    return normalize_tenant_id(raw_tenant)


@router.websocket("/ws")
async def agent_websocket(
    websocket: WebSocket,
    tenant_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    api_key: str | None = Query(default=None),
    token: str | None = Query(default=None),
) -> None:
    settings = get_settings()
    try:
        tid = _resolve_ws_tenant_id(tenant_id=tenant_id, api_key=api_key, token=token)
    except PermissionError as exc:
        await websocket.close(code=4401, reason=str(exc))
        return

    plat = normalize_platform(platform or settings.default_platform)
    aid = normalize_account_id(account_id)

    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            session = SessionLocal()
            agent = AgentService(settings, tid, plat, db_session=session, account_id=aid)
            try:
                try:
                    message: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "data": {"message": "无效的 JSON 消息"}},
                    )
                    continue

                msg_type = message.get("type")
                payload = message.get("payload") or message

                if msg_type == "chat":
                    async for event in agent.run_chat(
                        payload.get("message", ""),
                        session_id=payload.get("session_id"),
                        run_id=payload.get("run_id"),
                        provider=payload.get("provider", "openai"),
                        headless=payload.get("headless"),
                        explicit_skill_ids=payload.get("explicit_skill_ids"),
                        mode=payload.get("mode", "agent"),
                        run_mode=payload.get("run_mode", "auto"),
                    ):
                        await websocket.send_json(event.model_dump(mode="json"))

                elif msg_type == "cancel":
                    run_id = payload.get("run_id")
                    if not run_id:
                        await websocket.send_json(
                            {"type": "error", "data": {"message": "缺少 run_id"}},
                        )
                        continue
                    cancelled = await agent.cancel_run(run_id)
                    await websocket.send_json(
                        {
                            "type": "cancelled",
                            "data": {"run_id": run_id, "accepted": cancelled},
                        },
                    )

                elif msg_type == "approve":
                    async for event in agent.resume_approval(
                        payload.get("run_id", ""),
                        approved=bool(payload.get("approved")),
                    ):
                        await websocket.send_json(event.model_dump(mode="json"))

                elif msg_type == "plan":
                    async for event in agent.resume_plan(
                        payload.get("run_id", ""),
                        approved=bool(payload.get("approved")),
                    ):
                        await websocket.send_json(event.model_dump(mode="json"))

                else:
                    await websocket.send_json(
                        {"type": "error", "data": {"message": f"未知消息类型: {msg_type}"}},
                    )
            finally:
                session.close()
    except WebSocketDisconnect:
        return
