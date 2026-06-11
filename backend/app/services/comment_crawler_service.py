from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.platforms.registry import get_comment_crawler
from app.platforms.types import normalize_platform


class CommentCrawlerService:
    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        platform: str | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.platform = normalize_platform(platform or self.settings.default_platform)
        self.account_id = account_id
        self._backend = get_comment_crawler(
            self.settings, self.platform, self.tenant_id, account_id=self.account_id
        )

    async def crawl_video_comments(self, video_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        payload, output = await self._backend.crawl_note_comments(video_url, show_browser=show_browser)
        if "video_url" not in payload and payload.get("note_url"):
            payload["video_url"] = payload["note_url"]
        return payload, output

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
        *,
        guest_mode: bool = False,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        if guest_mode and self.platform != "douyin":
            raise ValueError("guest_mode 仅支持抖音平台")
        return await self._backend.crawl_keyword_comments(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            guest_mode=guest_mode,
        )

    async def search_videos(
        self,
        keyword: str,
        limit: int = 20,
        show_browser: bool = False,
    ) -> tuple[dict, Path]:
        backend = self._backend
        if not hasattr(backend, "search_videos"):
            raise NotImplementedError(f"平台 {self.platform} 暂不支持关键词视频搜索")
        return await backend.search_videos(keyword=keyword, limit=limit, show_browser=show_browser)
