from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.douyin.js_constants import _extract_aweme_id
from app.platforms.kuaishou.utils import build_video_url
from app.platforms.registry import get_reply_comment_tool
from app.platforms.types import normalize_platform
from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, extract_note_id
from app.repositories.content_comment_repository import ContentCommentRepository
from app.services.comment_store_service import extract_content_id


@dataclass
class CommentReplyTarget:
    platform: str
    comment_id: str
    content_id: str
    content_url: str
    comment_text: str = ""
    parent_comment_id: str | None = None
    nickname: str = ""
    photo_author_id: str | None = None
    reply_to_user_id: str | None = None


class CommentReplyService:
    """从 DB 定位评论所属内容，再经页面 JS 接口直接回复。"""

    def __init__(
        self,
        settings: Settings,
        *,
        tenant_id: str,
        platform: str,
        session: Session,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = normalize_platform(platform)
        self.session = session
        self.account_id = account_id
        self.repo = ContentCommentRepository(session, tenant_id)

    def resolve_target(
        self,
        *,
        comment_id: str,
        content_id: str | None = None,
        comment_text: str | None = None,
        video_url: str | None = None,
        note_url: str | None = None,
        content_url: str | None = None,
        photo_author_id: str | None = None,
    ) -> CommentReplyTarget | dict[str, Any]:
        comment_id = str(comment_id or "").strip()
        if not comment_id:
            return {"error": "缺少 comment_id", "status": "failed"}

        url_override = (video_url or note_url or content_url or "").strip() or None
        record = self.repo.find_comment_record(
            platform=self.platform,
            comment_id=comment_id,
            content_id=content_id,
            comment_text=comment_text,
        )

        if record:
            resolved_content_id = str(content_id or record.content_id)
            resolved_url = url_override or (record.content_url or "").strip() or self._default_content_url(
                resolved_content_id,
                fallback_url=url_override,
                raw_data=record.raw_data,
            )
            if not resolved_url:
                return {
                    "error": f"评论 {comment_id} 缺少 content_url，请传入 video_url / note_url",
                    "status": "failed",
                }
            raw = record.raw_data if isinstance(record.raw_data, dict) else {}
            return CommentReplyTarget(
                platform=self.platform,
                comment_id=comment_id,
                content_id=resolved_content_id,
                content_url=resolved_url,
                comment_text=record.comment_text or (comment_text or ""),
                parent_comment_id=record.parent_comment_id,
                nickname=record.nickname or "",
                photo_author_id=photo_author_id or raw.get("photo_author_id"),
                reply_to_user_id=raw.get("user_id"),
            )

        if url_override:
            resolved_content_id = str(content_id or extract_content_id(self.platform, url_override) or "")
            if not resolved_content_id:
                return {"error": "无法从链接解析 content_id", "status": "failed"}
            return CommentReplyTarget(
                platform=self.platform,
                comment_id=comment_id,
                content_id=resolved_content_id,
                content_url=url_override,
                comment_text=comment_text or "",
                photo_author_id=photo_author_id,
            )

        return {
            "error": (
                f"数据库未找到评论 {comment_id}；请先抓取评论入库，或同时提供 video_url / note_url"
            ),
            "status": "failed",
        }

    def _default_content_url(
        self,
        content_id: str,
        *,
        fallback_url: str | None,
        raw_data: dict[str, Any] | None,
    ) -> str:
        if fallback_url:
            return fallback_url
        if self.platform == "douyin":
            return f"https://www.douyin.com/video/{content_id}"
        if self.platform == "xiaohongshu":
            raw = raw_data or {}
            access = extract_note_access_params(str(raw.get("content_url") or raw.get("note_url") or ""))
            if not access.get("xsec_token"):
                access = extract_note_access_params(str(raw.get("xsec_token") or ""))
            return build_note_url(
                content_id,
                access.get("xsec_token"),
                access.get("xsec_source"),
            )
        if self.platform == "kuaishou":
            return build_video_url(content_id)
        return ""

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        content_id: str | None = None,
        comment_text: str | None = None,
        video_url: str | None = None,
        note_url: str | None = None,
        content_url: str | None = None,
        photo_author_id: str | None = None,
        show_browser: bool = False,
    ) -> dict[str, Any]:
        reply_text = str(reply_text or "").strip()
        if not reply_text:
            return {"error": "缺少 reply_text", "status": "failed"}

        target = self.resolve_target(
            comment_id=comment_id,
            content_id=content_id,
            comment_text=comment_text,
            video_url=video_url,
            note_url=note_url,
            content_url=content_url,
            photo_author_id=photo_author_id,
        )
        if isinstance(target, dict):
            return target

        tool = get_reply_comment_tool(
            self.settings,
            self.platform,
            self.tenant_id,
            account_id=self.account_id,
        )

        if self.platform == "douyin":
            aweme_id = target.content_id
            try:
                aweme_id = _extract_aweme_id(target.content_url)
            except ValueError:
                aweme_id = target.content_id
            result = await tool.reply_comment(
                comment_id=target.comment_id,
                reply_text=reply_text,
                content_url=target.content_url,
                aweme_id=aweme_id,
                show_browser=show_browser,
            )
        elif self.platform == "xiaohongshu":
            note_id = target.content_id
            try:
                note_id = extract_note_id(target.content_url)
            except ValueError:
                note_id = target.content_id
            result = await tool.reply_comment(
                comment_id=target.comment_id,
                reply_text=reply_text,
                note_url=target.content_url,
                note_id=note_id,
                show_browser=show_browser,
            )
        else:
            photo_id = target.content_id
            result = await tool.reply_comment(
                comment_id=target.comment_id,
                reply_text=reply_text,
                video_url=target.content_url,
                photo_id=photo_id,
                photo_author_id=target.photo_author_id or photo_author_id,
                reply_to_user_id=target.reply_to_user_id,
                show_browser=show_browser,
            )

        reply = result.get("reply") or {}
        ok = bool(reply.get("ok"))
        return {
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "comment_id": target.comment_id,
            "content_id": target.content_id,
            "content_url": target.content_url,
            "target_comment_text": target.comment_text,
            "reply_text": reply_text,
            "capture_method": result.get("capture_method") or "thin_nav_js",
            "reply": reply,
            "output_file": result.get("output_file"),
            "error": None if ok else reply.get("error") or reply.get("status_msg") or reply.get("msg"),
        }
