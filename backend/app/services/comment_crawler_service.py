from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.platforms.registry import get_comment_crawler
from app.platforms.types import normalize_platform
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator


class CommentCrawlerService:
    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        platform: str | None = None,
        account_id: str = "default",
        session: Session | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.platform = normalize_platform(platform or self.settings.default_platform)
        self.account_id = account_id
        self.session = session
        self._backend = get_comment_crawler(
            self.settings, self.platform, self.tenant_id, account_id=self.account_id
        )
        self._coordinator = (
            CachedCrawlCoordinator(
                session,
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.account_id,
            )
            if session is not None
            else None
        )

    async def crawl_video_comments(
        self,
        video_url: str,
        show_browser: bool = False,
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[dict, Path, CacheMeta | None]:
        if self._coordinator is not None:
            result = await self._coordinator.cached_video_comments(
                self._backend.crawl_note_comments,
                content_url=video_url,
                max_comments=200,
                show_browser=show_browser,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            payload = result.payload
            if "video_url" not in payload and payload.get("note_url"):
                payload["video_url"] = payload["note_url"]
            return payload, result.output or Path(""), result.meta

        payload, output = await self._backend.crawl_note_comments(video_url, show_browser=show_browser)
        if "video_url" not in payload and payload.get("note_url"):
            payload["video_url"] = payload["note_url"]
        return payload, output, None

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
        *,
        guest_mode: bool = False,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[list[dict], list[Path], str | None, dict, CacheMeta | None]:
        if guest_mode and self.platform != "douyin":
            raise ValueError("guest_mode 仅支持抖音平台")

        if self._coordinator is not None:
            items, outputs, diagnostic, session_meta, meta = await self._coordinator.cached_keyword_comments(
                self._backend.crawl_keyword_comments,
                keyword=keyword,
                limit=limit,
                max_comments=200,
                show_browser=show_browser,
                guest_mode=guest_mode,
                days=days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            return items, outputs, diagnostic, session_meta, meta

        results, outputs, diagnostic, session_meta = await self._backend.crawl_keyword_comments(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            guest_mode=guest_mode,
        )
        return results, outputs, diagnostic, session_meta, None

    async def search_videos(
        self,
        keyword: str,
        limit: int = 20,
        show_browser: bool = False,
        days: int | None = None,
        region: str | None = None,
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[dict, Path, CacheMeta | None]:
        backend = self._backend
        if not hasattr(backend, "search_videos"):
            raise NotImplementedError(f"平台 {self.platform} 暂不支持关键词视频搜索")

        if self._coordinator is not None:
            result = await self._coordinator.cached_search_videos(
                backend.search_videos,
                keyword=keyword,
                limit=limit,
                show_browser=show_browser,
                days=days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            return result.payload, result.output or Path(""), result.meta

        payload, output = await backend.search_videos(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
        )
        return payload, output, None
