from __future__ import annotations

import asyncio
import re
import time

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import apply_stealth, context_kwargs, launch_browser
from app.core.config import Settings
from app.platforms.qr_login_parsers import normalize_image_base64, xhs_status_from_poll
from app.platforms.qr_login_store import QrLoginSession
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import PLATFORM, REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.session import XhsSessionStore

DEFAULT_TTL_SECONDS = 180
VALIDITY_HINT = "小红书二维码约 3 分钟内有效，过期后请重新获取"


class XhsQrLoginTool:
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

    async def open_runtime(self) -> dict:
        playwright = await async_playwright().start()
        browser = await launch_browser(playwright, self.settings, headless=True)
        context = await browser.new_context(**context_kwargs(self.settings))
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return {"playwright": playwright, "browser": browser, "context": context, "page": page}

    async def fetch_qr(self, session: QrLoginSession, runtime: dict) -> None:
        page: Page = runtime["page"]
        create_body: dict | None = None

        async def on_response(resp) -> None:
            nonlocal create_body
            if "login/qrcode/create" not in resp.url:
                return
            try:
                body = await resp.json()
                if body.get("data", {}).get("qr_id"):
                    create_body = body
            except Exception:
                return

        page.on("response", on_response)
        try:
            warmup = self.settings.xhs_explore_url or self.settings.xhs_home_url
            await page.goto(warmup, wait_until="domcontentloaded", timeout=30000)
            for _ in range(20):
                if create_body:
                    break
                await page.wait_for_timeout(500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        if not create_body:
            raise RuntimeError("未能获取小红书登录二维码，请稍后重试或使用 VNC 扫码登录")

        data = create_body.get("data") or {}
        session.qr_id = str(data.get("qr_id") or "")
        session.qr_code = str(data.get("code") or "")
        session.qr_scan_url = data.get("url") or None
        session.qr_image_url = data.get("qr_url") or data.get("image") or None

        img_base64 = data.get("qr_code") or data.get("image_base64")
        if img_base64:
            session.qr_image_base64 = normalize_image_base64(str(img_base64))

        expires_at = None
        scan_url = session.qr_scan_url or ""
        match = re.search(r"timestamp=(\d+)", scan_url)
        if match:
            expires_at = int(match.group(1)) / 1000 + DEFAULT_TTL_SECONDS
        session.expires_at = expires_at or (time.time() + DEFAULT_TTL_SECONDS)
        session.validity_hint = VALIDITY_HINT
        session.status = "pending"
        session.message = "请使用小红书 App 扫码"

    async def poll_once(self, session: QrLoginSession, runtime: dict) -> None:
        if session.expires_at and time.time() >= session.expires_at:
            session.status = "expired"
            session.message = "二维码已过期，请重新获取"
            return

        page: Page = runtime["page"]
        context: BrowserContext = runtime["context"]
        if not session.qr_id or not session.qr_code:
            session.status = "error"
            session.message = "二维码会话缺少 qr_id/code"
            return

        status_body = await page.evaluate(
            """async ({ qrId, code }) => {
                const u = 'https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status?qr_id='
                    + encodeURIComponent(qrId) + '&code=' + encodeURIComponent(code);
                const r = await fetch(u, { credentials: 'include' });
                return await r.json();
            }""",
            {"qrId": session.qr_id, "code": session.qr_code},
        )
        status, message = xhs_status_from_poll(status_body if isinstance(status_body, dict) else {})
        session.status = status
        if message:
            session.message = message

        cookies = await context.cookies()
        cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
        if cookie_names & REQUIRED_LOGIN_COOKIES:
            session.status = "confirmed"
            session.message = "登录成功"
            await self.store.save_from_context(self.tenant_id, context, self.account_id)

    async def cleanup_runtime(self, runtime: dict | None) -> None:
        if not runtime:
            return
        context: BrowserContext | None = runtime.get("context")
        browser: Browser | None = runtime.get("browser")
        playwright: Playwright | None = runtime.get("playwright")
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    async def start_poll_loop(self, session: QrLoginSession) -> None:
        runtime = session.runtime

        async def _loop() -> None:
            try:
                while session.status in {"pending", "scanned"}:
                    await self.poll_once(session, runtime)
                    if session.status in {"confirmed", "expired", "error"}:
                        break
                    await asyncio.sleep(2)
            finally:
                await self.cleanup_runtime(runtime)
                session.runtime = {}

        session.poll_task = asyncio.create_task(_loop())
