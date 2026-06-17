from __future__ import annotations

import re
from typing import Any

from app.core.antibot import human_click, human_delay
from app.core.config import Settings
from app.platforms.douyin.js_constants import _normalize_comment

# Feed 流详情：左侧视频 + 右侧评论侧栏（见产品截图）
_COMMENT_TAB_SELECTORS = (
    '[data-e2e="detail-tab-comment"]',
    'div[role="tab"]:has-text("评论")',
    'span:text-is("评论")',
    'text=评论',
)
_COMMENT_SIDEBAR_MARKERS = (
    'text=全部评论',
    '[data-e2e="comment-item"]',
    '[class*="CommentItem"]',
)
_CLOSE_FEED_SELECTORS = (
    '[data-e2e="close-icon"]',
    '[aria-label="关闭"]',
    'button[aria-label="关闭"]',
    '[class*="close-btn"]',
)
_FEED_MODAL_COMMENT_ROOT = '[data-e2e="feed-active-video"]'
_COMMENT_WHEEL_TARGETS = (
    f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="comment-item"]',
    '[data-e2e="comment-item"]',
    'text=全部评论',
)

COMMENT_SIDEBAR_SCROLL_JS = """
() => {
  const items = [...document.querySelectorAll('[data-e2e="comment-item"]')];
  const anchors = [];
  if (items.length) anchors.push(items[items.length - 1]);
  const header = [...document.querySelectorAll('*')].find(el => {
    const t = (el.textContent || '').trim();
    return t.startsWith('全部评论');
  });
  if (header) anchors.push(header);
  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  if (feed) anchors.push(feed);

  for (const anchor of anchors) {
    let node = anchor;
    for (let i = 0; i < 12 && node; i++) {
      const sh = node.scrollHeight || 0;
      const ch = node.clientHeight || 0;
      if (sh > ch + 30) {
        const before = node.scrollTop || 0;
        node.scrollTop = Math.min(before + 520, sh);
        return node.scrollTop > before || sh > ch + 120;
      }
      node = node.parentElement;
    }
  }
  return false;
}
"""


async def is_feed_detail_open(page) -> bool:
    for selector in (
        *_COMMENT_SIDEBAR_MARKERS,
        _FEED_MODAL_COMMENT_ROOT,
        '[data-e2e="feed-comment-icon"]',
        '[data-e2e="video-player"]',
    ):
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                return True
        except Exception:
            continue
    url = (page.url or "").lower()
    if "modal_id=" in url and "/search/" in url:
        return True
    try:
        body = await page.locator("body").inner_text(timeout=1500)
        if "全部评论" in body and ("详情" in body or "相关推荐" in body):
            return True
    except Exception:
        pass
    return False


async def _comment_sidebar_active(page) -> bool:
    try:
        modal_comments = page.locator(f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="comment-item"]').first
        if await modal_comments.count() and await modal_comments.is_visible():
            return True
    except Exception:
        pass
    try:
        header = page.locator('text=全部评论').first
        return await header.count() > 0 and await header.is_visible()
    except Exception:
        return False


async def _wheel_comment_list_area(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    for selector in _COMMENT_WHEEL_TARGETS:
        loc = page.locator(selector).last
        try:
            if not await loc.count():
                continue
            if not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box:
                continue
            await page.mouse.move(
                box["x"] + box["width"] / 2,
                box["y"] + min(box["height"] / 2, 40),
            )
            await page.mouse.wheel(0, 520)
            await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
            return True
        except Exception:
            continue
    return False

_PAUSE_VIDEO_SELECTORS = (
    '[data-e2e="feed-active-video"] video',
    '[data-e2e="feed-active-video"] [data-e2e="video-player"]',
    '[data-e2e="video-player"]',
    "video",
)


async def pause_feed_video_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """暂停 Feed 视频：单击播放器中部（模拟真人，不用 JS / Space）。"""
    for selector in _PAUSE_VIDEO_SELECTORS:
        try:
            loc = page.locator(selector).first
            if not await loc.count() or not await loc.is_visible():
                continue
            await human_click(page, loc, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="action")
            return True
        except Exception:
            continue
    return False


async def activate_comment_sidebar_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    if await _comment_sidebar_active(page):
        return True

    await pause_feed_video_on_page(page, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="fast")

    icon_selectors = (
        '[data-e2e="feed-comment-icon"]',
        '[data-e2e="comment-icon"]',
        f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="feed-comment-icon"]',
        '[class*="comment"] [data-e2e="feed-comment-icon"]',
    )
    for _ in range(3):
        if await _comment_sidebar_active(page):
            return True
        for selector in icon_selectors:
            icon = page.locator(selector).first
            try:
                if await icon.count() and await icon.is_visible():
                    await human_click(page, icon, settings, tenant_id=tenant_id)
                    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                    if await _comment_sidebar_active(page) or await page.locator('[data-e2e="comment-item"]').count():
                        return True
            except Exception:
                continue
        await human_delay(page, settings, tenant_id=tenant_id, profile="fast")

    candidates: list = []
    for selector in _COMMENT_TAB_SELECTORS:
        loc = page.locator(selector)
        count = await loc.count()
        for i in range(min(count, 5)):
            candidates.append(loc.nth(i))

    for tab in candidates:
        try:
            if not await tab.is_visible():
                continue
            text = re.sub(r"\s+", "", (await tab.inner_text() or ""))
            if text != "评论":
                continue
            await human_click(page, tab, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="action")
            if await _comment_sidebar_active(page):
                return True
        except Exception:
            continue

    return await _comment_sidebar_active(page)


