"""小红书评论回复：UI 暖场 + 页内签名 comment/post（不依赖 DOM 定位目标评论）。"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.core.config import Settings
from app.platforms.xiaohongshu.human_guards import assert_xhs_human_ready
from app.platforms.xiaohongshu.reply_comment import XhsReplyCommentTool
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    activate_comments_on_detail,
    is_note_detail_open,
    open_note_for_human_action,
    scroll_comment_list_in_detail,
)
from app.services.ui_flow.platforms.xiaohongshu.note_ui import (
    scroll_note_page,
    trigger_comment_panel,
)

_WARM_REPLY_INPUT_SELECTORS = (
    'div.content-input [contenteditable="true"]',
    'textarea[placeholder*="回复"]',
    'textarea[placeholder*="评论"]',
    'div[contenteditable="true"]',
    "textarea",
)

_COMMENT_ITEM_SELECTORS = (
    ".note-comment-item",
    '[class*="comment-item"]',
    '[class*="CommentItem"]',
    "#comment-list > div",
)

_ITEM_REPLY_BTN_SELECTORS = (
    ".reply.icon-container",
    '[class*="reply"]',
    'span:has-text("回复")',
    'button:has-text("回复")',
)

CAPTURE_METHOD = "xiaohongshu_comment_warm_publish"
CAPTURE_METHOD_DRY = "xiaohongshu_comment_warm_publish_dry_run"


async def _human_pause(*, min_s: float = 1.0, max_s: float = 1.8) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def _slow_mouse_move(page, x: float, y: float) -> None:
    with contextlib.suppress(Exception):
        await page.mouse.move(x, y, steps=random.randint(14, 24))


async def _page_note_accessible(page) -> bool:
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    url = page.url or ""
    if "页面不见了" in title or "/404" in url or "暂时无法浏览" in url:
        return False
    return True


async def _warmup_note_page(page) -> None:
    vp = page.viewport_size or {"width": 1440, "height": 900}
    await _human_pause(min_s=2.0, max_s=3.5)
    for _ in range(random.randint(2, 4)):
        x = random.uniform(vp["width"] * 0.28, vp["width"] * 0.72)
        y = random.uniform(vp["height"] * 0.22, vp["height"] * 0.62)
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.7, max_s=1.4)


async def _wait_comment_panel_ready(page, *, timeout_s: float = 12.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            for sel in _COMMENT_ITEM_SELECTORS:
                if await page.locator(sel).count() > 0:
                    return True
            if await page.locator('span:has-text("条评论")').count() > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.45)
    return False


async def _ensure_on_note_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    note_id: str = "",
    note_meta: dict[str, Any] | None = None,
) -> str:
    """先进笔记详情再评论；探索首页不误判为浮层，不在首页滚评论。"""
    from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
        _on_explore_home_page,
        _note_detail_matches_id,
    )

    resolved_id = str(note_id or "").strip()
    if not resolved_id and content_url:
        with contextlib.suppress(ValueError):
            resolved_id = extract_note_id(content_url)

    if (
        resolved_id
        and not _on_explore_home_page(page.url)
        and await is_note_detail_open(page)
        and await _page_note_accessible(page)
        and await _note_detail_matches_id(page, resolved_id)
    ):
        await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
        await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
        return "note"

    if content_url and not _on_explore_home_page(page.url):
        with contextlib.suppress(Exception):
            await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
            await _human_pause(min_s=1.0, max_s=1.6)
        if (
            await is_note_detail_open(page)
            and await _page_note_accessible(page)
            and (not resolved_id or await _note_detail_matches_id(page, resolved_id))
        ):
            await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
            await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
            return "note"

    opened = await open_note_for_human_action(
        page,
        settings,
        tenant_id=tenant_id,
        content_url=content_url,
        note_id=resolved_id,
        note_meta=note_meta,
    )
    if not opened.get("ok"):
        raise RuntimeError("无法打开笔记详情")
    await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
    return "note"


async def _hover_comment_item(page, item) -> None:
    try:
        box = await item.bounding_box()
        if not box:
            return
        x = box["x"] + box["width"] * 0.55
        y = box["y"] + box["height"] * 0.55
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.6, max_s=1.1)
    except Exception:
        pass


async def _find_reply_btn_in_item(item):
    for selector in _ITEM_REPLY_BTN_SELECTORS:
        btn = item.locator(selector).first
        try:
            if await btn.count() and await btn.is_visible():
                return btn
        except Exception:
            continue
    return None


async def _reply_input_ready(page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                const nodes = document.querySelectorAll(
                  'div.content-input [contenteditable="true"], textarea[placeholder*="回复"], textarea[placeholder*="评论"]'
                );
                for (const el of nodes) {
                  const rect = el.getBoundingClientRect();
                  if (rect.width < 8 || rect.height < 8) continue;
                  const ph = (el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '').trim();
                  const active = document.activeElement === el || el.contains(document.activeElement);
                  if (active || ph.includes('回复')) return true;
                }
                return false;
              }"""
            )
        )
    except Exception:
        return False


