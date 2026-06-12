from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.comment_tool import DouyinCommentTool
from app.platforms.douyin.js_constants import DEFAULT_MAX_COMMENTS, PLATFORM, _extract_aweme_id
from app.platforms.douyin.search import DouyinSearchTool
from app.platforms.search_filters import SearchFilterOptions
from app.platforms.douyin.session import DouyinSessionStore, USER_LOGIN_MARKERS
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

# 从此模块继续导出常量
from app.platforms.douyin.js_constants import (  # noqa: F401
    COMMENT_PATH,
    DEFAULT_MAX_COMMENTS,
    DROP_QUERY_KEYS,
    PLATFORM,
    SEARCH_ITEM_PATH,
    SEARCH_SINGLE_PATH,
)


class DouyinCommentCrawler:
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
        self.store = store or DouyinSessionStore(settings)
        self._search = DouyinSearchTool(settings, tenant_id, self.store, account_id=account_id)
        self._comments = DouyinCommentTool(settings, tenant_id, self.store, account_id=account_id)

    @property
    def entry_url(self) -> str:
        return self._search.entry_url

    @property
    def js_warmup_urls(self) -> tuple[str, ...]:
        return self._search.js_warmup_urls

    async def crawl_note_comments(self, *args, **kwargs):
        return await self._comments.crawl_note_comments(*args, **kwargs)

    async def crawl_video_comments(self, *args, **kwargs):
        return await self._comments.crawl_video_comments(*args, **kwargs)

    async def search_videos(self, *args, **kwargs):
        return await self._search.search_videos(*args, **kwargs)

    async def search_videos_by_keyword(self, *args, **kwargs):
        return await self._search.search_videos_by_keyword(*args, **kwargs)

    async def search_videos_from_existing_page(self, *args, **kwargs):
        return await self._search.search_videos_from_existing_page(*args, **kwargs)

    async def _fetch_video_comments(self, *args, **kwargs):
        return await self._comments._fetch_video_comments(*args, **kwargs)

    async def _warmup_for_js_api(self, page, captured_urls):
        return await self._search.warmup_for_js_api(page, captured_urls)

    async def _pick_api_template_url(self, page, captured_urls=None):
        return await self._search.pick_api_template_url(page, captured_urls)

    async def _fetch_json_via_page(self, page, url, *, timeout_ms: int = 15000):
        return await self._search.fetch_json_via_page(page, url, timeout_ms=timeout_ms)

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        *,
        guest_mode: bool = False,
        existing_page=None,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        if guest_mode and show_browser:
            raise ValueError("guest_mode 与 show_browser 不能同时使用，游客态请使用无头模式")
        if not guest_mode:
            require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = self._build_session_meta(guest_mode=guest_mode)
        if existing_page is not None:
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                existing_page,
                keyword=keyword,
                limit=limit,
                manual_search=show_browser,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                from_existing=True,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

        crawler = DouyinCrawler(self.settings, self.tenant_id, self.store)
        session = DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if show_browser and not session:
            await crawler.start_interactive_login_session()
            session = DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if session:
            page = session["page"]
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                page,
                keyword=keyword,
                limit=limit,
                manual_search=show_browser,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                from_existing=True,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

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
                manual_search=show_browser,
                headless=resolved_headless,
                days=days,
                region=region,
                max_comments=max_comments,
                from_existing=False,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta


    def _build_session_meta(self, *, guest_mode: bool) -> dict:
        state = self.store.load(self.tenant_id, self.account_id)
        if guest_mode:
            mode = "guest"
        elif self.store.is_user_logged_in(state):
            mode = "logged_in"
        elif self.store.is_ready(state):
            mode = "guest"
        else:
            mode = "anonymous"
        return {"guest_mode": guest_mode, "session_mode": mode}

    @staticmethod
    def _apply_session_diagnostic(diagnostic: str | None, session_meta: dict) -> str | None:
        mode = session_meta.get("session_mode")
        if mode not in {"guest", "anonymous"}:
            return diagnostic
        label = "游客态" if mode == "guest" else "匿名态"
        if not diagnostic:
            return f"当前为{label}，结果可能不完整"
        if label in diagnostic:
            return diagnostic
        return f"{diagnostic}（{label}）"


    async def _detect_session_mode_from_page(self, page) -> str:
        try:
            names = {c.get("name") for c in await page.context.cookies() if c.get("name")}
        except Exception:
            return "anonymous"
        if names & USER_LOGIN_MARKERS:
            return "logged_in"
        if names & DouyinSessionStore.REQUIRED_LOGIN_COOKIES:
            return "guest"
        return "anonymous"


    async def _crawl_keyword_comments_on_page(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        manual_search: bool,
        headless: bool,
        days: int,
        region: str | None,
        max_comments: int,
        from_existing: bool,
        session_meta: dict | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        captured_api_urls: list[str] = []

        def on_response(resp):
            if "/aweme/v1/web/" in resp.url:
                captured_api_urls.append(resp.url)

        page.on("response", on_response)
        template_url = ""
        try:
            if manual_search or from_existing:
                api_items: dict[str, dict] = {}
                search_started: dict[str, bool] = {"value": True}
                has_storage_state = self.store.is_ready(self.store.load(self.tenant_id, self.account_id))
                if from_existing:
                    video_urls, diagnostic = await self._search.search_videos_from_existing_page(
                        page=page,
                        keyword=keyword,
                        limit=limit,
                    )
                else:
                    video_urls, diagnostic = await self._search._collect_keyword_search_results(
                        page,
                        keyword=keyword,
                        limit=limit,
                        headless=headless,
                        manual_search=manual_search,
                        api_items=api_items,
                        has_storage_state=has_storage_state,
                        search_started=search_started,
                        captured_api_urls=captured_api_urls,
                        region=region,
                        days=days,
                    )
                template_url = await self._search.pick_api_template_url(page, captured_api_urls)
            else:
                video_urls, diagnostic, template_url = await self._search._thin_browser_keyword_search(
                    page,
                    keyword=keyword,
                    limit=limit,
                    captured_api_urls=captured_api_urls,
                    region=region,
                    days=days,
                )
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        results: list[dict] = []
        files: list[Path] = []
        for url in video_urls:
            aweme_id = _extract_aweme_id(url)
            payload = await self._comments._fetch_comments_from_api(
                page,
                aweme_id,
                url,
                template_url,
                max_comments=max_comments,
            )
            payload["platform"] = PLATFORM
            ctx = {
                "keyword": keyword,
                "search_keyword": filters.composed_keyword(),
                "days": days,
                "region": region,
            }
            if session_meta:
                ctx.update(
                    {
                        "guest_mode": session_meta.get("guest_mode", False),
                        "session_mode": session_meta.get("session_mode"),
                    }
                )
            payload["keyword_context"] = ctx
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
        return results, files, diagnostic
