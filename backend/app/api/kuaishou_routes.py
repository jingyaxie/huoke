from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_account_id, get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.schemas.kuaishou_tools import (
    KuaishouFollowUserRequest,
    KuaishouKeywordCommentsRequest,
    KuaishouSearchVideosRequest,
    KuaishouSendMessageRequest,
    KuaishouToolResponse,
    KuaishouVideoCommentsRequest,
)
from app.services.kuaishou_tool_service import KuaishouToolService

router = APIRouter(prefix="/api/platforms/kuaishou", tags=["kuaishou-tools"])


def _service(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
) -> KuaishouToolService:
    return KuaishouToolService(settings, tenant_id=tenant_id, account_id=account_id)


def _envelope(
    *,
    ok: bool,
    tenant_id: str,
    account_id: str,
    tool: str,
    data: dict,
    diagnostic: str | None = None,
    report_file: str | None = None,
) -> KuaishouToolResponse:
    return KuaishouToolResponse(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool=tool,
        data=data,
        diagnostic=diagnostic,
        report_file=report_file,
    )


@router.post("/search/videos", response_model=KuaishouToolResponse, summary="关键词搜索视频")
async def search_videos(
    payload: KuaishouSearchVideosRequest,
    service: KuaishouToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output = await service.search_videos(
        keyword=payload.keyword,
        limit=payload.limit,
        show_browser=payload.show_browser,
    )
    videos = result.get("videos") or []
    return _envelope(
        ok=bool(videos),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="search",
        data={
            "keyword": payload.keyword,
            "video_count": len(videos),
            "capture_method": result.get("capture_method"),
            "videos": videos,
        },
        diagnostic=result.get("diagnostic"),
        report_file=str(output),
    )


@router.post("/comments/videos", response_model=KuaishouToolResponse, summary="抓取单视频评论")
async def crawl_video_comments(
    payload: KuaishouVideoCommentsRequest,
    service: KuaishouToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output = await service.crawl_video_comments(
        video_url=payload.video_url,
        max_comments=payload.max_comments,
        show_browser=payload.show_browser,
    )
    comments = result.get("comments") or []
    preview = comments[:20]
    return _envelope(
        ok=bool(comments) or int(result.get("api_total_top_comments") or 0) == 0,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments",
        data={
            "photo_id": result.get("photo_id"),
            "video_url": result.get("video_url"),
            "total_comments_captured": result.get("total_comments_captured", 0),
            "api_total_top_comments": result.get("api_total_top_comments", 0),
            "capture_method": result.get("capture_method"),
            "comments_preview": preview,
            "comments_total_in_response": len(preview),
        },
        diagnostic=result.get("warning"),
        report_file=str(output),
    )


@router.post("/comments/keyword", response_model=KuaishouToolResponse, summary="关键词搜索并抓取评论")
async def crawl_keyword_comments(
    payload: KuaishouKeywordCommentsRequest,
    service: KuaishouToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    results, outputs, diagnostic, session_meta = await service.crawl_keyword_comments(
        keyword=payload.keyword,
        limit=payload.limit,
        max_comments=payload.max_comments,
        show_browser=payload.show_browser,
        days=payload.days,
        region=payload.region,
    )
    items = [
        {
            "photo_id": row.get("photo_id"),
            "video_url": row.get("video_url"),
            "total_comments_captured": row.get("total_comments_captured", 0),
            "api_total_top_comments": row.get("api_total_top_comments", 0),
            "report_file": str(path),
        }
        for row, path in zip(results, outputs, strict=False)
    ]
    return _envelope(
        ok=bool(items),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments_keyword",
        data={
            "keyword": payload.keyword,
            "videos_found": len(results),
            "session_mode": session_meta.get("session_mode", "logged_in"),
            "items": items,
        },
        diagnostic=diagnostic,
    )


@router.post("/users/follow", response_model=KuaishouToolResponse, summary="关注单个用户")
async def follow_user(
    payload: KuaishouFollowUserRequest,
    service: KuaishouToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await service.follow_user(
        user_id=payload.user_id,
        username=payload.username or "",
        show_browser=payload.show_browser,
    )
    follow = result.get("follow") or {}
    ok = bool(follow.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="follow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "profile_url": result.get("profile_url") or service.profile_url(payload.user_id),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "follow": follow,
        },
        diagnostic=follow.get("error") or follow.get("reason"),
        report_file=result.get("output_file"),
    )


@router.post("/users/messages", response_model=KuaishouToolResponse, summary="向单个用户发送私信")
async def send_user_message(
    payload: KuaishouSendMessageRequest,
    service: KuaishouToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await service.send_message(
        user_id=payload.user_id,
        message=payload.message,
        username=payload.username or "",
        show_browser=payload.show_browser,
    )
    message = result.get("message") or {}
    ok = bool(message.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="dm",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "profile_url": result.get("profile_url") or service.profile_url(payload.user_id),
            "message": message,
            "text_preview": payload.message[:80],
        },
        diagnostic=message.get("error") or message.get("hint"),
        report_file=result.get("output_file"),
    )
