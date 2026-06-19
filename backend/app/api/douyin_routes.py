from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_account_id, get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.platforms.douyin.profile import build_profile_url
from app.schemas.crawl_cache import CacheMeta
from app.schemas.douyin_tools import (
    DouyinFollowUserRequest,
    DouyinKeywordCommentsRequest,
    DouyinProfileVideosRequest,
    DouyinSearchVideosRequest,
    DouyinSendMessageRequest,
    DouyinStandaloneKeywordBrowseRequest,
    DouyinToolResponse,
    DouyinUnfollowUserRequest,
    DouyinVideoCommentsRequest,
)
from app.services.platform_skill_adapter import PlatformSkillAdapter
from app.services.skill_runner_service import SkillRunnerService

router = APIRouter(prefix="/api/platforms/douyin", tags=["douyin-tools"])


def _runner(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> SkillRunnerService:
    return SkillRunnerService(
        settings,
        tenant_id,
        "douyin",
        account_id=account_id,
        db_session=session,
    )


def _adapter(runner: SkillRunnerService = Depends(_runner)) -> PlatformSkillAdapter:
    return PlatformSkillAdapter(runner)


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
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await adapter.search(payload)
    videos = result.get("videos") or []
    return _envelope(
        ok=bool(videos),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="search",
        data=result,
        diagnostic=result.get("diagnostic"),
        report_file=str(output) if output else None,
        cache=cache_meta,
    )


@router.post("/profile/videos", response_model=DouyinToolResponse, summary="主页 URL 采集视频列表")
async def collect_profile_videos(
    payload: DouyinProfileVideosRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await adapter.profile_videos(payload)
    videos = result.get("videos") or []
    return _envelope(
        ok=bool(videos),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="profile_videos",
        data=result,
        diagnostic=result.get("diagnostic"),
        report_file=str(output) if output else None,
        cache=cache_meta,
    )


@router.post("/comments/videos", response_model=DouyinToolResponse, summary="抓取单视频评论")
async def crawl_video_comments(
    payload: DouyinVideoCommentsRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await adapter.crawl_content_comments(payload)
    comments = result.get("comments_preview") or []
    return _envelope(
        ok=bool(comments) or int(result.get("api_total_top_comments") or 0) == 0,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments",
        data=result,
        diagnostic=result.get("warning"),
        report_file=str(output) if output else None,
        cache=cache_meta,
    )


@router.post("/comments/keyword", response_model=DouyinToolResponse, summary="关键词搜索并抓取评论")
async def crawl_keyword_comments(
    payload: DouyinKeywordCommentsRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    if payload.guest_mode and payload.show_browser:
        raise HTTPException(status_code=400, detail="guest_mode 与 show_browser 不能同时使用")
    result, diagnostic, cache_meta = await adapter.crawl_keyword_comments(payload)
    items = result.get("items") or []
    return _envelope(
        ok=bool(items),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments_keyword",
        data=result,
        diagnostic=diagnostic,
        cache=cache_meta,
    )


@router.post("/users/follow", response_model=DouyinToolResponse, summary="关注单个用户")
async def follow_user(
    payload: DouyinFollowUserRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.follow_user(payload)
    follow = result.get("follow") or {}
    ok = bool(follow.get("ok"))
    sec_uid = payload.sec_uid
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="follow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid") or sec_uid,
            "profile_url": result.get("profile_url") or build_profile_url(sec_uid),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "follow": follow,
        },
        diagnostic=follow.get("error") or follow.get("reason") or result.get("error"),
        report_file=result.get("output_file"),
    )


@router.post("/users/unfollow", response_model=DouyinToolResponse, summary="取消关注单个用户")
async def unfollow_user(
    payload: DouyinUnfollowUserRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.unfollow_user(payload)
    unfollow = result.get("unfollow") or {}
    ok = bool(unfollow.get("ok"))
    sec_uid = payload.sec_uid
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="unfollow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid") or sec_uid,
            "profile_url": result.get("profile_url") or build_profile_url(sec_uid),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "unfollow": unfollow,
        },
        diagnostic=unfollow.get("error") or unfollow.get("reason") or result.get("error"),
        report_file=result.get("output_file"),
    )


@router.post("/users/messages", response_model=DouyinToolResponse, summary="向单个用户发送私信")
async def send_user_message(
    payload: DouyinSendMessageRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.send_message(payload)
    message = result.get("message") or {}
    ok = bool(message.get("ok"))
    sec_uid = payload.sec_uid
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="dm",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid") or sec_uid,
            "profile_url": result.get("profile_url") or build_profile_url(sec_uid),
            "message": message,
            "text_preview": payload.message[:80],
        },
        diagnostic=message.get("error") or message.get("hint") or result.get("error"),
        report_file=result.get("output_file"),
    )


@router.post(
    "/standalone/keyword-browse",
    response_model=DouyinToolResponse,
    summary="独立关键词浏览（复用桌面稳定浏览器）",
)
async def standalone_keyword_browse(
    payload: DouyinStandaloneKeywordBrowseRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
):
    from app.platforms.douyin.standalone_keyword_browse import (
        StandaloneKeywordBrowseConfig,
        run_standalone_keyword_browse_with_browser,
    )

    target = max(1, int(payload.target_precise_leads or payload.limit))
    config = StandaloneKeywordBrowseConfig(
        keyword=payload.keyword.strip(),
        days=payload.days,
        comment_days=payload.comment_days,
        content_limit=target,
        target_precise_leads=target,
        max_videos_to_browse=max(target, int(payload.max_videos_to_browse)),
        match_keywords=list(payload.match_keywords),
        exclude_keywords=list(payload.exclude_keywords),
        execute_outreach=bool(payload.execute_outreach),
        test_all_outreach=bool(payload.test_all_outreach),
        reply_text=payload.reply_text.strip(),
        dm_text=payload.dm_text.strip(),
        action_policy={
            "comment_ratio": payload.comment_ratio,
            "dm_ratio": payload.dm_ratio,
            "follow_ratio": payload.follow_ratio,
            "interval_min_sec": 10,
            "interval_max_sec": 30,
        },
        persist_to_db=bool(payload.persist_to_db),
        reuse_stable_session=True,
        close_browser_after=bool(payload.close_browser_after),
    )
    result = await run_standalone_keyword_browse_with_browser(
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
        db_session=session if config.persist_to_db else None,
        headless=False,
    )
    return _envelope(
        ok=result.ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="standalone_keyword_browse",
        data={
            "keyword": result.keyword,
            "search_url": result.search_url,
            "videos_processed": result.videos_processed,
            "comments_scanned": result.comments_scanned,
            "duplicates_skipped": result.duplicates_skipped,
            "precise_lead_count": len(result.precise_leads),
            "target_reached": result.target_reached,
            "phase_log": result.phase_log[-20:],
            "error": result.error,
        },
        diagnostic=result.diagnostic,
        report_file=result.output_file,
    )
