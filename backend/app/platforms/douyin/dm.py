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

_DM_BUTTON_SELECTORS = (
    '[data-e2e="user-info-message-btn"]',
    '[data-e2e="user-detail"] button:has-text("私信")',
    '[data-e2e="user-info"] button:has-text("私信")',
    'button:has-text("私信")',
)

_IM_INPUT_SELECTORS = (
    '[data-e2e="im-dialog"] [data-e2e="message-input"]',
    '[data-e2e="im-dialog"] textarea',
    '[data-e2e="im-dialog"] div[contenteditable="true"]',
    '[data-e2e="message-input"]',
)


class DouyinDmTool(DouyinJsApiTool):
    """抖音私信工具（主页点击私信 → im-dialog 弹层内发送）。"""

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
            "capture_method": "profile_im_dialog",
            "message": await self._send_dm_on_profile(page, message),
        }

    @staticmethod
    async def _first_visible(page, selectors: tuple[str, ...]):
        for selector in selectors:
            loc = page.locator(selector)
            count = await loc.count()
            for idx in range(count):
                item = loc.nth(idx)
                try:
                    if await item.is_visible():
                        return item, selector
                except Exception:
                    continue
        return None, None

    async def _open_dm_dialog(self, page) -> dict:
        dm, selector = await self._first_visible(page, _DM_BUTTON_SELECTORS)
        if dm is None:
            clicked = await page.evaluate(
                """() => {
                    const root = document.querySelector('[data-e2e="user-detail"]');
                    if (!root) return false;
                    const btn = Array.from(root.querySelectorAll('button'))
                        .find((el) => (el.textContent || '').includes('私信'));
                    if (!btn) return false;
                    btn.click();
                    return true;
                }"""
            )
            if not clicked:
                return {"ok": False, "error": "dm_button_not_found"}
            selector = "user-detail.button.js_click"
        else:
            await dm.click(force=True)

        try:
            await page.locator('[data-e2e="im-dialog"]').wait_for(state="attached", timeout=15000)
        except Exception:
            return {"ok": False, "error": "im_dialog_not_found", "selector": selector}

        await page.wait_for_timeout(2000)
        return {"ok": True, "selector": selector}

    async def _wait_dm_input(self, page, *, timeout_ms: int = 25000):
        deadline = timeout_ms
        step = 1000
        while deadline > 0:
            inp, selector = await self._first_visible(page, _IM_INPUT_SELECTORS)
            if inp is not None:
                return inp, selector
            await page.wait_for_timeout(step)
            deadline -= step
        return None, None

    @staticmethod
    async def _dialog_hint(page) -> str:
        try:
            dialog = page.locator('[data-e2e="im-dialog"]').first
            if not await dialog.count():
                return ""
            text = await dialog.inner_text()
            for hint in ("无法私信", "互相关注", "隐私", "未开启私信", "加载中"):
                if hint in text:
                    return text[:200]
            return text[:200]
        except Exception:
            return ""

    async def _send_dm_on_profile(self, page, message: str) -> dict:
        opened = await self._open_dm_dialog(page)
        if not opened.get("ok"):
            return opened

        inp, input_selector = await self._wait_dm_input(page)
        if inp is None:
            hint = await self._dialog_hint(page)
            return {
                "ok": False,
                "error": "dm_input_not_found",
                "hint": hint or "私信弹层已打开但未出现输入框，可能受隐私/互关限制",
                "dm_selector": opened.get("selector"),
            }

        await inp.click()
        await inp.fill(message)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        dialog = page.locator('[data-e2e="im-dialog"]').first
        dialog_text = await dialog.inner_text() if await dialog.count() else ""
        visible = message in dialog_text
        return {
            "ok": visible,
            "method": "profile_im_dialog",
            "dm_selector": opened.get("selector"),
            "input_selector": input_selector,
            "verified_in_dialog": visible,
            "text_preview": message[:80],
            "dialog_snippet": dialog_text[:200],
        }
