from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_pause, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.comment_tool import XhsCommentTool
from app.platforms.xiaohongshu.constants import PLATFORM
from app.platforms.xiaohongshu.crawler import XhsCrawler
from app.platforms.xiaohongshu.js_constants import DEFAULT_MAX_COMMENTS
from app.platforms.xiaohongshu.search import XhsSearchTool
from app.platforms.xiaohongshu.session import XhsSessionStore, REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.playwright_pool import PlaywrightPool


class XhsCommentCrawler:
    """向后兼容门面：组合搜索工具 + 评论工具。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.platform = PLATFORM
        self.store = store or XhsSessionStore(settings)
        self._search = XhsSearchTool(settings, tenant_id, self.store, account_id=account_id)
        self._comments = XhsCommentTool(settings, tenant_id, self.store, account_id=account_id)
        self.hot_crawler = XhsCrawler(settings, tenant_id, self.store, account_id=account_id)

    async def crawl_note_comments(self, *args, **kwargs):
        return await self._comments.crawl_note_comments(*args, **kwargs)

    async def search_notes(self, *args, **kwargs):
        return await self._search.search_notes(*args, **kwargs)

    async def search_notes_by_keyword(self, *args, **kwargs):
        return await self._search.search_notes_by_keyword(*args, **kwargs)

    async def search_notes_from_existing_page(self, *args, **kwargs):
        return await self._search.search_notes_from_existing_page(*args, **kwargs)

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        guest_mode: bool = False,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        if guest_mode:
            raise ValueError("guest_mode 仅支持抖音平台")
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)

        if show_browser and not XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await self.hot_crawler.start_interactive_login_session()

        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session = XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        session_meta = {"guest_mode": False, "session_mode": "logged_in"}

        if session:
            page = session["page"]
            note_urls, diagnostic = await self._search.search_notes_from_existing_page(page, keyword, limit)
            results, files = await self._crawl_notes_on_page(
                page,
                note_urls,
                keyword=keyword,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            captured_api_urls: list[str] = []
            note_urls, diagnostic = await self._search._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
            )
            results, files = await self._crawl_notes_on_page(
                page,
                note_urls,
                keyword=keyword,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
                template_url=await self._search.pick_api_template_url(page, captured_api_urls),
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

    async def _crawl_notes_on_page(
        self,
        page,
        note_urls: list[str],
        *,
        keyword: str,
        days: int,
        region: str | None,
        max_comments: int,
        session_meta: dict,
        template_url: str | None = None,
    ) -> tuple[list[dict], list[Path]]:
        results: list[dict] = []
        files: list[Path] = []
        for url in note_urls:
            note_id = extract_note_id(url)
            payload = await self._comments._fetch_comments_via_nav(
                page,
                note_id,
                url,
                template_url or await self._search.pick_api_template_url(page),
                max_comments=max_comments,
            )
            payload["platform"] = PLATFORM
            payload["keyword_context"] = {
                "keyword": keyword,
                "days": days,
                "region": region,
                "guest_mode": session_meta.get("guest_mode", False),
                "session_mode": session_meta.get("session_mode"),
            }
            payload["video_url"] = payload.get("note_url") or url
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{note_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")
        return results, files

    async def _detect_session_mode_from_page(self, page) -> str:
        try:
            names = {c.get("name") for c in await page.context.cookies() if c.get("name")}
        except Exception:
            return "anonymous"
        if "web_session" in names:
            return "logged_in"
        if names & REQUIRED_LOGIN_COOKIES:
            return "guest"
        return "anonymous"
