from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    headless_for_platform,
    launch_browser,
    new_browser_context,
    open_tenant_page,
)
from app.core.config import Settings
from app.platforms.registry import get_session_store
from app.services.agent_network_capture import NetworkCapture


@dataclass
class AgentBrowserSession:
    session_id: str
    tenant_id: str
    platform: str
    settings: Settings
    account_id: str = "default"
    headless: bool | None = None
    _playwright: Playwright | None = field(default=None, repr=False)
    _browser: Browser | None = field(default=None, repr=False)
    _context: BrowserContext | None = field(default=None, repr=False)
    _page: Page | None = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    network_capture: NetworkCapture = field(default_factory=NetworkCapture, repr=False)

    @property
    def is_started(self) -> bool:
        return self._page is not None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器会话未启动")
        return self._page

    async def ensure_started(self) -> Page:
        if self._page is not None:
            return self._page
        timeout = float(self.settings.agent_browser_start_timeout_seconds)
        await asyncio.wait_for(self.start(), timeout=timeout)
        return self.page

    async def start(self) -> None:
        async with self._lock:
            if self._page is not None:
                return
            store = get_session_store(self.settings, self.platform)
            self._playwright = await async_playwright().start()
            self._browser, self._context, self._page = await open_tenant_page(
                self._playwright,
                self.settings,
                self.platform,
                self.tenant_id,
                store,
                headless=self.headless,
                account_id=self.account_id,
            )
            self.network_capture.attach(self._page)

    async def close(self) -> None:
        async with self._lock:
            self.network_capture.detach()
            if self._context is not None:
                try:
                    store = get_session_store(self.settings, self.platform)
                    await store.save_from_context(self.tenant_id, self._context, self.account_id)
                except Exception:
                    pass
                await self._context.close()
                self._context = None
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._page = None

    async def page_info(self) -> dict[str, str | None]:
        page = self.page
        return {
            "url": page.url,
            "title": await page.title(),
        }

    async def capture_storage_state(self) -> dict:
        if self._context is None:
            raise RuntimeError("浏览器上下文未启动")
        return await self._context.storage_state()

    async def restore_from_checkpoint(self, storage_state: dict, url: str | None = None) -> None:
        async with self._lock:
            if self._playwright is None:
                raise RuntimeError("浏览器未启动")
            if self._page is not None:
                await self._page.close()
                self._page = None
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._browser is None:
                resolved_headless = headless_for_platform(self.settings, self.platform, self.headless)
                self._browser = await launch_browser(self._playwright, self.settings, headless=resolved_headless)
            self._context = await new_browser_context(
                self._browser,
                self.settings,
                state=storage_state,
                tenant_id=self.tenant_id,
            )
            self._page = await self._context.new_page()
            self.network_capture.clear()
            self.network_capture.attach(self._page)
            if url and url not in {"", "about:blank"}:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)


class AgentSessionManager:
    _instance: AgentSessionManager | None = None

    def __init__(self) -> None:
        self._sessions: dict[str, AgentBrowserSession] = {}
        self._manager_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> AgentSessionManager:
        if cls._instance is None:
            cls._instance = AgentSessionManager()
        return cls._instance

    async def create(
        self,
        tenant_id: str,
        platform: str,
        settings: Settings,
        *,
        account_id: str = "default",
        headless: bool | None = None,
        auto_start: bool = True,
    ) -> AgentBrowserSession:
        session_id = str(uuid.uuid4())
        session = AgentBrowserSession(
            session_id=session_id,
            tenant_id=tenant_id,
            platform=platform,
            settings=settings,
            account_id=account_id,
            headless=headless,
        )
        if auto_start:
            await session.start()
        async with self._manager_lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> AgentBrowserSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> bool:
        async with self._manager_lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.close()
        return True

    async def shutdown_all(self) -> None:
        async with self._manager_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close()