async def _locate_reply_input(page, *, timeout_s: float = 12.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _reply_input_ready(page):
            for selector in _WARM_REPLY_INPUT_SELECTORS:
                loc = page.locator(selector).last
                try:
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
        await asyncio.sleep(0.42)
    return None


async def _iter_comment_items(page, *, max_scan: int = 12):
    for sel in _COMMENT_ITEM_SELECTORS:
        loc = page.locator(sel)
        try:
            count = await loc.count()
        except Exception:
            continue
        for idx in range(min(count, max_scan)):
            item = loc.nth(idx)
            try:
                if await item.count() and await item.is_visible():
                    yield item
            except Exception:
                continue


async def _pick_visible_comment_item(page, *, max_scan: int = 12):
    """触达关注用：任取一条带用户链接的可见评论（不必是目标评论）。"""
    async for item in _iter_comment_items(page, max_scan=max_scan):
        try:
            has_profile = await item.evaluate(
                """(el) => Boolean(el.querySelector('a[href*="/user/profile/"]'))"""
            )
            if has_profile:
                return item
        except Exception:
            continue
    return None


async def _click_reply_on_visible_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """打开评论区 → 随便点一条可见评论的「回复」暖场（不必是目标评论）。"""
    from app.core.antibot import human_click

    await _human_pause(min_s=1.0, max_s=1.8)
    await trigger_comment_panel(page, settings, tenant_id=tenant_id)
    panel_ok = await _wait_comment_panel_ready(page, timeout_s=12.0)
    if not panel_ok:
        return False

    await _human_pause(min_s=1.0, max_s=1.6)
    await scroll_note_page(page, settings, tenant_id=tenant_id, rounds=1)
    await scroll_comment_list_in_detail(page, settings, tenant_id=tenant_id, rounds=2)
    await _human_pause(min_s=0.8, max_s=1.4)

    tried = 0
    async for item in _iter_comment_items(page):
        if tried >= 10:
            break
        tried += 1
        try:
            await _hover_comment_item(page, item)
            reply_btn = await _find_reply_btn_in_item(item)
            if reply_btn is None:
                continue
            await _human_pause(min_s=0.5, max_s=0.9)
            await human_click(page, reply_btn, settings, tenant_id=tenant_id)
            await _human_pause(min_s=1.0, max_s=1.8)
            if await _locate_reply_input(page, timeout_s=10.0):
                return True
        except Exception:
            continue
    return False


async def _type_into_reply_input(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    reply_text: str,
) -> bool:
    from app.core.antibot import human_type

    input_loc = await _locate_reply_input(page, timeout_s=10.0)
    if input_loc is None:
        return False
    await _human_pause(min_s=0.6, max_s=1.1)
    await human_type(page, input_loc, reply_text, settings, tenant_id=tenant_id)
    await _human_pause(min_s=1.0, max_s=1.8)
    return True


async def warm_publish_reply_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    comment_id: str,
    reply_text: str,
    note_id: str = "",
    dry_run: bool = False,
    note_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UI 暖场后在页内 context 调用 comment/post；目标 comment_id 仅用于 API，不必在 DOM 中定位。"""
    text = str(reply_text or "").strip()
    target_cid = str(comment_id or "").strip()
    if not target_cid:
        return {"ok": False, "error": "缺少 comment_id", "capture_method": CAPTURE_METHOD}
    if not text:
        return {"ok": False, "error": "缺少 reply_text", "capture_method": CAPTURE_METHOD}

    resolved_note = str(note_id or "").strip()
    if not resolved_note and content_url:
        with contextlib.suppress(ValueError):
            resolved_note = extract_note_id(content_url)
    if not resolved_note:
        return {"ok": False, "error": "缺少 note_id", "capture_method": CAPTURE_METHOD}

    steps: list[str] = []
    try:
        stage = await _ensure_on_note_page(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=content_url,
            note_id=resolved_note,
            note_meta=note_meta,
        )
        steps.append(f"stage={stage}")
        await _warmup_note_page(page)

        if not await _click_reply_on_visible_comment(page, settings, tenant_id=tenant_id):
            return {
                "ok": False,
                "error": "未能点击评论回复并打开输入框",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("input=reply_button")

        if not await _type_into_reply_input(
            page, settings, tenant_id=tenant_id, reply_text=text
        ):
            return {
                "ok": False,
                "error": "未能输入回复文案",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("typed")

        would_publish = {
            "note_id": resolved_note,
            "target_comment_id": target_cid,
            "text_preview": text[:120],
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "capture_method": CAPTURE_METHOD_DRY,
                "comment_id": target_cid,
                "note_id": resolved_note,
                "content_url": content_url,
                "page_url": page.url,
                "steps": steps,
                "would_publish": would_publish,
                "diagnostic": "dry_run：已完成暖场与输入，未调用 comment/post",
            }

        tool = XhsReplyCommentTool(settings, tenant_id)
        publish_result = await tool._reply_via_api(
            page,
            note_id=resolved_note,
            comment_id=target_cid,
            reply_text=text,
            referer=page.url,
        )
        ok = bool(publish_result.get("ok"))
        return {
            "ok": ok,
            "dry_run": False,
            "capture_method": CAPTURE_METHOD,
            "comment_id": target_cid,
            "note_id": resolved_note,
            "content_url": content_url,
            "page_url": page.url,
            "steps": steps,
            "would_publish": would_publish,
            "publish": publish_result,
            "error": None if ok else publish_result.get("error"),
            "diagnostic": "已调用 comment/post" if ok else "comment/post 失败",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
            "steps": steps,
        }
