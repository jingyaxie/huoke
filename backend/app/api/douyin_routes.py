from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_account_id, get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.schemas.crawl_cache import CacheMeta
from app.schemas.douyin_tools import (
    DouyinFollowUserRequest,
    DouyinUnfollowUserRequest,
    DouyinKeywordCommentsRequest,
    DouyinSearchVideosRequest,
    DouyinSendMessageRequest,
    DouyinToolResponse,
    DouyinVideoCommentsRequest,
)
from app.services.douyin_tool_service import DouyinToolService

router = APIRouter(prefix="/api/platforms/douyin", tags=["douyin-tools"])


def _service(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> DouyinToolService:
    return DouyinToolService(settings, tenant_id=tenant_id, account_id=account_id, session=session)


def _envelope(
    *,
    ok: bool,
    tenant_id: str,
    account_id: str,
    tool: str,
    data: dict,
    diagnostic: str | None = None,
    report_file: str | None = None,
    cache: CacheMeta | None = None,
) -> DouyinToolResponse:
    return DouyinToolResponse(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool=tool,
        data=data,
        diagnostic=diagnostic,
        report_file=report_file,
        cache=cache,
    )


@router.post("/search/videos", response_model=DouyinToolResponse, summary="关键词搜索视频")
async def search_videos(
    payload: DouyinSearchVideosRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await service.search_videos(
        keyword=payload.keyword,
        limit=payload.limit,
        show_browser=payload.show_browser,
        days=payload.days,
        region=payload.region,
        force_refresh=payload.force_refresh,
        cache_ttl_hours=payload.cache_ttl_hours,
    )
    videos = result.get("videos") or []
    return _envelope(
        ok=bool(videos),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="search",
        data={
            "keyword": payload.keyword,
            "search_keyword": result.get("search_keyword"),
            "region": payload.region,
            "days": payload.days,
            "video_count": len(videos),
            "capture_method": result.get("capture_method"),
            "videos": videos,
        },
        diagnostic=result.get("diagnostic"),
        report_file=str(output),
        cache=cache_meta,
    )


@router.post("/comments/videos", response_model=DouyinToolResponse, summary="抓取单视频评论")
async def crawl_video_comments(
    payload: DouyinVideoCommentsRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await service.crawl_video_comments(
        video_url=payload.video_url,
        max_comments=payload.max_comments,
        show_browser=payload.show_browser,
        force_refresh=payload.force_refresh,
        cache_ttl_hours=payload.cache_ttl_hours,
    )
    comments = result.get("comments") or []
    preview = comments[:20]
    return _envelope(
        ok=bool(comments) or int(result.get("api_total_top_comments") or 0) == 0,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments",
        data={
            "aweme_id": result.get("aweme_id"),
            "video_url": result.get("video_url"),
            "total_comments_captured": result.get("total_comments_captured", 0),
            "api_total_top_comments": result.get("api_total_top_comments", 0),
            "capture_method": result.get("capture_method"),
            "comments_preview": preview,
            "comments_total_in_response": len(preview),
        },
        diagnostic=result.get("warning"),
        report_file=str(output),
        cache=cache_meta,
    )


@router.post("/comments/keyword", response_model=DouyinToolResponse, summary="关键词搜索并抓取评论")
async def crawl_keyword_comments(
    payload: DouyinKeywordCommentsRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    if payload.guest_mode and payload.show_browser:
        raise HTTPException(status_code=400, detail="guest_mode 与 show_browser 不能同时使用")
    results, outputs, diagnostic, session_meta, cache_meta = await service.crawl_keyword_comments(
        keyword=payload.keyword,
        limit=payload.limit,
        max_comments=payload.max_comments,
        show_browser=payload.show_browser,
        guest_mode=payload.guest_mode,
        days=payload.days,
        region=payload.region,
        force_refresh=payload.force_refresh,
        cache_ttl_hours=payload.cache_ttl_hours,
    )
    items = [
        {
            "aweme_id": row.get("aweme_id"),
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
            "guest_mode": session_meta.get("guest_mode", payload.guest_mode),
            "session_mode": session_meta.get("session_mode", "logged_in"),
            "items": items,
        },
        diagnostic=diagnostic,
        cache=cache_meta,
    )


@router.post("/users/follow", response_model=DouyinToolResponse, summary="关注单个用户")
async def follow_user(
    payload: DouyinFollowUserRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await service.follow_user(
        sec_uid=payload.sec_uid,
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
            "sec_uid": result.get("sec_uid"),
            "profile_url": result.get("profile_url") or service.profile_url(payload.sec_uid),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "follow": follow,
        },
        diagnostic=follow.get("error") or follow.get("reason"),
        report_file=result.get("output_file"),
    )


@router.post("/users/unfollow", response_model=DouyinToolResponse, summary="取消关注单个用户")
async def unfollow_user(
    payload: DouyinUnfollowUserRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await service.unfollow_user(
        sec_uid=payload.sec_uid,
        user_id=payload.user_id,
        username=payload.username or "",
        show_browser=payload.show_browser,
    )
    unfollow = result.get("unfollow") or {}
    ok = bool(unfollow.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="unfollow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid"),
            "profile_url": result.get("profile_url") or service.profile_url(payload.sec_uid),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "unfollow": unfollow,
        },
        diagnostic=unfollow.get("error") or unfollow.get("reason"),
        report_file=result.get("output_file"),
    )


@router.post("/users/messages", response_model=DouyinToolResponse, summary="向单个用户发送私信")
async def send_user_message(
    payload: DouyinSendMessageRequest,
    service: DouyinToolService = Depends(_service),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await service.send_message(
        sec_uid=payload.sec_uid,
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
            "sec_uid": result.get("sec_uid"),
            "profile_url": result.get("profile_url") or service.profile_url(payload.sec_uid),
            "message": message,
            "text_preview": payload.message[:80],
        },
        diagnostic=message.get("error") or message.get("hint"),
        report_file=result.get("output_file"),
    )
