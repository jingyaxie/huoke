from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    db_session,
    douyin_session_store,
    effective_platform_id,
    effective_tenant_id,
    get_authenticated_tenant_id,
    get_platform_id,
    require_path_tenant,
    verify_admin_secret,
)
from app.core.config import Settings, get_settings
from app.repositories.report_repository import ReportRepository
from app.schemas.comment_crawl import (
    CommentCrawlResult,
    DouyinLoginRequest,
    KeywordCommentCrawlRequest,
    KeywordCommentCrawlResponse,
    UploadStorageStateRequest,
    VideoCommentCrawlRequest,
)
from app.schemas.tenant import CreateTenantKeyRequest, CreateTenantKeyResponse
from app.services.douyin_session_store import DouyinSessionStore
from app.services.tenant_auth_service import TenantAuthService
from app.schemas.common import HealthResponse
from app.schemas.report import DailyReportOut
from app.schemas.snapshot import SnapshotOut
from app.schemas.trend import TrendPoint, TrendSeriesResponse
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.crawl_service import CrawlService
from app.services.douyin_crawler import DouyinCrawler
from app.services.report_service import ReportService
from app.services.trend_service import TrendService


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/admin/tenant-keys", response_model=CreateTenantKeyResponse)
def create_tenant_api_key(
    payload: CreateTenantKeyRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(verify_admin_secret),
):
    auth = TenantAuthService(session, settings)
    api_key, row = auth.create_api_key(payload.tenant_id, label=payload.label)
    session.commit()
    return CreateTenantKeyResponse(
        tenant_id=row.tenant_id,
        api_key=api_key,
        label=row.label,
        message="请妥善保存 API Key，之后无法再次查看明文",
    )


