from __future__ import annotations

import asyncio
import os
import re
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    human_delay,
    launch_args,
    require_login,
    launch_browser,
)
from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore, REQUIRED_LOGIN_COOKIES
from app.platforms.session_store import PlatformSessionStore
from app.schemas.crawl import CrawlItem
from app.services.playwright_pool import PlaywrightPool
from app.utils.parsers import parse_count, parse_datetime


PLATFORM = "douyin"


class DouyinCrawler:
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
        self.store = store or DouyinSessionStore(settings)
        self.pool = PlaywrightPool.get()

    @classmethod
    def _session_key(cls, tenant_id: str, account_id: str = "default") -> str:
        return f"{cls.platform}:{tenant_id}:{account_id}"

    def _context_kwargs(self) -> dict:
        return context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))

    async def _launch_standalone_context(
        self, headless: bool | None = None
    ) -> tuple[Playwright, Browser, BrowserContext, Page]:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=headless_for_platform(self.settings, self.platform, headless),
            args=launch_args(),
        )
        context = await browser.new_context(**self._context_kwargs())
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return playwright, browser, context, page

    @property
    def entry_url(self) -> str:
        return self.settings.douyin_hot_url

    async def login_and_save_cookies(self, show_browser: bool = True) -> None:
        playwright, browser, context, page = await self._launch_standalone_context(headless=not show_browser)
        try:
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            if not show_browser:
                raise RuntimeError("Cookie login requires an interactive browser. Set DOUYIN_HEADLESS=false first.")
            for _ in range(60):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES:
                    await self.store.save_from_context(self.tenant_id, context, self.account_id)
                    return
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            await self.store.save_from_context(self.tenant_id, context, self.account_id)
            raise RuntimeError("未检测到有效登录态，请在浏览器里完成扫码/验证后重试。")
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def start_interactive_login_session(self) -> dict:
        key = self._session_key(self.tenant_id, self.account_id)
        task = DouyinCrawler._interactive_tasks.get(key)
        if task and not task.done() and key in DouyinCrawler._interactive_sessions:
            return {
                "status": "running",
                "message": "该账号的服务器登录窗口已在运行",
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "platform": self.platform,
            }
        DouyinCrawler._interactive_tasks[key] = asyncio.create_task(self._run_interactive_login_session())
        return {
            "status": "started",
            "message": "服务器登录窗口已启动",
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "platform": self.platform,
        }

    @classmethod
    def get_interactive_session(cls, platform: str, tenant_id: str, account_id: str = "default") -> dict | None:
        if platform != cls.platform:
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
            browser = await launch_browser(playwright, self.settings, headless=False)
            context = await browser.new_context(**self._context_kwargs())
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()
            DouyinCrawler._interactive_sessions[key] = {
                "platform": self.platform,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            for _ in range(180):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES:
                    await self.store.save_from_context(self.tenant_id, context, self.account_id)
                    await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            while True:
                await page.wait_for_timeout(1000)
        finally:
            DouyinCrawler._interactive_sessions.pop(key, None)
            DouyinCrawler._interactive_tasks.pop(key, None)
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            await playwright.stop()

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        async with self.pool.tenant_context(
            self.platform, self.tenant_id, self.store, self.settings, account_id=self.account_id
        ) as (_, page):
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            items = await self._extract_from_page(page, limit=limit)
            return items[:limit]

    async def _extract_from_page(self, page: Page, limit: int) -> list[CrawlItem]:
        cards = page.locator("a")
        count = await cards.count()
        results: list[CrawlItem] = []
        seen_video_ids: set[str] = set()
        for index in range(min(count, 500)):
            node = cards.nth(index)
            href = await node.get_attribute("href")
            text = " ".join((await node.inner_text(timeout=1000) or "").split())
            if not text or len(text) < 4:
                continue
            href_text = href or ""
            if "/video/" not in href_text and "/note/" not in href_text:
                continue
            video_id = self._extract_video_id(href)
            if video_id and video_id in seen_video_ids:
                continue
            parsed = self._parse_hot_card_text(text)
            title = parsed.get("title") or ""
            if len(title) < 2:
                continue
            if video_id:
                seen_video_ids.add(video_id)
            item = CrawlItem(
                platform=self.platform,
                rank=len(results) + 1,
                title=title,
                author_name=parsed.get("author_name") or self._guess_author(text),
                external_id=video_id,
                video_url=self._to_absolute_url(page.url, href),
                like_count=parse_count(parsed.get("like_count_text") or self._match_count(text, ("点赞", "赞"))),
                comment_count=parse_count(self._match_count(text, ("评论", "评"))),
                share_count=parse_count(self._match_count(text, ("分享", "转"))),
                publish_time=parse_datetime(parsed.get("publish_time_text") or self._match_publish_time(text)),
                raw_data={
                    "text": text,
                    "href": href,
                    "index": index,
                    "tenant_id": self.tenant_id,
                    "platform": self.platform,
                },
            )
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def _parse_hot_card_text(self, text: str) -> dict:
        clean = " ".join(text.split())
        clean = re.sub(r"^\d{1,2}:\d{2}\s*", "", clean)

        like_count_text: str | None = None
        like_match = re.match(r"^([0-9]+(?:\.[0-9]+)?[万亿]?)\s+", clean)
        if like_match:
            like_count_text = like_match.group(1)
            clean = clean[like_match.end() :].strip()

        author_name: str | None = None
        author_match = re.search(r"@([^\s·•|]+)", clean)
        if author_match:
            candidate = author_match.group(1).strip()
            if not self._is_invalid_author_name(candidate):
                author_name = candidate

        publish_time_text: str | None = None
        time_match = re.search(r"(\d+[天周月年]前|\d{1,2}月\d{1,2}日)", clean)
        if time_match:
            publish_time_text = time_match.group(1)

        if author_match:
            title = clean[: author_match.start()].strip()
        else:
            title = re.sub(r"(\d+[天周月年]前|\d{1,2}月\d{1,2}日)$", "", clean).strip()

        title = re.sub(r"[·•|]\s*$", "", title).strip()
        return {
            "title": title,
            "author_name": author_name,
            "like_count_text": like_count_text,
            "publish_time_text": publish_time_text,
        }

    def _extract_video_id(self, href: str | None) -> str | None:
        if not href:
            return None
        match = re.search(r"/video/(\d+)", href)
        return match.group(1) if match else None

    def _to_absolute_url(self, page_url: str, href: str | None) -> str | None:
        if not href:
            return None
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            from urllib.parse import urljoin

            return urljoin(page_url, href)
        return None

    def _guess_author(self, text: str) -> str | None:
        parts = [part for part in re.split(r"[|•·/\n]", text) if part.strip()]
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if self._is_invalid_author_name(candidate):
                return None
            return candidate
        return None

    def _match_count(self, text: str, labels: tuple[str, ...]) -> str | None:
        for label in labels:
            match = re.search(label + r"[:：]?\s*([0-9.]+[万亿]?)", text)
            if match:
                return match.group(1)
        return None

    def _match_publish_time(self, text: str) -> str | None:
        match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)", text)
        return match.group(1) if match else None

    def _is_invalid_author_name(self, value: str | None) -> bool:
        if not value:
            return True
        text = value.strip()
        if not text:
            return True
        if re.fullmatch(r"\d{1,2}月\d{1,2}日", text):
            return True
        if re.fullmatch(r"\d+[天周月年]前", text):
            return True
        if len(text) > 30:
            return True
        if re.search(r"[#·•|]", text):
            return True
        return False
