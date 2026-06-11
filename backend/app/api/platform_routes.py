from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    db_session,
    effective_tenant_id,
    get_account_id,
    get_authenticated_tenant_id,
    require_path_tenant,
    resolve_path_platform_id,
)
from app.core.config import Settings, get_settings
from app.platforms.registry import get_hot_crawler, get_session_store, list_platforms
from app.repositories.report_repository import ReportRepository
from app.schemas.comment_crawl import DouyinLoginRequest, UploadStorageStateRequest
from app.schemas.report import DailyReportOut
from app.schemas.snapshot import SnapshotOut
from app.schemas.trend import TrendPoint, TrendSeriesResponse
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
    force_refresh: bool = Query(default=False, description="强制即时拉取，忽略缓存；拉取失败时回退返回已有缓存"),
    cache_ttl_hours: float = Query(default=24.0, ge=0.25, le=168, description="缓存有效期（小时）"),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    service = CrawlService(session, tenant_id=tenant_id, platform=pid, account_id=account_id)
    result = await service.crawl_hot(
        limit=limit,
        force_refresh=force_refresh,
        cache_ttl_hours=cache_ttl_hours,
    )
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


@router.get("/comments/download")
def download_comment_file(file_name: str = Query(..., min_length=1)):
    settings = get_settings()
    safe_name = Path(file_name).name
    path = settings.report_output_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(path, media_type="application/json", filename=safe_name)


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


@router.get("/platforms/{platform}/videos/{video_id}/trend", response_model=TrendSeriesResponse)
def platform_video_trend(
    platform: str,
    video_id: int,
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
):
    pid = resolve_path_platform_id(platform)
    service = TrendService(session, tenant_id=tenant_id, platform=pid)
    video = service.video_repo.get_by_id(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    rows = service.video_trend(video_id, days)
    points = [TrendPoint(day=row.snapshot_date, rank=row.rank, rank_change=row.rank_change) for row in rows]
    return TrendSeriesResponse(video_id=video_id, title=video.title, points=points)


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