@router.post("/crawl/hot")
async def crawl_hot(
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = CrawlService(session, tenant_id=tenant_id, platform=platform)
    result = await service.crawl_hot(limit=limit)
    return result.model_dump()


@router.post("/tenants/{tenant_id}/crawl/hot")
async def tenant_crawl_hot(
    tenant_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(db_session),
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    service = CrawlService(session, tenant_id=tid, platform=settings.default_platform)
    result = await service.crawl_hot(limit=limit)
    return result.model_dump()


@router.post("/douyin/login")
async def douyin_login(
    payload: DouyinLoginRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: DouyinSessionStore = Depends(douyin_session_store),
    settings: Settings = Depends(get_settings),
):
    tid = effective_tenant_id(tenant_id, payload.tenant_id, settings)
    crawler = DouyinCrawler(settings, tid, store)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    path = store.path_for(tid)
    return {"tenant_id": tid, "storage_state_path": str(path)}


@router.post("/tenants/{tenant_id}/douyin/login")
async def tenant_douyin_login(
    tenant_id: str,
    payload: DouyinLoginRequest,
    store: DouyinSessionStore = Depends(douyin_session_store),
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    crawler = DouyinCrawler(settings, tid, store)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    path = store.path_for(tid)
    return {"tenant_id": tid, "storage_state_path": str(path)}


@router.get("/douyin/login-status")
def douyin_login_status(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: DouyinSessionStore = Depends(douyin_session_store),
):
    return store.login_status(tenant_id)


@router.get("/tenants/{tenant_id}/douyin/login-status")
def tenant_douyin_login_status(
    tenant_id: str,
    store: DouyinSessionStore = Depends(douyin_session_store),
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    return store.login_status(tid)


@router.put("/tenants/{tenant_id}/douyin/storage-state")
def upload_tenant_storage_state(
    tenant_id: str,
    payload: UploadStorageStateRequest,
    store: DouyinSessionStore = Depends(douyin_session_store),
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    path = store.save_dict(tid, payload.storage_state)
    status = store.login_status(tid)
    return {"tenant_id": tid, "storage_state_path": str(path), **status}


@router.get("/douyin/server-login-url")
def douyin_server_login_url(settings: Settings = Depends(get_settings)):
    return {"url": settings.douyin_vnc_url}


@router.post("/douyin/server-login")
async def douyin_server_login(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: DouyinSessionStore = Depends(douyin_session_store),
    settings: Settings = Depends(get_settings),
):
    crawler = DouyinCrawler(settings, tenant_id, store)
    result = await crawler.start_interactive_login_session()
    return {
        "tenant_id": tenant_id,
        "storage_state_path": str(store.path_for(tenant_id)),
        **result,
    }


@router.post("/tenants/{tenant_id}/douyin/server-login")
async def tenant_douyin_server_login(
    tenant_id: str,
    store: DouyinSessionStore = Depends(douyin_session_store),
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    crawler = DouyinCrawler(settings, tid, store)
    result = await crawler.start_interactive_login_session()
    return {
        "tenant_id": tid,
        "storage_state_path": str(store.path_for(tid)),
        **result,
    }


@router.post("/comments/video", response_model=CommentCrawlResult)
async def crawl_video_comments(
    payload: VideoCommentCrawlRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    settings: Settings = Depends(get_settings),
):
    tid = effective_tenant_id(tenant_id, payload.tenant_id, settings)
    pid = effective_platform_id(platform, payload.platform)
    service = CommentCrawlerService(settings, tenant_id=tid, platform=pid)
    result, output = await service.crawl_video_comments(payload.video_url, show_browser=payload.show_browser)
    return {
        "tenant_id": tid,
        "platform": pid,
        "video_url": result.get("video_url") or result.get("note_url") or payload.video_url,
        "output_file": str(output),
        "total_comments_captured": result["total_comments_captured"],
        "api_total_top_comments": result["api_total_top_comments"],
    }


@router.post("/comments/keyword", response_model=KeywordCommentCrawlResponse)
async def crawl_keyword_comments(
    payload: KeywordCommentCrawlRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    settings: Settings = Depends(get_settings),
):
    tid = effective_tenant_id(tenant_id, payload.tenant_id, settings)
    pid = effective_platform_id(platform, payload.platform)
    service = CommentCrawlerService(settings, tenant_id=tid, platform=pid)
    results, outputs, diagnostic = await service.crawl_keyword_comments(
        keyword=payload.keyword,
        limit=payload.limit,
        show_browser=payload.show_browser,
        days=payload.days,
        region=payload.region,
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
        "tenant_id": tid,
        "platform": pid,
        "keyword": payload.keyword,
        "videos_found": len(results),
        "crawled": len(items),
        "diagnostic": diagnostic,
        "items": items,
    }


@router.get("/comments/download")
def download_comment_file(file_name: str = Query(..., min_length=1)):
    settings = get_settings()
    # only allow files under report_output_dir
    safe_name = Path(file_name).name
    path = settings.report_output_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(path, media_type="application/json", filename=safe_name)


@router.get("/hot/videos", response_model=list[SnapshotOut])
def hot_videos(
    snapshot_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = TrendService(session, tenant_id=tenant_id, platform=platform)
    rows = service.list_hot_videos(snapshot_date=snapshot_date, limit=limit)
    return rows


@router.get("/hot/authors")
def hot_authors(
    snapshot_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = TrendService(session, tenant_id=tenant_id, platform=platform)
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


@router.get("/videos/{video_id}/trend", response_model=TrendSeriesResponse)
def video_trend(
    video_id: int,
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = TrendService(session, tenant_id=tenant_id, platform=platform)
    video = service.video_repo.get_by_id(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    rows = service.video_trend(video_id, days)
    points = [TrendPoint(day=row.snapshot_date, rank=row.rank, rank_change=row.rank_change) for row in rows]
    return TrendSeriesResponse(video_id=video_id, title=video.title, points=points)


@router.get("/overview")
def overview(
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = TrendService(session, tenant_id=tenant_id, platform=platform)
    return service.overview(days)


@router.post("/reports/daily")
async def generate_daily_report(
    report_date: date = Query(default_factory=date.today),
    provider: str = Query(default="template", pattern="^(template|openai|deepseek)$"),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    service = ReportService(session, tenant_id=tenant_id, platform=platform)
    title, pdf_path = await service.generate_report(report_date, provider=provider)
    return {"tenant_id": tenant_id, "title": title, "pdf_path": pdf_path}


@router.get("/reports", response_model=list[DailyReportOut])
def list_reports(
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    repo = ReportRepository(session, tenant_id, platform)
    return repo.list_recent()


@router.get("/reports/{report_date}/pdf")
def download_report_pdf(
    report_date: date,
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
):
    report = ReportRepository(session, tenant_id, platform).get_by_date(report_date)
    if report is None or not report.pdf_path:
        raise HTTPException(status_code=404, detail="Report PDF not found")
    path = Path(report.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report PDF file is missing")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
