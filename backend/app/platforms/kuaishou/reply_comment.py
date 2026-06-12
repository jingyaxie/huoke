from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import GRAPHQL_PATH, PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import (
    COMMENT_ADD_MUTATION,
    COMMENT_ADD_OPERATION,
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
    """快手：打开视频页解析作者 ID，经 GraphQL visionAddComment 回复评论。"""

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        video_url: str,
        photo_id: str | None = None,
        photo_author_id: str | None = None,
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not comment_id:
            raise ValueError("缺少 comment_id")
        if not reply_text.strip():
            raise ValueError("缺少 reply_text")
        if not video_url:
            raise ValueError("缺少 video_url")

        from app.platforms.kuaishou.utils import extract_photo_id

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
        photo_id: str,
        comment_id: str,
        reply_text: str,
        video_url: str,
        photo_author_id: str | None,
    ) -> dict:
        captured_graphql: list[dict] = []

        async def on_response(resp) -> None:
            try:
                if GRAPHQL_PATH not in resp.url:
                    return
                data = await resp.json()
                if isinstance(data, dict):
                    captured_graphql.append(data)
            except Exception:
                return

        page.on("response", on_response)
        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        resolved_author_id = photo_author_id
        if not resolved_author_id:
            for packet in captured_graphql:
                resolved_author_id = _walk_photo_author_id(packet, photo_id)
                if resolved_author_id:
                    break
        if not resolved_author_id:
            resolved_author_id = await page.evaluate(
                """(photoId) => {
                    const state = window.__INITIAL_STATE__ || window.__APOLLO_STATE__ || {};
                    const text = JSON.stringify(state);
                    const re = /"authorId"\\s*:\\s*"([0-9]+)"/g;
                    let match;
                    while ((match = re.exec(text))) {
                        return match[1];
                    }
                    const rePhoto = new RegExp(`"photoId"\\\\s*:\\\\s*"${photoId}"[\\\\s\\\\S]{0,400}?"authorId"\\\\s*:\\\\s*"([0-9]+)"`);
                    const near = text.match(rePhoto);
                    return near ? near[1] : null;
                }""",
                photo_id,
            )

        if not resolved_author_id:
            return {
                "platform": PLATFORM,
                "tenant_id": self.tenant_id,
                "action": "reply_comment",
                "photo_id": photo_id,
                "comment_id": comment_id,
                "reply_text": reply_text,
                "video_url": video_url,
                "page_url": page.url,
                "capture_method": "video_page_graphql",
                "reply": {
                    "ok": False,
                    "error": "无法解析 photoAuthorId，请传入 photo_author_id 参数",
                },
            }

        variables = {
            "photoId": photo_id,
            "photoAuthorId": str(resolved_author_id),
            "content": reply_text,
            "replyToCommentId": comment_id,
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
        ok = bool(comment_id_out) and not data.get("errors")
        reply_result = {
            "ok": ok,
            "photo_author_id": str(resolved_author_id),
            "comment_id_out": comment_id_out,
            "payload": payload,
        }
        if not ok:
            errors = data.get("errors") or []
            reply_result["error"] = (
                errors[0].get("message") if errors else data.get("error") or data.get("raw") or "graphql_failed"
            )

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
            "capture_method": "video_page_graphql",
            "reply": reply_result,
        }
