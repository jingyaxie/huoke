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
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator


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

    def _items_from_snapshots(self, snapshot_date: date, limit: int) -> list[CrawlItem]:
        snapshots = self.snapshot_repo.list_by_date(snapshot_date, limit=limit)
        items: list[CrawlItem] = []
        for snap in snapshots:
            video = self.video_repo.get_by_id(snap.video_id)
            if video is None:
                continue
            raw = snap.raw_data or video.raw_data or {}
            items.append(
                CrawlItem(
                    platform=self.platform,
                    rank=snap.rank,
                    title=video.title,
                    author_name=raw.get("author_name"),
                    external_id=video.external_id,
                    video_url=video.video_url,
                    cover_url=video.cover_url,
                    like_count=video.like_count,
                    comment_count=video.comment_count,
                    share_count=video.share_count,
                    publish_time=video.publish_time,
                    raw_data=raw,
                )
            )
        return items

    async def crawl_hot(
        self,
        limit: int = 100,
        snapshot_date: date | None = None,
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> CrawlResult:
        snapshot_date = snapshot_date or date.today()
        coordinator = CachedCrawlCoordinator(
            self.session,
            self.settings,
            tenant_id=self.tenant_id,
            platform=self.platform,
            account_id=self.account_id,
        )
        if not force_refresh:
            cached = coordinator.cached_hot_crawl_exists(snapshot_date=snapshot_date, limit=limit)
            if cached is not None and cached.meta.from_cache:
                items = self._items_from_snapshots(snapshot_date, limit)
                if items:
                    return CrawlResult(
                        platform=self.platform,
                        snapshot_date=snapshot_date.isoformat(),
                        total=len(items),
                        items=items,
                    )

        try:
            items = await self.crawler.fetch_hot(limit=limit)
        except Exception as exc:
            fallback_items = self._items_from_snapshots(snapshot_date, limit)
            if fallback_items:
                return CrawlResult(
                    platform=self.platform,
                    snapshot_date=snapshot_date.isoformat(),
                    total=len(fallback_items),
                    items=fallback_items,
                )
            raise exc
        results: list[CrawlItem] = []
        for item in items:
            author = self.author_repo.upsert(
                platform_user_id=item.raw_data.get("author_id") if item.raw_data else None,
                name=item.author_name or "未知作者",
                avatar_url=item.author_avatar_url,
                profile_url=item.author_profile_url,
            )
            video = self.video_repo.upsert(
                title=item.title,
                author_id=author.id if author else None,
                external_id=item.external_id,
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
        result = CrawlResult(
            platform=self.platform,
            snapshot_date=snapshot_date.isoformat(),
            total=len(results),
            items=results,
        )
        coordinator.store_hot_crawl(result.model_dump(), cache_ttl_hours=cache_ttl_hours)
        return result
