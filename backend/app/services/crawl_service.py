from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.platforms.constants import DEFAULT_PLATFORM
from app.platforms.registry import get_hot_crawler
from app.repositories.author_repository import AuthorRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.video_repository import VideoRepository
from app.schemas.crawl import CrawlItem, CrawlResult


class CrawlService:
    def __init__(
        self,
        session: Session,
        tenant_id: str | None = None,
        platform: str | None = None,
        settings: Settings | None = None,
        account_id: str = "default",
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.platform = platform or self.settings.default_platform
        self.account_id = account_id
        self.author_repo = AuthorRepository(session, self.tenant_id, self.platform)
        self.video_repo = VideoRepository(session, self.tenant_id, self.platform)
        self.snapshot_repo = SnapshotRepository(session, self.tenant_id, self.platform)
        self.crawler = get_hot_crawler(
            self.settings, self.platform, self.tenant_id, account_id=self.account_id
        )

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
            content_id = item.external_id or item.douyin_video_id
            video = self.video_repo.upsert(
                title=item.title,
                author_id=author.id if author else None,
                external_id=content_id,
                douyin_video_id=content_id,
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
        return CrawlResult(
            platform=self.platform,
            snapshot_date=snapshot_date.isoformat(),
            total=len(results),
            items=results,
        )
