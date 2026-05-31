from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.author_repository import AuthorRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.video_repository import VideoRepository
from app.schemas.crawl import CrawlItem, CrawlResult
from app.services.douyin_crawler import DouyinCrawler


class CrawlService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()
        self.author_repo = AuthorRepository(session)
        self.video_repo = VideoRepository(session)
        self.snapshot_repo = SnapshotRepository(session)
        self.crawler = DouyinCrawler(self.settings)

    async def crawl_hot(self, limit: int = 100, snapshot_date: date | None = None) -> CrawlResult:
        snapshot_date = snapshot_date or date.today()
        items = await self.crawler.fetch_hot(limit=limit)
        results: list[CrawlItem] = []
        for item in items:
            author = self.author_repo.upsert(
                douyin_user_id=item.raw_data.get("author_id") if item.raw_data else None,
                name=item.author_name or "未知作者",
                avatar_url=item.author_avatar_url,
                profile_url=item.author_profile_url,
            )
            video = self.video_repo.upsert(
                title=item.title,
                author_id=author.id if author else None,
                douyin_video_id=item.douyin_video_id,
                video_url=item.video_url,
                cover_url=item.cover_url,
                like_count=item.like_count,
                comment_count=item.comment_count,
                share_count=item.share_count,
                publish_time=item.publish_time,
                raw_data=item.raw_data,
            )
            previous_rank = self.snapshot_repo.get_previous_rank(video_id=video.id, snapshot_date=snapshot_date)
            rank_change = None if previous_rank is None else previous_rank - item.rank
            self.snapshot_repo.add_snapshot(
                snapshot_date=snapshot_date,
                rank=item.rank,
                video_id=video.id,
                score=item.raw_data.get("score") if item.raw_data else None,
                rank_change=rank_change,
                raw_data=item.raw_data,
            )
            results.append(item)
        self.session.commit()
        return CrawlResult(snapshot_date=snapshot_date.isoformat(), total=len(results), items=results)

