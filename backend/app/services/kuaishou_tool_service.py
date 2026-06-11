from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.platforms.kuaishou.comments import KuaishouCommentCrawler
from app.platforms.kuaishou.utils import build_profile_url
from app.platforms.registry import get_comment_tool, get_dm_tool, get_follow_tool, get_search_tool


class KuaishouToolService:
    """快手工具服务：搜索 / 评论 / 关注 / 私信，各走独立工具类。"""

    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.account_id = account_id
        self._search = get_search_tool(self.settings, "kuaishou", self.tenant_id, account_id=account_id)
        self._comments = get_comment_tool(self.settings, "kuaishou", self.tenant_id, account_id=account_id)
        self._follow = get_follow_tool(self.settings, "kuaishou", self.tenant_id, account_id=account_id)
        self._dm = get_dm_tool(self.settings, "kuaishou", self.tenant_id, account_id=account_id)
        self._pipeline = KuaishouCommentCrawler(self.settings, self.tenant_id, account_id=account_id)

    async def search_videos(
        self,
        *,
        keyword: str,
        limit: int = 10,
        show_browser: bool = False,
    ) -> tuple[dict, Path]:
        return await self._search.search_videos(keyword=keyword, limit=limit, show_browser=show_browser)

    async def crawl_video_comments(
        self,
        *,
        video_url: str,
        max_comments: int = 200,
        show_browser: bool = False,
    ) -> tuple[dict, Path]:
        return await self._comments.crawl_video_comments(
            video_url,
            show_browser=show_browser,
            max_comments=max_comments,
        )

    async def crawl_keyword_comments(
        self,
        *,
        keyword: str,
        limit: int = 3,
        max_comments: int = 200,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        return await self._pipeline.crawl_keyword_comments(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            max_comments=max_comments,
        )

    async def follow_user(
        self,
        *,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._follow.follow_user(
            user_id=user_id,
            username=username,
            show_browser=show_browser,
        )

    async def send_message(
        self,
        *,
        user_id: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._dm.send_message(
            user_id=user_id,
            message=message,
            username=username,
            show_browser=show_browser,
        )

    @staticmethod
    def profile_url(user_id: str) -> str:
        return build_profile_url(user_id)
