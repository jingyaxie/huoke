from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.session_store import PlatformSessionStore

PROFILE_PATH = "/aweme/v1/web/user/profile/other/"


def build_profile_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"


def build_im_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/im?secUid={sec_uid}"


class DouyinProfileTool(DouyinJsApiTool):
    """抖音用户主页导航与 profile API。"""

    async def open_profile(self, page, sec_uid: str, *, wait_ms: int = 5000) -> str:
        profile_url = build_profile_url(sec_uid)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(wait_ms)
        return profile_url

    async def fetch_profile(self, page, template_url: str, sec_uid: str) -> dict:
        url = self.build_api_url(template_url, PROFILE_PATH, extra={"sec_user_id": sec_uid})
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)
