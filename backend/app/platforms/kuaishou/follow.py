from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import FOLLOW_PATH, PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import _build_follow_body
from app.platforms.kuaishou.profile import KuaishouProfileTool
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouFollowTool(KuaishouJsApiTool):
    """快手关注用户工具（主页上下文 + JS POST）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = KuaishouProfileTool(settings, tenant_id, self.store, account_id=account_id)

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

        follow_status_before = await self._detect_follow_status(page)

        result: dict = {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": username,
            "user_id": user_id,
            "profile_url": profile_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "follow_status_before": follow_status_before,
            "capture_method": "thin_nav_js",
            "follow": await self._commit_follow(
                page,
                template_url,
                user_id=user_id,
                follow_status_before=follow_status_before,
            ),
        }
        result["follow_status_after"] = await self._detect_follow_status(page)
        return result

    async def _detect_follow_status(self, page) -> str:
        try:
            body_text = await page.evaluate("() => document.body.innerText || ''")
        except Exception:
            return "unknown"
        if any(label in body_text for label in ("已关注", "互相关注", "发私信")):
            return "followed"
        if "关注" in body_text:
            return "none"
        return "unknown"

    async def _commit_follow(
        self,
        page,
        template_url: str,
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

        url = self.build_api_url(template_url, FOLLOW_PATH)
        body = _build_follow_body(user_id)
        data = await self.post_json_via_page(page, url, body, timeout_ms=12000)
        result_code = int(data.get("result") or -1)
        if result_code == 1:
            return {
                "ok": True,
                "skipped": False,
                "result": result_code,
                "status_msg": "",
            }

        ui_result = await self._follow_via_ui(page)
        if ui_result.get("ok"):
            return ui_result

        last_error = data.get("error_id") or data.get("error") or data.get("raw") or f"result={result_code}"
        if result_code == 109:
            last_error = "login_required"
        return {"ok": False, "skipped": False, "error": last_error, "ui": ui_result}

    async def _follow_via_ui(self, page) -> dict:
        btn = page.locator('button:has-text("关注")').first
        if not await btn.count():
            return {"ok": False, "error": "follow_button_not_found"}
        try:
            await btn.click()
            await page.wait_for_timeout(2000)
            followed = await self._detect_follow_status(page) == "followed"
            return {"ok": followed, "method": "profile_ui", "verified_in_page": followed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
