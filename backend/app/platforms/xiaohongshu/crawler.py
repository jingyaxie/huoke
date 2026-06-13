from __future__ import annotations

import asyncio
import logging
import re

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    human_delay,
    human_scroll,
    launch_browser,
    open_tenant_page,
    require_login,
    user_agent,
)
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import (
    HOMEFEED_PATH,
    PLATFORM,
    REQUIRED_LOGIN_COOKIES,
    SEARCH_NOTES_PATH,
)
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.ui_helpers import save_login_if_authenticated
from app.platforms.xiaohongshu.utils import parse_note_card, to_absolute_url, walk_note_ids
from app.schemas.crawl import CrawlItem
from app.services.playwright_pool import PlaywrightPool

logger = logging.getLogger(__name__)


class XhsCrawler:
    _interactive_sessions: dict[str, dict] = {}
    _interactive_tasks: dict[str, asyncio.Task] = {}

    platform = PLATFORM

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
        self.store = store or XhsSessionStore(settings)
        self.pool = PlaywrightPool.get()

    @classmethod
    def _session_key(cls, tenant_id: str, account_id: str = "default") -> str:
        return f"{PLATFORM}:{tenant_id}:{account_id}"

    def _context_kwargs(self) -> dict:
        return context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))

    async def _launch_standalone_context(
        self, headless: bool | None = None
    ) -> tuple[Playwright, Browser, BrowserContext, Page]:
        playwright = await async_playwright().start()
        browser = await launch_browser(
            playwright,
            self.settings,
            headless=headless_for_platform(self.settings, PLATFORM, headless),
        )
        context = await browser.new_context(**self._context_kwargs())
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return playwright, browser, context, page

    async def login_and_save_cookies(self, show_browser: bool = True) -> None:
        playwright, browser, context, page = await self._launch_standalone_context(headless=not show_browser)
        try:
            await page.goto(self.settings.xhs_home_url, wait_until="domcontentloaded", timeout=120000)
            if not show_browser:
                raise RuntimeError("小红书 Cookie 登录需要可见浏览器，请设置 XHS_HEADLESS=false")
            for _ in range(60):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if "web_session" in cookie_names and (cookie_names & REQUIRED_LOGIN_COOKIES):
                    saved = await save_login_if_authenticated(
                        page, context, self.store, self.tenant_id, self.account_id
                    )
                    if saved.get("saved"):
                        return
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            raise RuntimeError(
                "未检测到小红书真实登录态（guest=false），请在浏览器中完成扫码/验证后重试。"
            )
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def start_interactive_login_session(self) -> dict:
        key = self._session_key(self.tenant_id, self.account_id)
        task = XhsCrawler._interactive_tasks.get(key)
        if task and not task.done() and key in XhsCrawler._interactive_sessions:
            return {
                "status": "running",
                "message": "该账号的小红书登录窗口已在运行",
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "platform": PLATFORM,
            }
        XhsCrawler._interactive_tasks[key] = asyncio.create_task(self._run_interactive_login_session())
        return {
            "status": "started",
            "message": "小红书登录窗口已启动",
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "platform": PLATFORM,
        }

    @classmethod
    def get_interactive_session(cls, platform: str, tenant_id: str, account_id: str = "default") -> dict | None:
        if platform != PLATFORM:
            return None
        session = cls._interactive_sessions.get(cls._session_key(tenant_id, account_id))
        if not session:
            return None
        page = session.get("page")
        if page is None:
            return None
        try:
            if page.is_closed():
                return None
        except Exception:
            return None
        return session

    def login_status(self, tenant_id: str) -> dict:
        return self.store.login_status(tenant_id, account_id=self.account_id)

    async def _run_interactive_login_session(self) -> None:
        key = self._session_key(self.tenant_id, self.account_id)
        playwright = await async_playwright().start()
        browser = None
        context = None
        try:
            browser, context, page = await open_tenant_page(
                playwright,
                self.settings,
                PLATFORM,
                self.tenant_id,
                self.store,
                headless=False,
                account_id=self.account_id,
            )
            XhsCrawler._interactive_sessions[key] = {
                "platform": PLATFORM,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            await page.goto(self.settings.xhs_explore_url, wait_until="domcontentloaded", timeout=120000)
            saved = False
            for _ in range(240):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES and "web_session" in cookie_names:
                    result = await save_login_if_authenticated(
                        page, context, self.store, self.tenant_id, self.account_id
                    )
                    if result.get("saved"):
                        saved = True
                        break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            if not saved:
                logger.warning(
                    "xhs interactive login ended without guest=false save tenant=%s account=%s",
                    self.tenant_id,
                    self.account_id,
                )
        finally:
            XhsCrawler._interactive_sessions.pop(key, None)
            XhsCrawler._interactive_tasks.pop(key, None)
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            await playwright.stop()

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        async with self.pool.tenant_context(
            PLATFORM, self.tenant_id, self.store, self.settings, account_id=self.account_id
        ) as (_, page):
            captured: list[dict] = []

            async def on_response(resp):
                try:
                    url = resp.url
                    if HOMEFEED_PATH not in url and "/homefeed" not in url:
                        return
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    if isinstance(data, dict):
                        captured.append(data)
                except Exception:
                    return

            page.on("response", on_response)
            try:
                await page.goto(self.settings.xhs_explore_url, wait_until="domcontentloaded", timeout=120000)
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
                for _ in range(8):
                    if captured:
                        break
                    await human_scroll(page, self.settings, tenant_id=self.tenant_id)

                items = self._items_from_feed_payloads(captured, limit=limit)
                if not items:
                    items = await self._items_from_dom(page, limit=limit)
                return items[:limit]
            finally:
                try:
                    page.remove_listener("response", on_response)
                except Exception:
                    pass

    def _items_from_feed_payloads(self, payloads: list[dict], limit: int) -> list[CrawlItem]:
        results: list[CrawlItem] = []
        seen: set[str] = set()
        for payload in payloads:
            items = payload.get("data", {}).get("items") if isinstance(payload.get("data"), dict) else None
            if not isinstance(items, list):
                items = payload.get("items") or []
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                parsed = parse_note_card(raw, rank=len(results) + 1, tenant_id=self.tenant_id)
                if not parsed:
                    continue
                note_id = parsed["external_id"]
                if note_id in seen:
                    continue
                seen.add(note_id)
                results.append(CrawlItem(**parsed))
                if len(results) >= limit:
                    return results
        return results

    async def _items_from_dom(self, page: Page, limit: int) -> list[CrawlItem]:
        links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]').evaluate_all(
            "els => els.map(e => ({ href: e.href, text: (e.innerText || '').trim() }))"
        )
        results: list[CrawlItem] = []
        seen: set[str] = set()
        for link in links:
            href = link.get("href") or ""
            match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", href)
            if not match:
                continue
            note_id = match.group(1)
            if note_id in seen:
                continue
            seen.add(note_id)
            text = (link.get("text") or "").strip()
            title = text if len(text) >= 2 else f"小红书笔记 {note_id[:8]}"
            results.append(
                CrawlItem(
                    platform=PLATFORM,
                    rank=len(results) + 1,
                    title=title[:500],
                    external_id=note_id,
                    video_url=to_absolute_url(page.url, href),
                    raw_data={"note_id": note_id, "href": href, "platform": PLATFORM, "tenant_id": self.tenant_id},
                )
            )
            if len(results) >= limit:
                break
        return results

    async def search_note_urls(self, keyword: str, limit: int, *, headless: bool = True) -> tuple[list[str], str | None]:
        from urllib.parse import quote

        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        note_meta: dict[str, dict] = {}

        async with async_playwright() as p:
            browser = await launch_browser(p, self.settings, headless=headless)
            context = await browser.new_context(**self._context_kwargs())
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()

            async def on_response(resp):
                try:
                    if SEARCH_NOTES_PATH not in resp.url or resp.status != 200:
                        return
                    data = await resp.json()
                except Exception:
                    return
                for note_id in walk_note_ids(data):
                    if note_id not in note_meta:
                        note_meta[note_id] = {"note_id": note_id}
                items = (data.get("data") or {}).get("items") or data.get("items") or []
                for raw in items:
                    if not isinstance(raw, dict):
                        continue
                    parsed = parse_note_card(raw, rank=0, tenant_id=self.tenant_id)
                    if not parsed:
                        continue
                    note_id = parsed["external_id"]
                    note_meta[note_id] = parsed.get("raw_data") or {"note_id": note_id}

            page.on("response", on_response)
            try:
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
                for _ in range(10):
                    if len(note_meta) >= limit:
                        break
                    await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                if not note_meta:
                    links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]').evaluate_all(
                        "els => els.map(e => e.href)"
                    )
                    for href in links:
                        match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", href or "")
                        if match:
                            note_meta[match.group(1)] = {"note_id": match.group(1)}
            finally:
                try:
                    page.remove_listener("response", on_response)
                except Exception:
                    pass
            await context.close()
            await browser.close()

        urls: list[str] = []
        for note_id, meta in list(note_meta.items())[: limit * 2]:
            from app.platforms.xiaohongshu.utils import build_note_url

            urls.append(
                build_note_url(
                    note_id,
                    meta.get("xsec_token"),
                    meta.get("xsec_source") or "pc_search",
                )
            )
            if len(urls) >= limit:
                break

        diagnostic = None
        if not urls:
            diagnostic = "搜索页未捕获到笔记，可能需要登录或触发小红书验证码。"
        elif not self.store.is_ready(self.store.load(self.tenant_id, self.account_id)):
            diagnostic = "未检测到小红书登录态，部分笔记/评论可能抓取不全。"
        return urls[:limit], diagnostic
