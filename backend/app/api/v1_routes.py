from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import get_settings
from app.models.video import Video
from app.repositories.report_repository import ReportRepository
from app.schemas.comment_crawl import (
    CommentCrawlResult,
    DouyinLoginRequest,
    KeywordCommentCrawlRequest,
    KeywordCommentCrawlResponse,
    VideoCommentCrawlRequest,
)
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


@router.post("/crawl/hot")
async def crawl_hot(limit: int = Query(default=100, ge=1, le=100), session: Session = Depends(db_session)):
    service = CrawlService(session)
    result = await service.crawl_hot(limit=limit)
    return result.model_dump()


@router.post("/douyin/login")
async def douyin_login(payload: DouyinLoginRequest):
    settings = get_settings()
    crawler = DouyinCrawler(settings)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    return {"storage_state_path": str(settings.douyin_storage_state_path)}


@router.get("/douyin/login-status")
def douyin_login_status():
    settings = get_settings()
    path = settings.douyin_storage_state_path
    if not path.exists():
        return {
            "status": "missing",
            "message": "未找到登录态文件，请先打开抖音登录页完成登录。",
            "storage_state_path": str(path),
            "cookie_count": 0,
        }

    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
        required = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss"}
        has_session = bool(cookie_names & required)
        return {
            "status": "ready" if has_session else "incomplete",
            "message": "登录态可用" if has_session else "已找到 Cookie 文件，但缺少关键会话 Cookie，可能仍需重新登录。",
            "storage_state_path": str(path),
            "cookie_count": len(cookies),
            "required_cookies_present": sorted(cookie_names & required),
            "cookie_names_preview": sorted(cookie_names)[:20],
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"读取登录态失败：{exc}",
            "storage_state_path": str(path),
            "cookie_count": 0,
        }


@router.get("/douyin/server-login-url")
def douyin_server_login_url():
    settings = get_settings()
    return {"url": settings.douyin_vnc_url}


@router.post("/douyin/server-login")
async def douyin_server_login():
    settings = get_settings()
    crawler = DouyinCrawler(settings)
    result = await crawler.start_interactive_login_session()
    return {
        "storage_state_path": str(settings.douyin_storage_state_path),
        **result,
    }


@router.post("/comments/video", response_model=CommentCrawlResult)
async def crawl_video_comments(payload: VideoCommentCrawlRequest):
    service = CommentCrawlerService(get_settings())
    result, output = await service.crawl_video_comments(payload.video_url, show_browser=payload.show_browser)
    return {
        "video_url": result["video_url"],
        "output_file": str(output),
        "total_comments_captured": result["total_comments_captured"],
        "api_total_top_comments": result["api_total_top_comments"],
    }


@router.post("/comments/keyword", response_model=KeywordCommentCrawlResponse)
async def crawl_keyword_comments(payload: KeywordCommentCrawlRequest):
    service = CommentCrawlerService(get_settings())
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
):
    service = TrendService(session)
    rows = service.list_hot_videos(snapshot_date=snapshot_date, limit=limit)
    return rows


@router.get("/hot/authors")
def hot_authors(
    snapshot_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(db_session),
):
    service = TrendService(session)
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
def video_trend(video_id: int, days: int = Query(default=30, ge=1, le=365), session: Session = Depends(db_session)):
    service = TrendService(session)
    rows = service.video_trend(video_id, days)
    video = session.get(Video, video_id)
    points = [TrendPoint(day=row.snapshot_date, rank=row.rank, rank_change=row.rank_change) for row in rows]
    return TrendSeriesResponse(video_id=video_id, title=video.title if video else f"Video {video_id}", points=points)


@router.get("/overview")
def overview(days: int = Query(default=7, ge=1, le=90), session: Session = Depends(db_session)):
    service = TrendService(session)
    return service.overview(days)


@router.post("/reports/daily")
async def generate_daily_report(
    report_date: date = Query(default_factory=date.today),
    provider: str = Query(default="template", pattern="^(template|openai|deepseek)$"),
    session: Session = Depends(db_session),
):
    service = ReportService(session)
    title, pdf_path = await service.generate_report(report_date, provider=provider)
    return {"title": title, "pdf_path": pdf_path}


@router.get("/reports", response_model=list[DailyReportOut])
def list_reports(session: Session = Depends(db_session)):
    repo = ReportRepository(session)
    return repo.list_recent()


@router.get("/reports/{report_date}/pdf")
def download_report_pdf(report_date: date, session: Session = Depends(db_session)):
    report = ReportRepository(session).get_by_date(report_date)
    if report is None or not report.pdf_path:
        raise HTTPException(status_code=404, detail="Report PDF not found")
    path = Path(report.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report PDF file is missing")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
