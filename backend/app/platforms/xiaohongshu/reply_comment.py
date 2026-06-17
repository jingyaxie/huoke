from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.antibot import headless_for_platform, human_delay, human_scroll, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import COMMENT_POST_PATH, PLATFORM, _build_comment_post_url
from app.platforms.xiaohongshu.profile import XhsProfileTool
from app.platforms.xiaohongshu.ui_helpers import ensure_logged_in_user
from app.platforms.xiaohongshu.utils import (
    build_note_url,
    extract_note_access_params,
    extract_note_id,
    parse_note_card,
)
from app.services.playwright_pool import PlaywrightPool


class XhsReplyCommentTool(XhsJsApiTool):
    """小红书：激活登录态 → 刷新笔记链接 → API/UI 回复指定评论。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = XhsProfileTool(settings, tenant_id, self.store, account_id=account_id)

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
                note_url=note_url,
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
        await self.warmup_for_js_api(page, captured_urls)
        login = await ensure_logged_in_user(page)
        if not login.get("ok"):
            from app.platforms.xiaohongshu.session_meta import mark_session_expired

            prep = login.get("prep") if isinstance(login.get("prep"), dict) else {}
            user_me = prep.get("user_me") if isinstance(prep.get("user_me"), dict) else {}
            reason = "guest" if user_me.get("guest") is True else "live_verify_failed"
            mark_session_expired(
                self.store,
                self.tenant_id,
                self.account_id,
                reason=reason,
                detail=str(login.get("error") or ""),
            )
            return await self._failure_result(
                note_id=note_id,
                comment_id=comment_id,
                reply_text=reply_text,
                note_url=note_url,
                page=page,
                error=str(login.get("error") or "login_required"),
                capture_method="login_check",
                extra={"login": login},
            )

        template_url = await self.pick_api_template_url(page, captured_urls)
        open_url = await self._resolve_note_open_url(page, note_id=note_id, note_url=note_url, template_url=template_url)
        page_ready = await self._open_note_page(page, open_url)
        if not page_ready.get("ok"):
            return await self._failure_result(
                note_id=note_id,
                comment_id=comment_id,
                reply_text=reply_text,
                note_url=open_url,
                page=page,
                error=str(page_ready.get("error") or "note_page_unavailable"),
                capture_method="note_page",
                extra={"page_ready": page_ready, "login": login},
            )

        reply_result = await self._reply_via_api(
            page,
            note_id=note_id,
            comment_id=comment_id,
            reply_text=reply_text,
            referer=page.url,
        )
        capture_method = "note_page_js_api_signed"
        if not reply_result.get("ok"):
            await self._scroll_to_comment(page, comment_id)
            ui_result = await self._reply_via_ui(page, comment_id=comment_id, reply_text=reply_text)
            capture_method = "note_page_ui"
            if ui_result.get("ok"):
                reply_result = ui_result
            else:
                reply_result = {
                    **reply_result,
                    "ui": ui_result,
                    "error": reply_result.get("error") or ui_result.get("error") or "reply_failed",
                }

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": "reply_comment",
            "note_id": note_id,
            "comment_id": comment_id,
            "reply_text": reply_text,
            "note_url": open_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "capture_method": capture_method,
            "login_user_id": login.get("user_id"),
            "reply": reply_result,
        }

    async def _resolve_note_open_url(
        self,
        page,
        *,
        note_id: str,
        note_url: str,
        template_url: str,
    ) -> str:
        access = extract_note_access_params(note_url)
        if access.get("xsec_token"):
            return note_url

        raw_self = await self._profile.fetch_self_info(page, template_url)
        data = raw_self.get("data") if isinstance(raw_self.get("data"), dict) else raw_self
        basic = data.get("basic_info") or data.get("user") or data if isinstance(data, dict) else {}
        user_id = str(basic.get("user_id") or basic.get("id") or "")
        if not user_id:
            return note_url

        raw_notes = await self._profile.fetch_self_notes(page, template_url, user_id, limit=30)
        notes = (raw_notes.get("data") or {}).get("notes") or (raw_notes.get("data") or {}).get("items") or []
        for index, item in enumerate(notes):
            if not isinstance(item, dict):
                continue
            parsed = parse_note_card(item, rank=index + 1, tenant_id=self.tenant_id)
            if parsed and parsed.get("external_id") == note_id:
                return str(parsed.get("video_url") or note_url)

        return build_note_url(note_id, access.get("xsec_token"), access.get("xsec_source"))

    async def _open_note_page(self, page, note_url: str) -> dict[str, Any]:
        await page.goto(note_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        await human_scroll(page, self.settings, tenant_id=self.tenant_id)

        current_url = page.url
        title = await page.title()
        if "/404" in current_url or "页面不见了" in title or "暂时无法浏览" in current_url:
            return {
                "ok": False,
                "error": "笔记链接已失效(xsec_token 过期或不可访问)，请重新抓取评论以更新链接",
                "page_url": current_url,
                "page_title": title,
            }
        return {"ok": True, "page_url": current_url, "page_title": title}

    async def _scroll_to_comment(self, page, comment_id: str) -> None:
        selector = f"#comment-{comment_id}"
        for _ in range(12):
            if await page.locator(selector).count():
                await page.locator(selector).first.scroll_into_view_if_needed(timeout=5000)
                await page.wait_for_timeout(500)
                return
            await human_scroll(page, self.settings, tenant_id=self.tenant_id)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="scroll")

    async def _reply_via_api(
        self,
        page,
        *,
        note_id: str,
        comment_id: str,
        reply_text: str,
        referer: str,
    ) -> dict[str, Any]:
        payload = {
            "note_id": note_id,
            "content": reply_text,
            "at_users": [],
            "target_comment_id": comment_id,
        }
        data = await self.post_signed_json_via_page(
            page,
            COMMENT_POST_PATH,
            payload,
            timeout_ms=12000,
            referer=referer,
        )
        code = data.get("code")
        success = data.get("success")
        ok = code == 0 or success is True
        result = {
            "ok": ok,
            "code": code,
            "success": success,
            "msg": data.get("msg") or data.get("message") or "",
            "data": data.get("data") or {},
            "http_status": data.get("status"),
        }
        if not ok:
            result["error"] = result["msg"] or data.get("error") or data.get("raw") or f"code={code}"
        return result

    async def _reply_via_ui(self, page, *, comment_id: str, reply_text: str) -> dict[str, Any]:
        selector = f"#comment-{comment_id}"
        comment = page.locator(selector).first
        if not await comment.count():
            return {"ok": False, "error": f"页面未找到评论节点 {comment_id}"}

        reply_btn = comment.locator(".reply.icon-container").first
        if not await reply_btn.count():
            return {"ok": False, "error": "未找到回复按钮"}
        await reply_btn.click()
        await page.wait_for_timeout(1200)

        input_loc = page.locator(
            'div.content-input [contenteditable="true"], textarea[placeholder*="评论"], textarea'
        ).last
        if not await input_loc.count():
            return {"ok": False, "error": "未找到回复输入框"}
        await input_loc.click()
        await input_loc.fill(reply_text)
        await page.wait_for_timeout(400)

        post_result: dict[str, Any] = {"ok": False}

        async def on_response(resp) -> None:
            nonlocal post_result
            if "/comment/post" not in resp.url:
                return
            try:
                body = await resp.json()
            except Exception:
                return
            code = body.get("code")
            success = body.get("success")
            if code == 0 or success is True:
                post_result = {"ok": True, "code": code, "success": success, "data": body.get("data") or {}}

        page.on("response", on_response)
        try:
            send_btn = page.locator('button:has-text("发送"), div.btn:has-text("发送"), span:has-text("发送")').last
            if not await send_btn.count():
                return {"ok": False, "error": "未找到发送按钮"}
            await send_btn.click()
            for _ in range(20):
                if post_result.get("ok"):
                    return {**post_result, "method": "ui"}
                await page.wait_for_timeout(500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        return {"ok": False, "error": "UI 回复后未捕获成功响应", "method": "ui"}

    async def _failure_result(
        self,
        *,
        note_id: str,
        comment_id: str,
        reply_text: str,
        note_url: str,
        page,
        error: str,
        capture_method: str,
        extra: dict | None = None,
    ) -> dict:
        reply_result = {"ok": False, "error": error}
        if extra:
            reply_result.update(extra)
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
            "capture_method": capture_method,
            "reply": reply_result,
        }
