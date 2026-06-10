from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    launch_browser,
    launch_persistent_context,
    new_browser_context,
    persistent_profile_enabled,
)
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore


class PlaywrightPool:
    _instance: PlaywrightPool | None = None

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()

    @classmethod
    def get(cls) -> PlaywrightPool:
        if cls._instance is None:
            cls._instance = PlaywrightPool()
        return cls._instance

    def _lock_for(self, platform: str, tenant_id: str) -> asyncio.Lock:
        key = f"{platform}:{tenant_id}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _ensure_playwright(self) -> Playwright:
        async with self._start_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            return self._playwright

    async def _ensure_browser(self, settings: Settings, headless: bool) -> Browser:
        async with self._start_lock:
            playwright = await self._ensure_playwright()
            if self._browser is not None and not self._browser.is_connected():
                await self._shutdown_unlocked()
            if self._browser is None:
                self._browser = await launch_browser(playwright, settings, headless=headless)
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
        async with self._lock_for(platform, tenant_id):
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
                )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                yield context, page
                if persist_state:
                    await store.save_from_context(tenant_id, context, account_id)
            finally:
                await context.close()

    async def shutdown(self) -> None:
        async with self._start_lock:
            await self._shutdown_unlocked()

    async def _shutdown_unlocked(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
