from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlencode

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.js_constants import COMMENT_PUBLISH_PATH, PLATFORM, _extract_aweme_id
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class DouyinReplyCommentTool(DouyinJsApiTool):
    """抖音：打开视频页预热签名，经 comment/publish 接口回复指定评论。"""

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        content_url: str,
        aweme_id: str | None = None,
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not comment_id:
            raise ValueError("缺少 comment_id")
        if not reply_text.strip():
            raise ValueError("缺少 reply_text")
        if not content_url:
            raise ValueError("缺少 content_url")

        resolved_aweme_id = aweme_id or _extract_aweme_id(content_url)
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
            result = await self._reply_on_page(
                page,
                aweme_id=resolved_aweme_id,
                comment_id=comment_id,
                reply_text=reply_text.strip(),
                content_url=content_url,
            )

        output = (
            self.settings.report_output_dir
            / f"reply_comment_{self.platform}_{self.tenant_id}_{comment_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _reply_on_page(
        self,
        page,
        *,
        aweme_id: str,
        comment_id: str,
        reply_text: str,
        content_url: str,
    ) -> dict:
        captured_urls: list[str] = []

        async def on_response(resp) -> None:
            try:
                url = resp.url
                if "douyin.com/aweme/v1/web/" in url:
                    captured_urls.append(url)
            except Exception:
                return

        page.on("response", on_response)
        try:
            await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        template_url = await self.pick_api_template_url(page, captured_urls)
        body = urlencode(
            {
                "aweme_id": aweme_id,
                "text": reply_text,
                "reply_id": comment_id,
                "text_extra": "",
                "is_self_see": "0",
                "reply_to_reply_id": "0",
            }
        )

        last_error = "comment_publish_failed"
        reply_result: dict | None = None
        for host in ("www-hj.douyin.com", "www.douyin.com"):
            api_url = self.build_api_url(template_url, COMMENT_PUBLISH_PATH, host=host)
            data = await self.post_form_via_page(page, api_url, body, timeout_ms=12000)
            status_code = data.get("status_code")
            if status_code == 0:
                reply_result = {
                    "ok": True,
                    "host": host,
                    "status_code": status_code,
                    "status_msg": data.get("status_msg") or "",
                    "comment": data.get("comment") or {},
                }
                break
            last_error = (
                data.get("status_msg")
                or data.get("error")
                or data.get("raw")
                or f"status_code={status_code}"
            )

        if reply_result is None:
            reply_result = {"ok": False, "error": last_error}

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": "reply_comment",
            "aweme_id": aweme_id,
            "comment_id": comment_id,
            "reply_text": reply_text,
            "content_url": content_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "capture_method": "video_page_js_api",
            "reply": reply_result,
        }