async def select_latest_comment_sort_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """评论侧栏默认「最热」时，切到「最新」以便按时间窗口采集。"""
    if not await _comment_sidebar_active(page):
        return False
    selectors = (
        '[data-e2e="comment-sort-latest"]',
        'span:text-is("最新")',
        'div[role="tab"]:has-text("最新")',
        'text=最新',
    )
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if not await loc.count() or not await loc.is_visible():
                continue
            await human_click(page, loc, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="action")
            return True
        except Exception:
            continue
    return False


async def scroll_comment_sidebar_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 1,
) -> bool:
    scrolled_any = False
    for _ in range(rounds):
        scrolled = await page.evaluate(COMMENT_SIDEBAR_SCROLL_JS)
        if scrolled:
            scrolled_any = True
        wheeled = await _wheel_comment_list_area(page, settings, tenant_id=tenant_id)
        if wheeled:
            scrolled_any = True
        if not scrolled_any:
            try:
                header = page.locator("text=全部评论").first
                if await header.count():
                    box = await header.bounding_box()
                    if box:
                        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 120)
                        await page.mouse.wheel(0, 520)
                        scrolled_any = True
                        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
            except Exception:
                pass
        else:
            await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
    return scrolled_any


def merge_comment_api_pages(
    captured_pages: list[dict[str, Any]],
    *,
    max_comments: int,
) -> tuple[dict[str, dict[str, Any]], int, list[dict[str, Any]]]:
    comments_map: dict[str, dict[str, Any]] = {}
    api_total = 0
    for index, data in enumerate(captured_pages):
        if index == 0:
            api_total = int(data.get("total") or 0)
        for item in data.get("comments") or []:
            row = _normalize_comment(item)
            if row["comment_id"]:
                comments_map[row["comment_id"]] = row
                for reply in item.get("reply_comment") or []:
                    reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                    if reply_row["comment_id"]:
                        comments_map[reply_row["comment_id"]] = reply_row

    comments = list(comments_map.values())
    comments.sort(key=lambda row: row.get("create_time") or 0, reverse=True)
    top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
    return comments_map, api_total, top_rows


async def find_comment_item_locator(
    page,
    *,
    comment_id: str = "",
    comment_text: str = "",
):
    needle = (comment_text or "").strip()[:40]
    cid = (comment_id or "").strip()
    selectors = ('[data-e2e="comment-item"]', '[class*="CommentItem"]')
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for index in range(count):
            item = loc.nth(index)
            try:
                dom_cid = (await item.get_attribute("data-cid")) or ""
                if cid and (dom_cid == cid or cid in dom_cid):
                    return item
                if needle:
                    text = (await item.inner_text(timeout=1500)) or ""
                    if needle in text:
                        return item
            except Exception:
                continue
    return None


async def scroll_comment_sidebar_until(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str = "",
    comment_text: str = "",
    max_rounds: int = 8,
):
    await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
    target = await find_comment_item_locator(
        page,
        comment_id=comment_id,
        comment_text=comment_text,
    )
    if target is not None:
        return target

    for _ in range(max(1, max_rounds)):
        await scroll_comment_sidebar_on_page(page, settings, tenant_id=tenant_id, rounds=1)
        target = await find_comment_item_locator(
            page,
            comment_id=comment_id,
            comment_text=comment_text,
        )
        if target is not None:
            return target
    return None


async def close_feed_detail_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> None:
    if not await is_feed_detail_open(page):
        return
    for selector in _CLOSE_FEED_SELECTORS:
        btn = page.locator(selector).first
        try:
            if await btn.count() and await btn.is_visible():
                await human_click(page, btn, settings, tenant_id=tenant_id)
                await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                return
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    except Exception:
        pass


def extract_comment_total_from_page_text(text: str) -> int | None:
    match = re.search(r"全部评论\s*\(?\s*(\d+)\s*\)?", text)
    if match:
        return int(match.group(1))
    return None
