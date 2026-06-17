from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

PLATFORM = "douyin"
FOLLOW_PATH = "/aweme/v1/web/commit/follow/user/"


def _is_followed_status(follow_status: int) -> bool:
    """follow_status: 0=未关注, 1=已关注, 2=互相关注"""
    return int(follow_status or 0) in {1, 2}


class DouyinFollowTool(DouyinJsApiTool):
    """抖音关注/取消关注用户工具（主页上下文 + JS POST）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = DouyinProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def follow_user(
        self,
        *,
        sec_uid: str,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._run_relation_action(
            sec_uid=sec_uid,
            user_id=user_id,
            username=username,
            show_browser=show_browser,
            action="follow",
        )

    async def unfollow_user(
        self,
        *,
        sec_uid: str,
        user_id: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        return await self._run_relation_action(
            sec_uid=sec_uid,
            user_id=user_id,
            username=username,
            show_browser=show_browser,
            action="unfollow",
        )

    async def _run_relation_action(
        self,
        *,
        sec_uid: str,
        user_id: str,
        username: str,
        show_browser: bool,
        action: str,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not sec_uid:
            raise ValueError("缺少 sec_uid")
        if not user_id:
            raise ValueError("操作需要 user_id")

        headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
        ) as (_, page):
            result = await self._relation_on_page(
                page,
                sec_uid=sec_uid,
                user_id=user_id,
                username=username,
                action=action,
            )

        prefix = "follow" if action == "follow" else "unfollow"
        output = (
            self.settings.report_output_dir
            / f"{prefix}_{self.platform}_{self.tenant_id}_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _relation_on_page(
        self,
        page,
        *,
        sec_uid: str,
        user_id: str,
        username: str,
        action: str,
    ) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        template_url = await self.pick_api_template_url(page, captured_urls)
        profile_url = await self._profile.open_profile(page, sec_uid)

        profile_data = await self._profile.fetch_profile(page, template_url, sec_uid)
        user = profile_data.get("user") or {}
        follow_status_before = int(user.get("follow_status") or 0)

        if action == "follow":
            relation_result = await self._commit_follow(
                page,
                template_url,
                sec_uid=sec_uid,
                user_id=user_id,
                follow_status_before=follow_status_before,
            )
        else:
            relation_result = await self._commit_unfollow(
                page,
                template_url,
                sec_uid=sec_uid,
                user_id=user_id,
                follow_status_before=follow_status_before,
            )

        result: dict = {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": action,
            "username": username or user.get("nickname") or "",
            "user_id": user_id,
            "sec_uid": sec_uid,
            "profile_url": profile_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "follow_status_before": follow_status_before,
            "capture_method": "thin_nav_js",
            action: relation_result,
        }
        profile_after = await self._profile.fetch_profile(page, template_url, sec_uid)
        result["follow_status_after"] = int((profile_after.get("user") or {}).get("follow_status") or 0)
        return result

    async def _commit_follow(
        self,
        page,
        template_url: str,
        *,
        sec_uid: str,
        user_id: str,
        follow_status_before: int,
    ) -> dict:
        if _is_followed_status(follow_status_before):
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_followed",
                "follow_status": follow_status_before,
            }

        return await self._commit_relation_api(
            page,
            template_url,
            sec_uid=sec_uid,
            user_id=user_id,
            relation_type="1",
        )

    async def _commit_unfollow(
        self,
        page,
        template_url: str,
        *,
        sec_uid: str,
        user_id: str,
        follow_status_before: int,
    ) -> dict:
        if not _is_followed_status(follow_status_before):
            return {
                "ok": True,
                "skipped": True,
                "reason": "not_followed",
                "follow_status": follow_status_before,
            }

        return await self._commit_relation_api(
            page,
            template_url,
            sec_uid=sec_uid,
            user_id=user_id,
            relation_type="0",
        )

    async def _commit_relation_api(
        self,
        page,
        template_url: str,
        *,
        sec_uid: str,
        user_id: str,
        relation_type: str,
    ) -> dict:
        body = urlencode({"type": relation_type, "user_id": user_id, "sec_user_id": sec_uid})
        last_error = "relation_failed"
        for host in ("www-hj.douyin.com", "www.douyin.com"):
            url = self.build_api_url(template_url, FOLLOW_PATH, host=host)
            data = await self.post_form_via_page(page, url, body, timeout_ms=12000)
            status_code = data.get("status_code")
            if status_code == 0:
                return {
                    "ok": True,
                    "skipped": False,
                    "host": host,
                    "status_code": status_code,
                    "follow_status": data.get("follow_status"),
                    "status_msg": data.get("status_msg") or "",
                }
            last_error = (
                data.get("status_msg")
                or data.get("error")
                or data.get("raw")
                or f"status_code={status_code}"
            )
        return {"ok": False, "skipped": False, "error": last_error}
