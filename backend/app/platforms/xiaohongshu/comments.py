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
from app.platforms.xiaohongshu.profile_videos import XhsProfileVideosTool, parse_profile_input_url
from app.platforms.search_filters import SearchFilterOptions
from app.platforms.xiaohongshu.search import XhsSearchTool
from app.platforms.xiaohongshu.session import XhsSessionStore, REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.playwright_pool import PlaywrightPool


class XhsCommentCrawler:
    """组合搜索工具与评论工具的门面。"""

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
        self._profile_videos = XhsProfileVideosTool(settings, tenant_id, self.store, account_id=account_id)
        self.hot_crawler = XhsCrawler(settings, tenant_id, self.store, account_id=account_id)

    async def crawl_note_comments(self, *args, **kwargs):
        return await self._comments.crawl_note_comments(*args, **kwargs)

    async def collect_profile_videos(self, *args, **kwargs):
        return await self._profile_videos.collect_profile_videos(*args, **kwargs)

    async def crawl_profile_comments(
        self,
        profile_url: str,
        limit: int = 5,
        show_browser: bool = False,
        days: int | None = None,
        comment_days: int | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        *,
        existing_page=None,
        video_publish_days: int | None = None,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        publish_days = video_publish_days if video_publish_days is not None else days
        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = {"guest_mode": False, "session_mode": "logged_in"}

        async def _run(page) -> tuple[list[dict], list[Path], str | None]:
            return await self._crawl_profile_comments_on_page(
                page,
                profile_url=profile_url,
                limit=limit,
                days=publish_days,
                comment_days=comment_days,
                max_comments=max_comments,
                session_meta=session_meta,
            )

        if existing_page is not None and not existing_page.is_closed():
            results, files, diagnostic = await _run(existing_page)
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
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
            results, files, diagnostic = await _run(page)
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

    async def _crawl_profile_comments_on_page(
        self,
        page,
        *,
        profile_url: str,
        limit: int,
        days: int | None,
        comment_days: int | None,
        max_comments: int,
        session_meta: dict | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        captured_api_urls: list[str] = []
        notes, diagnostic, _capture = await self._profile_videos.collect_notes_on_page(
            page,
            profile_url=profile_url,
            limit=limit,
            days=days,
            captured_api_urls=captured_api_urls,
        )
        if not notes:
            return [], [], diagnostic or "主页未采集到可抓取评论的笔记"

        template_url = await self._search.pick_api_template_url(page, captured_api_urls)
        parsed = parse_profile_input_url(profile_url)
        results: list[dict] = []
        files: list[Path] = []
        if session_meta is not None:
            session_meta["videos_processed"] = 0

        for note in notes[:limit]:
            url = str(note.get("video_url") or note.get("note_url") or "")
            note_id = extract_note_id(url) or str(note.get("note_id") or "")
            if not note_id:
                continue
            payload = await self._comments._fetch_comments_via_nav(
                page,
                note_id,
                url,
                template_url or await self._search.pick_api_template_url(page),
                max_comments=max_comments,
            )
            payload["platform"] = PLATFORM
            payload["profile_context"] = {
                "profile_url": parsed.get("profile_url") or profile_url,
                "user_id": parsed.get("user_id") or note.get("author_id") or "",
                "note_entry_id": parsed.get("note_id") or "",
                "video_publish_days": days,
            }
            if session_meta:
                payload["profile_context"].update(
                    {
                        "guest_mode": session_meta.get("guest_mode", False),
                        "session_mode": session_meta.get("session_mode"),
                    }
                )
            payload["video_url"] = payload.get("note_url") or url
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{note_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            if session_meta is not None:
                session_meta["videos_processed"] = int(session_meta.get("videos_processed") or 0) + 1
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")

        watched_ids = [str(n.get("note_id") or "") for n in notes if n.get("note_id")]
        if session_meta is not None and watched_ids:
            session_meta["watched_content_ids"] = watched_ids[:500]
        return results, files, diagnostic

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
        existing_page=None,
        manual_search: bool = False,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        ui_first: bool = False,
        ui_flow_context: dict | None = None,
        **_,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        if guest_mode:
            raise ValueError("guest_mode 仅支持抖音平台")
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if ui_search_only and existing_page is None:
            return (
                [],
                [],
                "UI 搜索需要任务浏览器会话（禁止 PlaywrightPool 临时窗口）",
                {"guest_mode": False, "session_mode": "logged_in"},
            )

        if show_browser and not XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await self.hot_crawler.start_interactive_login_session()

        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = {"guest_mode": False, "session_mode": "logged_in"}

        if existing_page is not None:
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                existing_page,
                keyword=keyword,
                limit=limit,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                manual_search=manual_search,
                ui_flow_context=ui_flow_context,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
            return results, files, diagnostic, session_meta

        session = XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if session:
            page = session["page"]
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                page,
                keyword=keyword,
                limit=limit,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                manual_search=manual_search,
                ui_flow_context=ui_flow_context,
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
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                page,
                keyword=keyword,
                limit=limit,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                manual_search=manual_search,
                ui_flow_context=ui_flow_context,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

    async def _crawl_keyword_comments_on_page(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        headless: bool,
        days: int,
        region: str | None,
        max_comments: int,
        session_meta: dict | None = None,
        ui_search_only: bool = False,
        ui_first: bool = False,
        manual_search: bool = False,
        ui_flow_context: dict | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        captured_api_urls: list[str] = []
        if ui_search_only:
            note_urls, diagnostic = await self._search._ui_searchbar_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )
        elif manual_search:
            note_urls, diagnostic = await self._search.search_notes_from_existing_page(
                page, keyword, limit, region=region, days=days
            )
        else:
            note_urls, diagnostic = await self._search._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )
        results, files = await self._crawl_notes_on_page(
            page,
            note_urls,
            keyword=keyword,
            days=days,
            region=region,
            max_comments=max_comments,
            session_meta=session_meta or {},
            template_url=await self._search.pick_api_template_url(page, captured_api_urls),
        )
        return results, files, diagnostic

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
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
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
                "search_keyword": filters.composed_keyword(),
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
