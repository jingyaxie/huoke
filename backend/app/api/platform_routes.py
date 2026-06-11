from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    db_session,
    effective_platform_id,
    effective_tenant_id,
    get_account_id,
    get_authenticated_tenant_id,
    get_platform_id,
    platform_session_store,
    require_path_tenant,
    resolve_path_platform_id,
)
from app.core.config import Settings, get_settings
from app.platforms.registry import get_hot_crawler, get_session_store, list_platforms
from app.platforms.session_store import PlatformSessionStore
from app.repositories.report_repository import ReportRepository
from app.schemas.comment_crawl import (
    CommentCrawlResult,
    DouyinLoginRequest,
    KeywordCommentCrawlRequest,
    KeywordCommentCrawlResponse,
    UploadStorageStateRequest,
    VideoCommentCrawlRequest,
)
from app.schemas.report import DailyReportOut
from app.schemas.snapshot import SnapshotOut
from app.schemas.trend import TrendPoint, TrendSeriesResponse
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.crawl_service import CrawlService
from app.services.report_service import ReportService
from app.services.trend_service import TrendService


router = APIRouter(prefix="/api")


@router.get("/platforms")
def supported_platforms():
    return {"platforms": list_platforms()}


@router.post("/platforms/{platform}/crawl/hot")
async def platform_crawl_hot(
    platform: str,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    service = CrawlService(session, tenant_id=tenant_id, platform=pid, account_id=account_id)
    result = await service.crawl_hot(limit=limit)
    return result.model_dump()


@router.get("/platforms/{platform}/login-status")
def platform_login_status(
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    store = get_session_store(settings, pid)
    return store.login_status(tenant_id, account_id)


@router.put("/platforms/{platform}/tenants/{tenant_id}/storage-state")
def platform_upload_storage_state(
    platform: str,
    tenant_id: str,
    payload: UploadStorageStateRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    from app.platforms.registry import get_session_store

    store = get_session_store(settings, pid)
    path = store.save_dict(tid, payload.storage_state)
    status = store.login_status(tid)
    return {"platform": pid, "tenant_id": tid, "storage_state_path": str(path), **status}


@router.post("/platforms/{platform}/login")
async def platform_login(
    platform: str,
    payload: DouyinLoginRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = effective_tenant_id(authenticated_tenant_id, payload.tenant_id, settings)
    crawler = get_hot_crawler(settings, pid, tid)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    store = get_session_store(settings, pid)
    return {"platform": pid, "tenant_id": tid, "storage_state_path": str(store.path_for(tid))}


@router.post("/platforms/{platform}/douyin/login")
async def platform_douyin_login(
    platform: str,
    payload: DouyinLoginRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    if pid != "douyin":
        raise HTTPException(status_code=400, detail="该平台请使用对应平台的登录接口")
    tid = effective_tenant_id(authenticated_tenant_id, payload.tenant_id, settings)
    crawler = get_hot_crawler(settings, pid, tid)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    store = get_session_store(settings, pid)
    return {"platform": pid, "tenant_id": tid, "storage_state_path": str(store.path_for(tid))}


@router.post("/platforms/{platform}/comments/video", response_model=CommentCrawlResult)
async def platform_crawl_video_comments(
    platform: str,
    payload: VideoCommentCrawlRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = effective_tenant_id(tenant_id, payload.tenant_id, settings)
    service = CommentCrawlerService(settings, tenant_id=tid, platform=pid, account_id=account_id)
    result, output = await service.crawl_video_comments(payload.video_url, show_browser=payload.show_browser)
    return {
        "platform": pid,
        "tenant_id": tid,
        "account_id": account_id,
        "video_url": result["video_url"],
        "output_file": str(output),
        "total_comments_captured": result["total_comments_captured"],
        "api_total_top_comments": result["api_total_top_comments"],
    }


@router.post("/platforms/{platform}/comments/keyword", response_model=KeywordCommentCrawlResponse)
async def platform_crawl_keyword_comments(
    platform: str,
    payload: KeywordCommentCrawlRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = effective_tenant_id(tenant_id, payload.tenant_id, settings)
    service = CommentCrawlerService(settings, tenant_id=tid, platform=pid, account_id=account_id)
    results, outputs, diagnostic, session_meta = await service.crawl_keyword_comments(
        keyword=payload.keyword,
        limit=payload.limit,
        show_browser=payload.show_browser,
        days=payload.days,
        region=payload.region,
        guest_mode=payload.guest_mode,
    )
    items = [
        {
            "video_url": result["video_url"],
            "output_file": str(output),
            "total_comments_captured": result["total_comments_captured"],
            "api_total_top_comments": result["api_total_top_comments"],
        }
        for result, output in zip(results, outputs, strict=False)
    ]
    return {
        "platform": pid,
        "tenant_id": tid,
        "keyword": payload.keyword,
        "videos_found": len(results),
        "crawled": len(items),
        "diagnostic": diagnostic,
        "guest_mode": session_meta.get("guest_mode", payload.guest_mode),
        "session_mode": session_meta.get("session_mode", "logged_in"),
        "items": items,
    }


@router.get("/platforms/{platform}/hot/videos", response_model=list[SnapshotOut])
def platform_hot_videos(
    platform: str,
    snapshot_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    service = TrendService(session, tenant_id=tenant_id, platform=pid)
    return service.list_hot_videos(snapshot_date=snapshot_date, limit=limit)


@router.get("/platforms/{platform}/hot/authors")
def platform_hot_authors(
    platform: str,
    snapshot_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    service = TrendService(session, tenant_id=tenant_id, platform=pid)
    rows = service.list_hot_authors(snapshot_date=snapshot_date, limit=limit)
    return [
        {
            "author_id": row.author_id,
            "author_name": row.author_name,
            "video_count": int(row.video_count or 0),
            "like_count": int(row.like_count or 0),
            "comment_count": int(row.comment_count or 0),
            "share_count": int(row.share_count or 0),
        }
        for row in rows
    ]


@router.get("/platforms/{platform}/overview")
def platform_overview(
    platform: str,
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    service = TrendService(session, tenant_id=tenant_id, platform=pid)
    return service.overview(days)


@router.post("/platforms/{platform}/reports/daily")
async def platform_generate_daily_report(
    platform: str,
    report_date: date = Query(default_factory=date.today),
    provider: str = Query(default="template", pattern="^(template|openai|deepseek)$"),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    service = ReportService(session, tenant_id=tenant_id, platform=pid)
    title, pdf_path = await service.generate_report(report_date, provider=provider)
    return {"platform": pid, "tenant_id": tenant_id, "title": title, "pdf_path": pdf_path}


@router.get("/platforms/{platform}/reports", response_model=list[DailyReportOut])
def platform_list_reports(
    platform: str,
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    return ReportRepository(session, tenant_id, pid).list_recent()


@router.get("/platforms/{platform}/reports/{report_date}/pdf")
def platform_download_report_pdf(
    platform: str,
    report_date: date,
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    report = ReportRepository(session, tenant_id, pid).get_by_date(report_date)
    if report is None or not report.pdf_path:
        raise HTTPException(status_code=404, detail="Report PDF not found")
    path = Path(report.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report PDF file is missing")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
