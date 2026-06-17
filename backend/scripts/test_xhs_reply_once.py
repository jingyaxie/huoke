#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.comment_reply_service import CommentReplyService

COMMENT_ID = "6a0e60ed000000002b02bf0e"
REPLY_TEXT = "有这个可能，有些唇釉叠护唇油确实会这种光泽感"


async def main() -> int:
    settings = get_settings()
    session = SessionLocal()
    try:
        service = CommentReplyService(
            settings,
            tenant_id="default",
            platform="xiaohongshu",
            session=session,
            account_id="default",
        )
        target = service.resolve_target(comment_id=COMMENT_ID)
        print("=== resolve_target ===", flush=True)
        if isinstance(target, dict):
            print(json.dumps(target, ensure_ascii=False, indent=2), flush=True)
            return 1
        print(
            json.dumps(
                {
                    "comment_id": target.comment_id,
                    "content_id": target.content_id,
                    "content_url": target.content_url,
                    "comment_text": target.comment_text,
                    "nickname": target.nickname,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

        result = await service.reply_comment(
            comment_id=COMMENT_ID,
            reply_text=REPLY_TEXT,
            show_browser=False,
        )
        print("=== reply_result ===", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("status") == "completed" else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
