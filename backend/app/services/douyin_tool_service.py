from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.douyin.profile import build_profile_url
from app.platforms.registry import get_comment_tool, get_dm_tool, get_follow_tool, get_search_tool
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator


class DouyinToolService:
    """抖音工具服务：搜索 / 评论 / 关注 / 私信，各走独立工具类。"""

    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        account_id: str = "default",
        session: Session | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.account_id = account_id
        self.session = session
        self._search = get_search_tool(self.settings, "douyin", self.tenant_id, account_id=account_id)
        self._comments = get_comment_tool(self.settings, "douyin", self.tenant_id, account_id=account_id)
        self._follow = get_follow_tool(self.settings, "douyin", self.tenant_id, account_id=account_id)
        self._dm = get_dm_tool(self.settings, "douyin", self.tenant_id, account_id=account_id)
        self._pipeline = DouyinCommentCrawler(self.settings, self.tenant_id, account_id=account_id)
        self._coordinator = (
            CachedCrawlCoordinator(
                session,
                self.settings,
                tenant_id=self.tenant_id,
                platform="douyin",
                account_id=self.account_id,
            )
            if session is not None
            else None
        )

    async def search_videos(
        self,
        *,
        keyword: str,
        limit: int = 10,
        show_browser: bool = False,
        days: int | None = None,
        region: str | None = None,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[dict, Path, CacheMeta | None]:
        if self._coordinator is not None:
            result = await self._coordinator.cached_search_videos(
                self._search.search_videos,
                keyword=keyword,
                limit=limit,
                show_browser=show_browser,
                days=days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            return result.payload, result.output or Path(""), result.meta
        payload, output = await self._search.search_videos(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
        )
        return payload, output, None

    async def crawl_video_comments(
        self,
        *,
        video_url: str,
        max_comments: int = 200,
        show_browser: bool = False,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[dict, Path, CacheMeta | None]:
        if self._coordinator is not None:
            result = await self._coordinator.cached_video_comments(
                self._comments.crawl_note_comments,
                content_url=video_url,
                max_comments=max_comments,
                show_browser=show_browser,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            return result.payload, result.output or Path(""), result.meta
        payload, output = await self._comments.crawl_note_comments(
            video_url,
            show_browser=show_browser,
            max_comments=max_comments,
        )
        return payload, output, None

    async def crawl_keyword_comments(
        self,
        *,
        keyword: str,
        limit: int = 3,
        max_comments: int = 200,
        show_browser: bool = False,
        guest_mode: bool = False,
        days: int = 3,
        region: str | None = None,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[list[dict], list[Path], str | None, dict, CacheMeta | None]:
        if self._coordinator is not None:
            return await self._coordinator.cached_keyword_comments(
                self._pipeline.crawl_keyword_comments,
                keyword=keyword,
                limit=limit,
                max_comments=max_comments,
                show_browser=show_browser,
                guest_mode=guest_mode,
                days=days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
        results, outputs, diagnostic, session_meta = await self._pipeline.crawl_keyword_comments(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            max_comments=max_comments,
            guest_mode=guest_mode,
        )
        return results, outputs, diagnostic, session_meta, None

    async def follow_user(
        self,
        *,
        sec_uid: str,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._follow.follow_user(
            sec_uid=sec_uid,
            user_id=user_id,
            username=username,
            show_browser=show_browser,
        )

    async def unfollow_user(
        self,
        *,
        sec_uid: str,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._follow.unfollow_user(
            sec_uid=sec_uid,
            user_id=user_id,
            username=username,
            show_browser=show_browser,
        )

    async def send_message(
        self,
        *,
        sec_uid: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._dm.send_message(
            sec_uid=sec_uid,
            message=message,
            username=username,
            show_browser=show_browser,
        )

    @staticmethod
    def profile_url(sec_uid: str) -> str:
        return build_profile_url(sec_uid)
