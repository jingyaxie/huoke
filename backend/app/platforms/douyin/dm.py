from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

PLATFORM = "douyin"


class DouyinDmTool(DouyinJsApiTool):
    """抖音私信工具（主页打开 IM 面板 + 轻量 UI 发送）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = DouyinProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def send_message(
        self,
        *,
        sec_uid: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not sec_uid:
            raise ValueError("缺少 sec_uid")
        if not (message or "").strip():
            raise ValueError("发送私信需要 message")

        headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
        ) as (_, page):
            result = await self._send_on_page(page, sec_uid=sec_uid, message=message, username=username)

        output = (
            self.settings.report_output_dir
            / f"dm_{self.platform}_{self.tenant_id}_{sec_uid[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _send_on_page(self, page, *, sec_uid: str, message: str, username: str) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        profile_url = await self._profile.open_profile(page, sec_uid)
        template_url = await self.pick_api_template_url(page, captured_urls)
        profile_data = await self._profile.fetch_profile(page, template_url, sec_uid)
        user = profile_data.get("user") or {}

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": username or user.get("nickname") or "",
            "user_id": str(user.get("uid") or ""),
            "sec_uid": sec_uid,
            "profile_url": profile_url,
            "page_url": page.url,
            "capture_method": "profile_dm_panel",
            "message": await self._send_dm_on_profile(page, message),
        }

    async def _send_dm_on_profile(self, page, message: str) -> dict:
        dm = page.locator('[data-e2e="user-info"] button:has-text("私信")').first
        if not await dm.count():
            dm = page.locator('button:has-text("私信")').last
        if not await dm.count():
            return {"ok": False, "error": "dm_button_not_found"}

        await dm.click()
        await page.wait_for_timeout(2500)

        inp = page.locator('[data-e2e="message-input"], textarea, div[contenteditable="true"]').first
        if not await inp.count():
            return {
                "ok": False,
                "error": "dm_input_not_found",
                "hint": "私信面板未打开，可能受隐私/互关限制",
            }

        await inp.click()
        await inp.fill(message)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        body_text = await page.evaluate("() => document.body.innerText || ''")
        visible = message in body_text
        return {
            "ok": visible,
            "method": "profile_dm_panel",
            "verified_in_page": visible,
            "text_preview": message[:80],
        }
