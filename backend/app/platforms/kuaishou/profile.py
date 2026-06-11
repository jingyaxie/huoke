from __future__ import annotations

from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.utils import build_profile_url


class KuaishouProfileTool(KuaishouJsApiTool):
    """快手用户主页导航。"""

    async def open_profile(self, page, user_id: str, *, wait_ms: int = 5000) -> str:
        profile_url = build_profile_url(user_id)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(wait_ms)
        return profile_url
