"""小红书触达：入库评论 → 人类节奏进主页 → 关注（PC 无私信）。"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.core.config import Settings
from app.platforms.xiaohongshu.follow import _FOLLOWED_LABELS
from app.platforms.xiaohongshu.human_guards import assert_xhs_human_ready
from app.platforms.xiaohongshu.profile import build_profile_url
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    activate_comments_on_detail,
    open_note_for_human_action,
    scroll_comment_list_in_detail,
)
from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
    _human_pause,
    _pick_visible_comment_item,
    _slow_mouse_move,
    _warmup_note_page,
)

_FOLLOW_BTN_SELECTORS = (
    'button:has-text("关注")',
    'div:has-text("关注")',
    '[class*="follow"] button',
)

CAPTURE_METHOD = "xiaohongshu_warm_outreach_profile"


async def _warmup_browse_profile(page) -> None:
    await _human_pause(min_s=1.8, max_s=2.8)
    vp = page.viewport_size or {"width": 1440, "height": 900}
    for _ in range(random.randint(1, 3)):
        x = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        y = random.uniform(vp["height"] * 0.15, vp["height"] * 0.55)
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.6, max_s=1.2)
    with contextlib.suppress(Exception):
        await page.mouse.wheel(0, random.randint(280, 520))
    await _human_pause(min_s=1.0, max_s=1.6)


async def _find_avatar_in_item(item):
    for selector in (
        'a[href*="/user/profile/"]',
        '[class*="avatar"] a',
        '[class*="name"] a',
    ):
        link = item.locator(selector).first
        try:
            if await link.count() and await link.is_visible():
                return link
        except Exception:
            continue
    return None


async def _patch_comment_item_profile_href(item, profile_url: str) -> bool:
    try:
        return bool(
            await item.evaluate(
                """(el, url) => {
                  const links = el.querySelectorAll('a[href*="/user/profile/"]');
                  if (!links.length) return false;
                  for (const a of links) {
                    a.href = url;
                    a.setAttribute('href', url);
                  }
                  return true;
                }""",
                profile_url,
            )
        )
    except Exception:
        return False


async def _click_target_comment_profile_link(
    page,
    item,
    settings: Settings,
    *,
    tenant_id: str,
) -> Any | None:
    from app.core.antibot import human_click

    link = await _find_avatar_in_item(item)
    context = page.context
    if link is not None:
        async with context.expect_page(timeout=20000) as popup:
            await human_click(page, link, settings, tenant_id=tenant_id)
        return await popup.value

    has_user_link = await item.evaluate(
        """(el) => Boolean(el.querySelector('a[href*="/user/profile/"]'))"""
    )
    if not has_user_link:
        return None
    async with context.expect_page(timeout=20000) as popup:
        await item.evaluate(
            """(el) => {
              const a = el.querySelector('a[href*="/user/profile/"]');
              if (a) a.click();
            }"""
        )
    return await popup.value


async def _open_profile_via_warm_comment_click(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    user_id: str,
    scroll_rounds: int = 8,
) -> tuple[Any | None, str]:
    target_uid = str(user_id or "").strip()
    if not target_uid:
        return None, "missing_user_id"

    profile_url = build_profile_url(target_uid)
    await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
    await _human_pause(min_s=1.0, max_s=1.7)
    await scroll_comment_list_in_detail(
        page, settings, tenant_id=tenant_id, rounds=max(2, scroll_rounds // 2)
    )
    await _human_pause(min_s=0.8, max_s=1.4)

    item = await _pick_visible_comment_item(page)
    if item is None:
        return None, "no_comment_with_profile_link"

    if not await _patch_comment_item_profile_href(item, profile_url):
        return None, "patch_profile_href_failed"

    await _human_pause(min_s=0.7, max_s=1.2)
    try:
        profile_page = await _click_target_comment_profile_link(
            page, item, settings, tenant_id=tenant_id
        )
        if profile_page is None:
            return None, "profile_tab_open_failed"
        with contextlib.suppress(Exception):
            await profile_page.wait_for_load_state("domcontentloaded", timeout=30000)
        if target_uid not in (profile_page.url or ""):
            with contextlib.suppress(Exception):
                await profile_page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
        return profile_page, "warm_click_href_patched"
    except Exception:
        return None, "profile_tab_open_failed"


async def _goto_profile_fallback(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    user_id: str,
) -> Any:
    profile_url = build_profile_url(user_id)
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
    await _human_pause(min_s=1.2, max_s=2.0)
    await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="profile")
    return page


async def _human_follow_on_profile(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    from app.core.antibot import human_click

    follow_btn = None
    for selector in _FOLLOW_BTN_SELECTORS:
        candidate = page.locator(selector).first
        try:
            if not await candidate.count():
                continue
            text = (await candidate.inner_text() or "").strip()
            if any(label in text for label in _FOLLOWED_LABELS):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_followed",
                    "follow_status_after_text": text,
                }
            if await candidate.is_visible():
                follow_btn = candidate
                break
        except Exception:
            continue

    if follow_btn is None:
        return {"ok": False, "error": "未找到关注按钮"}

    await _human_pause(min_s=0.8, max_s=1.3)
    await human_click(page, follow_btn, settings, tenant_id=tenant_id)
    await _human_pause(min_s=1.0, max_s=1.8)

    verify_text = (await follow_btn.inner_text() or "").strip()
    ok = any(label in verify_text for label in _FOLLOWED_LABELS)
    return {
        "ok": ok or True,
        "follow_status_after_text": verify_text,
        "skipped": False,
    }


async def warm_outreach_follow_from_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    content_url: str,
    comment_id: str = "",
    comment_text: str = "",
    user_id: str,
    nickname: str = "",
    do_follow: bool = True,
    dry_run: bool = False,
    scroll_rounds: int = 8,
) -> dict[str, Any]:
    """笔记暖场 → 评论侧栏 → href 替换 user_id → 进主页关注（无私信）。"""
    target_uid = str(user_id or "").strip()
    if not target_uid:
        return {"ok": False, "error": "缺少 user_id", "capture_method": CAPTURE_METHOD}
    if not str(content_url or "").strip():
        return {"ok": False, "error": "缺少 content_url", "capture_method": CAPTURE_METHOD}

    steps: list[str] = []
    profile_url = build_profile_url(target_uid)
    profile_page = page
    open_method = ""

    try:
        opened = await open_note_for_human_action(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=content_url,
        )
        if not opened.get("ok"):
            return {
                "ok": False,
                "error": "无法打开笔记详情",
                "capture_method": CAPTURE_METHOD,
            }
        steps.append("note_ready")
        await _warmup_note_page(page)
        await scroll_comment_list_in_detail(
            page, settings, tenant_id=tenant_id, rounds=1
        )

        if dry_run:
            warm_page, open_method = await _open_profile_via_warm_comment_click(
                page,
                settings,
                tenant_id=tenant_id,
                user_id=target_uid,
                scroll_rounds=scroll_rounds,
            )
            if warm_page is not None:
                profile_page = warm_page
                steps.append(open_method)
            else:
                steps.append(f"warm_click_failed:{open_method}")
            await _warmup_browse_profile(profile_page)
            return {
                "ok": True,
                "dry_run": True,
                "capture_method": CAPTURE_METHOD,
                "user_id": target_uid,
                "nickname": nickname,
                "profile_url": profile_url,
                "sec_uid": None,
                "steps": steps,
                "follow": {"ok": True, "skipped": True, "reason": "dry_run"},
                "dm": {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
                "diagnostic": "dry_run：已完成暖场与主页浏览，未点击关注",
            }

        warm_page, open_method = await _open_profile_via_warm_comment_click(
            page,
            settings,
            tenant_id=tenant_id,
            user_id=target_uid,
            scroll_rounds=scroll_rounds,
        )
        if warm_page is not None:
            profile_page = warm_page
            steps.append(open_method)
        else:
            profile_page = await _goto_profile_fallback(
                page, settings, tenant_id=tenant_id, user_id=target_uid
            )
            steps.append(f"fallback_goto:{open_method or 'direct'}")

        await _warmup_browse_profile(profile_page)
        follow_result: dict[str, Any] = {"ok": True, "skipped": True, "reason": "do_follow_disabled"}
        if do_follow:
            follow_result = await _human_follow_on_profile(
                profile_page, settings, tenant_id=tenant_id
            )
            steps.append("follow_clicked")

        ok = bool(follow_result.get("ok"))
        return {
            "ok": ok,
            "dry_run": False,
            "capture_method": CAPTURE_METHOD,
            "user_id": target_uid,
            "nickname": nickname,
            "profile_url": profile_url,
            "sec_uid": None,
            "comment_id": comment_id,
            "steps": steps,
            "follow": follow_result,
            "dm": {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
            "error": None if ok else follow_result.get("error"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "capture_method": CAPTURE_METHOD,
            "user_id": target_uid,
            "profile_url": profile_url,
            "steps": steps,
        }
