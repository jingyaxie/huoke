from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.antibot import headless_for_platform, human_delay, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import GRAPHQL_PATH, PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import (
    COMMENT_ADD_MUTATION,
    COMMENT_ADD_OPERATION,
    COMMENT_LIST_OPERATION,
    COMMENT_LIST_QUERY,
    VIDEO_DETAIL_OPERATION,
    VIDEO_DETAIL_QUERY,
)
from app.platforms.kuaishou.utils import (
    extract_photo_id,
    find_comment_author_id,
    normalize_ks_comment,
    parse_video_detail,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


def _walk_photo_author_id(node: Any, photo_id: str) -> str | None:
    if isinstance(node, dict):
        current_photo = str(
            node.get("photoId")
            or node.get("photo_id")
            or node.get("id")
            or ""
        )
        if current_photo == photo_id:
            author = node.get("author")
            if isinstance(author, dict):
                author_id = author.get("id") or author.get("authorId")
                if author_id:
                    return str(author_id)
            for key in ("photoAuthorId", "authorId"):
                value = node.get(key)
                if value:
                    return str(value)
        for value in node.values():
            found = _walk_photo_author_id(value, photo_id)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_photo_author_id(item, photo_id)
            if found:
                return found
    return None


class KuaishouReplyCommentTool(KuaishouJsApiTool):
    """快手：预热登录态 → 打开视频页 → GraphQL visionAddComment 回复评论。"""

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        video_url: str,
        photo_id: str | None = None,
        photo_author_id: str | None = None,
        reply_to_user_id: str | None = None,
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not comment_id:
            raise ValueError("缺少 comment_id")
        if not reply_text.strip():
            raise ValueError("缺少 reply_text")
        if not video_url:
            raise ValueError("缺少 video_url")

        resolved_photo_id = photo_id or extract_photo_id(video_url)
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
                photo_id=resolved_photo_id,
                comment_id=comment_id,
                reply_text=reply_text.strip(),
                video_url=video_url,
                photo_author_id=photo_author_id,
                reply_to_user_id=reply_to_user_id,
            )

        output = (
            self.settings.report_output_dir
            / f"reply_comment_{self.platform}_{self.tenant_id}_{comment_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _fetch_video_detail(self, page, photo_id: str) -> dict[str, str | None]:
        data = await self.graphql_via_page(
            page,
            operation_name=VIDEO_DETAIL_OPERATION,
            query=VIDEO_DETAIL_QUERY,
            variables={"photoId": photo_id},
            timeout_ms=12000,
        )
        return parse_video_detail(data)

    async def _resolve_reply_to_user_id(
        self,
        page,
        *,
        photo_id: str,
        comment_id: str,
        reply_to_user_id: str | None,
    ) -> str | None:
        if reply_to_user_id:
            return str(reply_to_user_id)

        pcursor = ""
        guard = 0
        while guard < 10:
            guard += 1
            data = await self.graphql_via_page(
                page,
                operation_name=COMMENT_LIST_OPERATION,
                query=COMMENT_LIST_QUERY,
                variables={"photoId": photo_id, "pcursor": pcursor},
                timeout_ms=12000,
            )
            vision = (data.get("data") or {}).get("visionCommentList") or {}
            rows = [normalize_ks_comment(item) for item in vision.get("rootCommentsV2") or []]
            author_id = find_comment_author_id(rows, comment_id)
            if author_id:
                return author_id
            pcursor = str(vision.get("pcursor") or "")
            if not pcursor:
                break
        return None

    async def _reply_on_page(
        self,
        page,
        *,
        photo_id: str,
        comment_id: str,
        reply_text: str,
        video_url: str,
        photo_author_id: str | None,
        reply_to_user_id: str | None,
    ) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)

        detail = await self._fetch_video_detail(page, photo_id)
        resolved_author_id = photo_author_id or detail.get("photo_author_id")
        exp_tag = detail.get("exp_tag") or ""
        if not resolved_author_id:
            return await self._failure_result(
                page=page,
                photo_id=photo_id,
                comment_id=comment_id,
                reply_text=reply_text,
                video_url=video_url,
                error="无法解析 photoAuthorId，请传入 photo_author_id 参数",
                capture_method="video_page_js_graphql",
            )

        resolved_reply_to = await self._resolve_reply_to_user_id(
            page,
            photo_id=photo_id,
            comment_id=comment_id,
            reply_to_user_id=reply_to_user_id,
        )
        if not resolved_reply_to:
            return await self._failure_result(
                page=page,
                photo_id=photo_id,
                comment_id=comment_id,
                reply_text=reply_text,
                video_url=video_url,
                error="无法解析被回复评论作者 user_id，请确认 comment_id 或传入 reply_to_user_id",
                capture_method="video_page_js_graphql",
                extra={"photo_author_id": resolved_author_id},
            )

        variables = {
            "photoId": photo_id,
            "photoAuthorId": str(resolved_author_id),
            "content": reply_text,
            "replyToCommentId": comment_id,
            "replyTo": str(resolved_reply_to),
            "expTag": exp_tag,
        }
        data = await self.graphql_via_page(
            page,
            operation_name=COMMENT_ADD_OPERATION,
            query=COMMENT_ADD_MUTATION,
            variables=variables,
            timeout_ms=12000,
        )
        payload = (data.get("data") or {}).get("visionAddComment") or {}
        comment_id_out = payload.get("commentId") or payload.get("comment_id")
        status = str(payload.get("status") or "")
        result_code = payload.get("result")
        ok = (
            (status == "success" or result_code == 1)
            and bool(comment_id_out)
            and not data.get("errors")
        )
        reply_result: dict[str, Any] = {
            "ok": ok,
            "photo_author_id": str(resolved_author_id),
            "reply_to_user_id": str(resolved_reply_to),
            "exp_tag": exp_tag,
            "comment_id_out": comment_id_out,
            "result": result_code,
            "status": status,
            "payload": payload,
        }
        if not ok:
            errors = data.get("errors") or []
            reply_result["error"] = (
                errors[0].get("message")
                if errors
                else payload.get("message")
                or data.get("error")
                or data.get("raw")
                or f"result={result_code}, status={status}"
            )

        capture_method = "video_page_js_graphql"
        if not ok:
            ui_result = await self._reply_via_ui(
                page,
                comment_id=comment_id,
                reply_text=reply_text,
            )
            capture_method = "video_page_ui"
            if ui_result.get("ok"):
                reply_result = {**reply_result, **ui_result, "ok": True}
            else:
                reply_result["ui"] = ui_result

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": "reply_comment",
            "photo_id": photo_id,
            "comment_id": comment_id,
            "reply_text": reply_text,
            "video_url": video_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "capture_method": capture_method,
            "reply": reply_result,
        }

    async def _reply_via_ui(self, page, *, comment_id: str, reply_text: str) -> dict[str, Any]:
        for selector in ('span:has-text("评论")', 'div:has-text("条评论")'):
            loc = page.locator(selector).first
            try:
                if await loc.count() > 0:
                    await loc.click(force=True, timeout=800)
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                    break
            except Exception:
                continue

        reply_btn = page.locator('[class*="reply"], button:has-text("回复")').first
        if not await reply_btn.count():
            return {"ok": False, "error": "未找到回复按钮", "method": "ui"}

        post_result: dict[str, Any] = {"ok": False}

        async def on_response(resp) -> None:
            nonlocal post_result
            try:
                if GRAPHQL_PATH not in resp.url:
                    return
                post = resp.request.post_data or ""
                if COMMENT_ADD_OPERATION not in post:
                    return
                body = await resp.json()
            except Exception:
                return
            payload = (body.get("data") or {}).get("visionAddComment") or {}
            if payload.get("status") == "success" or payload.get("result") == 1:
                post_result = {
                    "ok": True,
                    "comment_id_out": payload.get("commentId"),
                    "payload": payload,
                    "method": "ui",
                }

        page.on("response", on_response)
        try:
            await reply_btn.click(force=True)
            await page.wait_for_timeout(1000)
            input_loc = page.locator(
                '[class*="comment"] [contenteditable="true"], textarea, input[placeholder*="评论"]'
            ).last
            if not await input_loc.count():
                return {"ok": False, "error": "未找到回复输入框", "method": "ui"}
            await input_loc.click()
            await input_loc.fill(reply_text)
            await page.wait_for_timeout(400)
            send_btn = page.locator('button:has-text("发送"), span:has-text("发送"), div:has-text("发布")').last
            if not await send_btn.count():
                return {"ok": False, "error": "未找到发送按钮", "method": "ui"}
            await send_btn.click(force=True)
            for _ in range(20):
                if post_result.get("ok"):
                    return post_result
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
        page,
        photo_id: str,
        comment_id: str,
        reply_text: str,
        video_url: str,
        error: str,
        capture_method: str,
        extra: dict | None = None,
    ) -> dict:
        reply_result: dict[str, Any] = {"ok": False, "error": error}
        if extra:
            reply_result.update(extra)
        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "action": "reply_comment",
            "photo_id": photo_id,
            "comment_id": comment_id,
            "reply_text": reply_text,
            "video_url": video_url,
            "page_url": page.url,
            "page_title": await page.title(),
            "capture_method": capture_method,
            "reply": reply_result,
        }
