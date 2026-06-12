from __future__ import annotations

import json
from datetime import datetime

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import PLATFORM, _build_comment_post_url
from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, extract_note_id
from app.services.playwright_pool import PlaywrightPool


class XhsReplyCommentTool(XhsJsApiTool):
    """小红书：打开笔记页预热签名，经 comment/post 接口回复指定评论。"""

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        note_url: str,
        note_id: str | None = None,
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not comment_id:
            raise ValueError("缺少 comment_id")
        if not reply_text.strip():
            raise ValueError("缺少 reply_text")
        if not note_url:
            raise ValueError("缺少 note_url")

        resolved_note_id = note_id or extract_note_id(note_url)
        access = extract_note_access_params(note_url)
        open_url = note_url
        if access.get("xsec_token") and "xsec_token=" not in note_url:
            open_url = build_note_url(
                resolved_note_id,
                access.get("xsec_token"),
                access.get("xsec_source"),
            )

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
                note_id=resolved_note_id,
                comment_id=comment_id,
                reply_text=reply_text.strip(),
                note_url=open_url,
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
        note_id: str,
        comment_id: str,
        reply_text: str,
        note_url: str,
    ) -> dict:
        captured_urls: list[str] = []

        async def on_response(resp) -> None:
            try:
                url = resp.url
                if "xiaohongshu.com/api/sns" in url or "edith.xiaohongshu.com" in url:
                    captured_urls.append(url)
            except Exception:
                return

        page.on("response", on_response)
        try:
            await page.goto(note_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        payload = {
            "note_id": note_id,
            "content": reply_text,
            "at_users": [],
            "target_comment_id": comment_id,
        }
        post_url = _build_comment_post_url()
        data = await self.post_json_via_page(
            page,
            post_url,
            payload,
            timeout_ms=12000,
        )
        code = data.get("code")
        success = data.get("success")
        ok = code == 0 or success is True
        reply_result = {
            "ok": ok,
            "code": code,
            "success": success,
            "msg": data.get("msg") or data.get("message") or "",
            "data": data.get("data") or {},
        }
        if not ok:
            reply_result["error"] = reply_result["msg"] or data.get("error") or data.get("raw") or f"code={code}"

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": "reply_comment",
            "note_id": note_id,
            "comment_id": comment_id,
            "reply_text": reply_text,
            "note_url": note_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "capture_method": "note_page_js_api",
            "reply": reply_result,
        }
