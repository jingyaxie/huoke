from __future__ import annotations

from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import _build_user_otherinfo_url


def build_profile_url(user_id: str) -> str:
    return f"https://www.xiaohongshu.com/user/profile/{user_id}"


class XhsProfileTool(XhsJsApiTool):
    """小红书用户主页导航与 profile API。"""

    async def open_profile(self, page, user_id: str, *, wait_ms: int = 5000) -> str:
        profile_url = build_profile_url(user_id)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(wait_ms)
        return profile_url

    async def fetch_user_info(self, page, template_url: str, user_id: str) -> dict:
        url = _build_user_otherinfo_url(template_url, user_id)
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)
