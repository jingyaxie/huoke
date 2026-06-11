from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import PLATFORM, _build_follow_url
from app.platforms.xiaohongshu.profile import XhsProfileTool
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.services.playwright_pool import PlaywrightPool


class XhsFollowTool(XhsJsApiTool):
    """小红书关注用户工具（主页上下文 + JS POST）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = XhsProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def follow_user(
        self,
        *,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not user_id:
            raise ValueError("关注需要 user_id")

        headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
            account_id=self.account_id,
        ) as (_, page):
            result = await self._follow_on_page(page, user_id=user_id, username=username)

        output = (
            self.settings.report_output_dir
            / f"follow_{self.platform}_{self.tenant_id}_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _follow_on_page(self, page, *, user_id: str, username: str) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        template_url = await self.pick_api_template_url(page, captured_urls)
        profile_url = await self._profile.open_profile(page, user_id)

        profile_data = await self._profile.fetch_user_info(page, template_url, user_id)
        inner = profile_data.get("data") if isinstance(profile_data.get("data"), dict) else profile_data
        basic = inner.get("basic_info") or inner.get("user") or inner
        follow_status_before = self._parse_follow_status(basic)

        result: dict = {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": username or basic.get("nickname") or basic.get("nick_name") or "",
            "user_id": user_id,
            "profile_url": profile_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "follow_status_before": follow_status_before,
            "capture_method": "thin_nav_js",
            "follow": await self._commit_follow(
                page,
                user_id=user_id,
                follow_status_before=follow_status_before,
            ),
        }
        profile_after = await self._profile.fetch_user_info(page, template_url, user_id)
        inner_after = profile_after.get("data") if isinstance(profile_after.get("data"), dict) else profile_after
        basic_after = inner_after.get("basic_info") or inner_after.get("user") or inner_after
        result["follow_status_after"] = self._parse_follow_status(basic_after)
        return result

    @staticmethod
    def _parse_follow_status(user: dict) -> str:
        if not isinstance(user, dict):
            return "unknown"
        for key in ("followed", "is_followed", "follow_status"):
            value = user.get(key)
            if value is True or value in {1, "1", "followed"}:
                return "followed"
            if value is False or value in {0, "0", "none"}:
                return "none"
        return str(user.get("follow_status") or "unknown")

    async def _commit_follow(
        self,
        page,
        *,
        user_id: str,
        follow_status_before: str,
    ) -> dict:
        if follow_status_before == "followed":
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_followed",
                "follow_status": follow_status_before,
            }

        url = _build_follow_url()
        data = await self.post_json_via_page(page, url, {"target_user_id": user_id}, timeout_ms=12000)
        code = data.get("code")
        success = data.get("success")
        if code == 0 or success is True:
            return {
                "ok": True,
                "skipped": False,
                "code": code,
                "success": success,
                "msg": data.get("msg") or "",
            }

        ui_result = await self._follow_via_ui(page)
        if ui_result.get("ok"):
            return ui_result

        last_error = data.get("msg") or data.get("error") or data.get("raw") or f"code={code}"
        return {"ok": False, "skipped": False, "error": last_error, "ui": ui_result}

    async def _follow_via_ui(self, page) -> dict:
        btn = page.locator('button:has-text("关注")').first
        if not await btn.count():
            return {"ok": False, "error": "follow_button_not_found"}
        try:
            await btn.click()
            await page.wait_for_timeout(2000)
            body_text = await page.evaluate("() => document.body.innerText || ''")
            followed = any(label in body_text for label in ("已关注", "互相关注", "发消息"))
            return {"ok": followed, "method": "profile_ui", "verified_in_page": followed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
