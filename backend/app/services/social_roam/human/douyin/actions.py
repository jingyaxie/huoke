from __future__ import annotations

import asyncio
import random
from typing import Any

from app.core.antibot import human_click, human_delay, human_scroll, human_type, require_login
from app.core.config import Settings
from app.platforms.douyin.js_constants import PLATFORM
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.registry import get_comment_crawler

_REPLY_BTN_SELECTORS = (
    '[data-e2e="comment-reply"]',
    'button:has-text("回复")',
    'span:has-text("回复")',
)
_INPUT_SELECTORS = (
    '[data-e2e="comment-input"] div[contenteditable="true"]',
    '[data-e2e="comment-input"] textarea',
    'div.public-DraftEditor-content[contenteditable="true"]',
    'div[contenteditable="true"]',
)
_SEND_SELECTORS = (
    '[data-e2e="comment-post"]',
    'button:has-text("发送")',
    'div:has-text("发送")',
)


async def browse_keyword_comments(
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    keyword: str,
    content_limit: int,
    days: int,
    region: str | None,
    page,
    show_browser: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    store = DouyinSessionStore(settings)
    require_login(store, tenant_id, settings, account_id=account_id)
    backend = get_comment_crawler(settings, PLATFORM, tenant_id, account_id=account_id)
    results, _files, diagnostic, _session_meta = await backend.crawl_keyword_comments(
        keyword=keyword,
        limit=content_limit,
        show_browser=show_browser,
        days=days,
        region=region,
        existing_page=page,
    )
    return results, diagnostic


async def human_reply_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    comment_id: str,
    reply_text: str,
    scroll_rounds: int = 4,
) -> dict[str, Any]:
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")

    for _ in range(max(1, scroll_rounds)):
        await human_scroll(page, settings, tenant_id=tenant_id, delta_y=500)
        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")

    comment_nodes = page.locator('[data-e2e="comment-item"], [class*="CommentItem"]')
    target = comment_nodes.filter(has_text=comment_id[:8]).first
    if not await target.count():
        target = page.locator(f'[data-e2e="comment-item"]').first

    reply_btn = None
    for selector in _REPLY_BTN_SELECTORS:
        candidate = target.locator(selector).first if await target.count() else page.locator(selector).first
        if await candidate.count():
            reply_btn = candidate
            break
    if reply_btn is None or not await reply_btn.count():
        return {"ok": False, "error": "未找到回复按钮", "capture_method": "douyin_comment_ui_human"}

    await human_click(page, reply_btn, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")

    input_loc = None
    for selector in _INPUT_SELECTORS:
        candidate = page.locator(selector).last
        if await candidate.count():
            input_loc = candidate
            break
    if input_loc is None:
        return {"ok": False, "error": "未找到回复输入框", "capture_method": "douyin_comment_ui_human"}

    await human_type(page, input_loc, reply_text, settings, tenant_id=tenant_id)

    post_result: dict[str, Any] = {"ok": False}

    async def on_response(resp) -> None:
        if "comment/publish" not in resp.url:
            return
        try:
            body = await resp.json()
        except Exception:
            return
        code = body.get("status_code")
        if code == 0:
            post_result.update({"ok": True, "status_code": code, "comment": body.get("comment") or {}})

    page.on("response", on_response)
    try:
        send_btn = None
        for selector in _SEND_SELECTORS:
            candidate = page.locator(selector).last
            if await candidate.count():
                send_btn = candidate
                break
        if send_btn is None:
            return {"ok": False, "error": "未找到发送按钮", "capture_method": "douyin_comment_ui_human"}
        await human_click(page, send_btn, settings, tenant_id=tenant_id)
        for _ in range(20):
            if post_result.get("ok"):
                break
            await asyncio.sleep(0.4)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    if post_result.get("ok"):
        return {
            **post_result,
            "capture_method": "douyin_comment_ui_human_type",
            "comment_id": comment_id,
            "content_url": content_url,
        }
    return {
        "ok": False,
        "error": post_result.get("error") or "UI 回复后未捕获成功响应",
        "capture_method": "douyin_comment_ui_human_type",
        "comment_id": comment_id,
    }


async def human_follow_user(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    sec_uid: str,
    user_id: str,
    username: str = "",
) -> dict[str, Any]:
    store = DouyinSessionStore(settings)
    profile = DouyinProfileTool(settings, tenant_id, store, account_id=account_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    profile_url = await profile.open_profile(page, sec_uid)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")

    follow_selectors = (
        '[data-e2e="user-info-follow"]',
        'button:has-text("关注")',
        '[data-e2e="follow-button"]',
    )
    follow_btn = None
    for selector in follow_selectors:
        candidate = page.locator(selector).first
        if await candidate.count():
            text = (await candidate.inner_text() or "").strip()
            if "已关注" in text or "互相关注" in text:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_followed",
                    "capture_method": "douyin_follow_ui_human",
                    "profile_url": profile_url,
                }
            follow_btn = candidate
            break
    if follow_btn is None:
        return {
            "ok": False,
            "error": "未找到关注按钮",
            "capture_method": "douyin_follow_ui_human",
            "profile_url": profile_url,
        }

    await human_click(page, follow_btn, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    await asyncio.sleep(random.uniform(0.8, 1.6))

    verify_text = (await follow_btn.inner_text() or "").strip()
    ok = "已关注" in verify_text or "互相关注" in verify_text
    return {
        "ok": ok,
        "user_id": user_id,
        "sec_uid": sec_uid,
        "username": username,
        "profile_url": profile_url,
        "capture_method": "douyin_follow_ui_human",
        "follow_status_after_text": verify_text,
        "error": None if ok else "点击关注后未检测到已关注状态",
    }
