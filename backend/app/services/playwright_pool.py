from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    BROWSER_RENDER_EPOCH,
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    launch_browser,
    launch_persistent_context,
    new_browser_context,
    persistent_profile_enabled,
    register_main_page,
    uses_native_system_chrome,
)
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore

_DOUYIN_VISIBLE_ENTRY = "https://www.douyin.com/jingxuan"


def _is_blank_url(url: str) -> bool:
    normalized = (url or "").strip().lower()
    return not normalized or normalized == "about:blank" or normalized.startswith("about:blank")


async def _bootstrap_visible_pool_page(
    page: Page,
    context: BrowserContext,
    *,
    browser: Browser | None,
    settings: Settings,
    platform: str,
) -> None:
    """有头模式：先导航出 about:blank 再装轻量守卫（池内 tab 跳过 CDP，避免系统 Chrome 卡死）。"""
    current = (page.url or "").strip()
    if platform == "douyin":
        from app.services.browser_workbench import is_douyin_home_like

        on_search = "/search/" in current.lower()
        if _is_blank_url(current) or (not on_search and not is_douyin_home_like(current)):
            try:
                await page.goto(_DOUYIN_VISIBLE_ENTRY, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                with contextlib.suppress(Exception):
                    await page.goto(settings.douyin_home_url, wait_until="domcontentloaded", timeout=60000)
            with contextlib.suppress(Exception):
                for selector in (
                    'input[placeholder*="搜索"]',
                    '[data-e2e="searchbar-input"]',
                ):
                    try:
                        await page.wait_for_selector(selector, state="visible", timeout=15000)
                        break
                    except Exception:
                        continue
    elif platform == "xiaohongshu" and _is_blank_url(current):
        with contextlib.suppress(Exception):
            await page.goto(settings.xhs_home_url, wait_until="domcontentloaded", timeout=60000)
    elif platform == "kuaishou" and _is_blank_url(current):
        with contextlib.suppress(Exception):
            await page.goto(settings.kuaishou_home_url, wait_until="domcontentloaded", timeout=60000)
    with contextlib.suppress(Exception):
        await page.bring_to_front()

    register_main_page(context, page)
    if uses_native_system_chrome(settings, headless=False):
        from app.core.antibot import _install_window_open_guard

        with contextlib.suppress(Exception):
            await asyncio.wait_for(_install_window_open_guard(context, page), timeout=3.0)


async def _should_persist_session(platform: str, page: Page) -> bool:
    if platform != "xiaohongshu":
        return True
    try:
        from app.platforms.xiaohongshu.ui_helpers import should_persist_login

        return await should_persist_login(page)
    except Exception:
        return False


class PlaywrightPool:
    _instance: PlaywrightPool | None = None

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_headless: bool | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()
        self._browser_render_epoch = 0

    async def sync_browser_render_epoch(self) -> None:
        if self._browser_render_epoch == BROWSER_RENDER_EPOCH:
            return
        await self.shutdown()
        self._browser_render_epoch = BROWSER_RENDER_EPOCH

    @classmethod
    def get(cls) -> PlaywrightPool:
        if cls._instance is None:
            cls._instance = PlaywrightPool()
        return cls._instance

    def _lock_for(self, platform: str, tenant_id: str, account_id: str = "default") -> asyncio.Lock:
        key = f"{platform}:{tenant_id}:{account_id}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _ensure_playwright(self) -> Playwright:
        async with self._start_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            return self._playwright

    async def _ensure_browser(self, settings: Settings, headless: bool) -> Browser:
        # 不可在持有 _start_lock 时调用 _ensure_playwright()：asyncio.Lock 不可重入，会死锁。
        async with self._start_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            playwright = self._playwright
            if self._browser is not None and not self._browser.is_connected():
                await self._shutdown_unlocked()
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                playwright = self._playwright
            if (
                self._browser is not None
                and self._browser_headless is not None
                and self._browser_headless != headless
            ):
                await self._shutdown_unlocked()
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                playwright = self._playwright
            if self._browser is None:
                self._browser = await launch_browser(playwright, settings, headless=headless)
                self._browser_headless = headless
            return self._browser

    @asynccontextmanager
    async def tenant_context(
        self,
        platform: str,
        tenant_id: str,
        store: PlatformSessionStore,
        settings: Settings,
        *,
        headless: bool | None = None,
        persist_state: bool = True,
        account_id: str = "default",
    ) -> AsyncIterator[tuple[BrowserContext, Page]]:
        await self.sync_browser_render_epoch()
        async with self._lock_for(platform, tenant_id, account_id):
            resolved_headless = headless_for_platform(settings, platform, headless)
            playwright = await self._ensure_playwright()
            browser: Browser | None = None
            if persistent_profile_enabled(settings, platform):
                context = await launch_persistent_context(
                    playwright,
                    settings,
                    platform,
                    tenant_id,
                    store,
                    headless=resolved_headless,
                    account_id=account_id,
                )
            else:
                browser = await self._ensure_browser(settings, resolved_headless)
                context = await new_browser_context(
                    browser,
                    settings,
                    state=store.load(tenant_id, account_id),
                    tenant_id=tenant_id,
                    visible=not resolved_headless,
                )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                if not resolved_headless:
                    await _bootstrap_visible_pool_page(
                        page,
                        context,
                        browser=browser,
                        settings=settings,
                        platform=platform,
                    )
                yield context, page
                if persist_state:
                    if await _should_persist_session(platform, page):
                        await store.save_from_context(tenant_id, context, account_id)
                        if platform == "xiaohongshu":
                            from app.platforms.xiaohongshu.session_meta import record_authenticated_snapshot

                            await record_authenticated_snapshot(
                                store, tenant_id, account_id, page
                            )
                    elif platform == "xiaohongshu":
                        from app.platforms.xiaohongshu.session_meta import mark_session_expired

                        mark_session_expired(
                            store,
                            tenant_id,
                            account_id,
                            reason="guest",
                            detail="任务结束时检测到游客态",
                        )
            finally:
                await context.close()

    async def shutdown(self) -> None:
        async with self._start_lock:
            await self._shutdown_unlocked()

    async def _shutdown_unlocked(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        self._browser_headless = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
