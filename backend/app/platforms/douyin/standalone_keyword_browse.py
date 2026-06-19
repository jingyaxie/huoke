"""抖音关键词搜索 → 逐视频浏览评论 → 评估线索 → 分配触达动作。

与 skill / 智能体 / DouyinCommentCrawler 彼此独立，固定 UI 流程：
1. 打开 https://www.douyin.com/
2. 搜索框逐字输入关键词，Enter 搜索
3. 点击筛选，按 days 选发布时间
4. 按列表顺序点击视频（从第一个开始）
5. 打开评论侧栏，拦截 comment/list，评估符合意图的评论
6. 慢速滚动评论；命中则按 action_policy 分配 reply/dm/follow，保存精准线索
7. 评论过旧或看完 → 返回列表 → 下一个视频，重复 5–7
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from playwright.async_api import Page
from sqlalchemy.orm import Session

from app.core.antibot import human_click, human_delay
from app.core.config import Settings
from app.platforms.douyin.human_guards import (
    HumanBrowseGuardError,
    assert_douyin_human_ready,
    is_captcha_page,
)
from app.platforms.douyin.js_constants import COMMENT_PATH, PLATFORM, _extract_aweme_id
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.douyin.video_comments_passive import (
    _days_cutoff_ts,
    _filter_comments_by_days,
    _last_list_page,
    _merge_captured_pages,
    _newest_top_create_time_in_page,
    _page_signature,
    _should_stop_for_time_window,
)
from app.services.outreach_policy import OutreachAction, choose_outreach_action, random_interval_sec
from app.services.supervisor_outreach import persist_crawl_skill_result
from app.services.ui_flow.step_overlay import clear_page_step_hint, set_page_step_hint
from app.services.ui_flow.params import parse_ui_flow_params
from app.services.ui_flow.platforms.douyin.feed_ui import (
    _comment_sidebar_active,
    activate_comment_sidebar_on_page,
    classify_douyin_page,
    close_feed_detail_on_page,
    feed_overlay_visible,
    is_feed_detail_open,
    scroll_comment_sidebar_on_page,
    search_list_visible,
    select_latest_comment_sort_on_page,
    wait_feed_detail,
)
from app.services.ui_flow.platforms.douyin.browse_ui import (
    _VIDEO_CARD_SELECTORS,
    _click_video_link_at_index,
    _open_feed_via_modal_id,
    _resolve_aweme_id_at_index,
    click_search_poster,
)
from app.services.ui_flow.platforms.douyin.search_parse import (
    analyze_search_api_response,
    extract_aweme_items_from_json,
    is_search_result_api,
    mark_search_api_flags,
    rank_search_items,
    search_api_min_items,
)
from app.services.ui_flow.platforms.douyin.search_ui import (
    _POSTER_SELECTORS,
    collect_video_urls_from_page,
    page_has_search_posters,
    page_has_video_results,
    release_searchbar_focus,
    run_search,
    scroll_search_results_page,
)
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

CAPTURE_METHOD = "standalone_keyword_browse"
DOUYIN_ENTRY_URL = "https://www.douyin.com/"


def _on_search_results_url(url: str) -> bool:
    u = (url or "").lower()
    return "/search/" in u or "/jingxuan/search/" in u


def _sync_search_aweme_ids_from_api(
    ctx: DouyinUiSession,
    api_items: dict[str, dict],
) -> list[str]:
    """用拦截到的 search/single API 顺序确定要点哪个视频（不依赖 DOM href）。"""
    if not api_items:
        return list(ctx.state.get("search_aweme_ids") or [])
    ranked = rank_search_items(list(api_items.values()), ctx.params.keyword)
    aweme_ids = [str(row.get("aweme_id") or "") for row in ranked if str(row.get("aweme_id") or "")]
    if aweme_ids:
        ctx.state["search_aweme_ids"] = aweme_ids
        ctx.state["search_poster_mode"] = True
    return aweme_ids


async def _is_search_list_ready(
    page: Page,
    api_items: dict[str, dict],
    *,
    ctx: DouyinUiSession | None = None,
) -> bool:
    """列表已展示即视为搜索成功：search API 有明确结论，或 DOM 海报/链接可见。"""
    if not _on_search_results_url(page.url or ""):
        return False
    if api_items:
        return True
    if ctx and ctx.state.get("search_api_complete"):
        return True
    return bool(await page_has_search_posters(page) or await page_has_video_results(page))


async def _page_phase_note(page: Page) -> str:
    snap = await classify_douyin_page(page)
    return (
        f"phase={snap.get('phase')} feed={snap.get('feed_visible')} "
        f"list={snap.get('list_visible')} modal_param={snap.get('has_modal_param')}"
    )


async def _wait_feed_opened(page: Page, *, max_sec: float = 4.0) -> bool:
    return await wait_feed_detail(page, max_sec=max_sec)


async def _search_list_visible(page: Page) -> bool:
    if not _on_search_results_url(page.url or ""):
        return False
    if "modal_id=" in (page.url or "").lower() and await feed_overlay_visible(page):
        return False
    return await search_list_visible(page)


async def _back_to_search_list(ctx: DouyinUiSession) -> bool:
    """从 Feed 回到搜索列表，准备点下一个 item。返回 True 表示列表可继续点击。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id

    if await _search_list_visible(page):
        ctx.state["feed_mode"] = False
        return True

    on_search = _on_search_results_url(page.url or "")
    if on_search and await _count_search_posters(page) > 0:
        ctx.state["feed_mode"] = False
        return True

    if ctx.state.get("feed_mode") or "modal_id=" in (page.url or "").lower() or (
        not on_search and await is_feed_detail_open(page)
    ):
        for _ in range(2):
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.18)
        await close_feed_detail_on_page(page, settings, tenant_id=tenant_id)
        ctx.state["feed_mode"] = False

    if _on_search_results_url(page.url or ""):
        for _ in range(15):
            if await _search_list_visible(page):
                await release_searchbar_focus(page)
                return True
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.12)

    search_url = str(ctx.state.get("search_url") or "")
    if search_url and not await page_has_search_posters(page):
        need_goto = (
            "/search/" not in (page.url or "").lower()
            or "modal_id=" in (page.url or "").lower()
            or await is_feed_detail_open(page)
        )
        if need_goto:
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
            except Exception:
                pass
            for _ in range(10):
                if await _search_list_visible(page):
                    await release_searchbar_focus(page)
                    return True
                await asyncio.sleep(0.12)

    await release_searchbar_focus(page)
    return await _search_list_visible(page)


_CLICK_POSTER_SELECTORS = (
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
    '[class*="search-result-card"]',
    'div.search-result-card',
    '[data-e2e="search-card-video"]',
    '[class*="SearchVideoCard"]',
    *_VIDEO_CARD_SELECTORS,
)

_VISIBLE_SEARCH_CARDS_JS = """
() => {
  const out = [];
  const seen = new Set();
  const isInViewport = (r) => (
    r.width >= 24 && r.height >= 24 &&
    r.bottom > 8 && r.top < window.innerHeight - 8 &&
    r.right > 8 && r.left < window.innerWidth - 8
  );
  const pickNode = (el) => {
    const chain = [
      el.closest('[class*="discover-video-card"]'),
      el.closest('[data-e2e="search-card-video"]'),
      el.closest('[class*="search-result-card"]'),
      el.closest('div.search-result-card'),
      el.closest('[class*="SearchVideoCard"]'),
      el.closest('a[href*="/video/"]'),
      el.tagName === 'IMG' ? el.parentElement : null,
      el,
    ];
    for (const node of chain) {
      if (!node) continue;
      const r = node.getBoundingClientRect();
      if (r.width >= 24 && r.height >= 24) return { node, rect: r };
    }
    return null;
  };
  const selectors = [
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
    '[data-e2e="search-card-video"]',
    'div.search-result-card',
    '[class*="search-result-card"]',
    '[class*="SearchVideoCard"]',
    '[class*="videoImage"] img',
    'a[href*="/video/"]',
  ];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const picked = pickNode(el);
      if (!picked || !isInViewport(picked.rect)) continue;
      const r = picked.rect;
      const key = `${Math.round(r.top)}:${Math.round(r.left)}:${Math.round(r.width)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const hrefEl = el.closest('a[href*="/video/"]')
        || el.querySelector?.('a[href*="/video/"]')
        || (el.href ? el : null);
      const href = hrefEl?.href || el.href || '';
      let aweme = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
      if (!aweme) {
        const holder = el.closest('[data-aweme-id]') || el;
        aweme = String(holder.getAttribute('data-aweme-id') || '').trim();
      }
      out.push({
        top: r.top,
        left: r.left,
        width: r.width,
        height: r.height,
        aweme,
        selector: sel,
      });
    }
  }
  out.sort((a, b) => a.top - b.top || a.left - b.left);
  return out;
}
"""

_CLICK_SEARCH_CARD_JS = """
(index) => {
  const selectors = [
    '[class*="discover-video-card"]',
    'div.search-result-card',
    '[data-e2e="search-card-video"]',
    '[class*="search-result-card"]',
    '[class*="SearchVideoCard"]',
    '[class*="videoImage"] img',
  ];
  for (const sel of selectors) {
    const nodes = Array.from(document.querySelectorAll(sel));
    if (nodes.length <= index) continue;
    let target = nodes[index];
    if (target.tagName === 'IMG') {
      target = target.closest(
        '[class*="discover-video-card"], [data-e2e="search-card-video"], '
        + '[class*="search-result-card"], [class*="SearchVideoCard"]'
      ) || target.parentElement || target;
    }
    target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
    const r = target.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (typeof target.click === 'function') target.click();
    else {
      target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    }
    const href = (target.closest('a[href*="/video/"]') || target.querySelector('a[href*="/video/"]'))?.href || '';
    let aweme = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
    if (!aweme) {
      const holder = target.closest('[data-aweme-id]') || target;
      aweme = String(holder.getAttribute('data-aweme-id') || '').trim();
    }
    return { ok: true, selector: sel, total: nodes.length, aweme, top: r.top, left: r.left };
  }
  return { ok: false, selector: '', total: 0, aweme: '', top: 0, left: 0 };
}
"""


async def _click_search_card_via_js(ctx: DouyinUiSession, index: int) -> tuple[bool, str, str]:
    """虚拟列表：按 DOM 序号 scrollIntoView 后 JS 点击。"""
    page = ctx.page
    try:
        result = await page.evaluate(_CLICK_SEARCH_CARD_JS, index)
    except Exception as exc:
        return False, f"js_click_failed:{exc}", ""
    if not isinstance(result, dict) or not result.get("ok"):
        total = int((result or {}).get("total") or 0) if isinstance(result, dict) else 0
        return False, f"js_click_miss index={index} total={total}", ""
    aweme = str(result.get("aweme") or "")
    sel = str(result.get("selector") or "js_card")
    await asyncio.sleep(random.uniform(0.35, 0.65))
    if await _wait_feed_opened(page, max_sec=5.0):
        ctx.state["feed_mode"] = True
        return True, f"js_click:{sel} index={index} total={result.get('total')}", aweme
    top = float(result.get("top") or 0)
    left = float(result.get("left") or 0)
    if top > 0 and left > 0:
        await page.mouse.click(left + 40, top + 40)
        if await _wait_feed_opened(page, max_sec=3.0):
            ctx.state["feed_mode"] = True
            return True, f"js_coord:{sel} index={index}", aweme
    return False, f"js_clicked_no_feed:{sel}[{index}]", aweme


async def _collect_visible_search_cards(page: Page) -> list[dict[str, Any]]:
    try:
        cards = await page.evaluate(_VISIBLE_SEARCH_CARDS_JS)
    except Exception:
        return []
    return cards if isinstance(cards, list) else []


_SEARCH_CARD_PICK_JS = _VISIBLE_SEARCH_CARDS_JS


async def _scroll_search_until_card_index(
    ctx: DouyinUiSession,
    index: int,
    *,
    max_scrolls: int = 12,
) -> list[dict[str, Any]]:
    """虚拟列表下滚动直到第 index 个可见卡片出现（仅在搜索列表页执行）。"""
    page = ctx.page
    if not await search_list_visible(page):
        return await _collect_visible_search_cards(page)

    cards: list[dict[str, Any]] = []
    scroll_budget = 0 if index <= 0 else max_scrolls
    for _ in range(scroll_budget + 1):
        cards = await _collect_visible_search_cards(page)
        if len(cards) > index:
            return cards
        if await feed_overlay_visible(page) or not await search_list_visible(page):
            break
        if scroll_budget <= 0:
            break
        scroll_budget -= 1
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(0.35)
    return cards


async def _resolve_best_poster_selector(page: Page, index: int) -> tuple[str, int]:
    """找出能覆盖 index 且可见条目最多的海报选择器。"""
    best_selector = ""
    best_count = 0
    best_score = -1
    for selector in (
        '[class*="discover-video-card"]',
        'img.discover-video-card-img',
        'div.search-result-card',
        '[class*="search-result-card"]',
        '[data-e2e="search-card-video"]',
        '[class*="SearchVideoCard"]',
        '[class*="videoImage"] img',
        *_VIDEO_CARD_SELECTORS,
        *_POSTER_SELECTORS,
    ):
        try:
            loc = page.locator(selector)
            count = await loc.count()
        except Exception:
            continue
        if count <= index:
            continue
        visible = 0
        for i in range(min(count, max(index + 1, 6))):
            try:
                if await loc.nth(i).is_visible():
                    visible += 1
            except Exception:
                continue
        score = visible * 1000 + count
        if score > best_score:
            best_score = score
            best_count = count
            best_selector = selector
    return best_selector, best_count


async def _click_visible_card_coords(
    page: Page,
    card: dict[str, Any],
    *,
    settings: Settings,
    tenant_id: str,
) -> bool:
    x = float(card.get("left") or 0) + float(card.get("width") or 0) / 2
    y = float(card.get("top") or 0) + float(card.get("height") or 0) / 2
    await page.mouse.move(x, y)
    await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
    await page.mouse.click(x, y)
    return await _wait_feed_opened(page, max_sec=4.0)


async def _click_search_img_poster(ctx: DouyinUiSession, index: int) -> tuple[bool, str]:
    """点击搜索列表封面（优先可见卡片坐标，兼容精选页虚拟列表）。"""
    page = ctx.page
    cards = await _scroll_search_until_card_index(ctx, index)
    if len(cards) > index:
        card = cards[index]
        if await _click_visible_card_coords(
            page,
            card,
            settings=ctx.settings,
            tenant_id=ctx.tenant_id,
        ):
            ctx.state["feed_mode"] = True
            sel = str(card.get("selector") or "visible_card")
            return True, f"visible_coord:{sel} index={index}"

    selector, count = await _resolve_best_poster_selector(page, index)
    if not selector:
        return False, f"img_click_no_target count={count} visible={len(cards)}"
    target = page.locator(selector).nth(index)
    if " img" in selector or "discover-video-card-img" in selector:
        parent = target.locator(
            "xpath=ancestor::*[@data-e2e='search-card-video' or "
            "contains(@class,'search-result-card') or contains(@class,'SearchVideoCard') or "
            "contains(@class,'discover-video-card')][1]"
        )
        if await parent.count():
            target = parent.first
    try:
        if await target.is_visible():
            await target.scroll_into_view_if_needed(timeout=3000)
            try:
                await human_click(page, target, ctx.settings, tenant_id=ctx.tenant_id)
            except Exception:
                await target.click(force=True, timeout=4000)
        else:
            box = await target.bounding_box()
            if box:
                await page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
            else:
                await target.click(force=True, timeout=4000)
        if await _wait_feed_opened(page, max_sec=5.0):
            ctx.state["feed_mode"] = True
            return True, f"img_click:{selector} index={index}"
    except Exception as exc:
        box = await target.bounding_box()
        if box:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            await page.mouse.click(x, y)
            if await _wait_feed_opened(page, max_sec=5.0):
                ctx.state["feed_mode"] = True
                return True, f"img_coord:{selector} index={index}"
        return False, f"img_click_fail:{selector}[{index}] {exc}"
    return False, f"img_click_no_feed:{selector}[{index}] visible={len(cards)}"


async def _click_search_card_via_dom(
    ctx: DouyinUiSession,
    index: int,
) -> tuple[bool, str, str]:
    """用页面内可见卡片坐标点击（兼容精选页 discover-video-card）。"""
    page = ctx.page
    try:
        cards = await _scroll_search_until_card_index(ctx, index)
    except Exception as exc:
        return False, f"dom_pick_failed:{exc}", ""
    if not isinstance(cards, list) or len(cards) <= index:
        return False, f"dom_cards={len(cards) if isinstance(cards, list) else 0}", ""
    card = cards[index]
    aweme = str(card.get("aweme") or "")
    if await _click_visible_card_coords(
        page,
        card,
        settings=ctx.settings,
        tenant_id=ctx.tenant_id,
    ):
        ctx.state["feed_mode"] = True
        return True, f"dom_click index={index} aweme={aweme[:12] if aweme else 'dom'}", aweme
    return False, f"dom_clicked_no_feed index={index}", aweme


async def _click_search_result_item(
    ctx: DouyinUiSession,
    index: int,
    *,
    skip_back: bool = False,
) -> tuple[bool, str]:
    """点击搜索列表第 N 个视频：aweme 直开优先，DOM 点击兜底；每步校验页面阶段。"""
    page = ctx.page
    if not skip_back:
        if not await _back_to_search_list(ctx):
            return False, "未能返回搜索列表"
    else:
        await asyncio.sleep(random.uniform(0.12, 0.28))

    await _sync_search_aweme_ids_from_dom(ctx)
    aweme_hint = await _resolve_aweme_id_at_index(ctx, index)
    phase_before = await _page_phase_note(page)
    ctx.phase_log.append(
        f"CLICK_PREP index={index} posters={await _count_search_posters(page)} "
        f"best={await _resolve_best_poster_selector(page, index)} aweme={aweme_hint[:12] if aweme_hint else 'none'} "
        f"{phase_before}"
    )

    async def _confirm_feed_open(method: str) -> tuple[bool, str]:
        snap = await classify_douyin_page(page)
        if await wait_feed_detail(page, max_sec=5.0):
            ctx.state["feed_mode"] = True
            return True, (
                f"{method} index={index} aweme={aweme_hint[:12] if aweme_hint else 'dom'} "
                f"phase={snap.get('phase')}"
            )
        return False, (
            f"{method}_no_feed index={index} phase={snap.get('phase')} "
            f"feed={snap.get('feed_visible')} list={snap.get('list_visible')}"
        )

    if aweme_hint and await _open_feed_via_modal_id(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("modal_open")
        if ok:
            return True, note

    if aweme_hint and await _open_feed_via_video_url(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("video_url_open")
        if ok:
            return True, note

    if not await search_list_visible(page):
        return False, f"无法 DOM 点击：当前不在搜索列表；{await _page_phase_note(page)}"

    last_note = f"未找到可点击的列表 item；api_aweme={aweme_hint or 'none'}"

    if index > 0:
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(0.35)

    js_ok, js_note, js_aweme = await _click_search_card_via_js(ctx, index)
    if js_ok:
        ok, note = await _confirm_feed_open(js_note.split()[0] if js_note else "js_click")
        if ok:
            if js_aweme and not aweme_hint:
                ids = list(ctx.state.get("search_aweme_ids") or [])
                if js_aweme not in ids:
                    ids.append(js_aweme)
                    ctx.state["search_aweme_ids"] = ids
            return True, note
        last_note = note

    img_ok, img_note = await _click_search_img_poster(ctx, index)
    if img_ok:
        ok, note = await _confirm_feed_open(img_note.split(":")[0] if img_note else "img_click")
        if ok:
            return True, note
        last_note = note

    dom_ok, dom_note, dom_aweme = await _click_search_card_via_dom(ctx, index)
    if dom_ok:
        ok, note = await _confirm_feed_open("dom_click")
        if ok:
            if dom_aweme and not aweme_hint:
                ids = list(ctx.state.get("search_aweme_ids") or [])
                if dom_aweme not in ids:
                    ids.append(dom_aweme)
                    ctx.state["search_aweme_ids"] = ids
            return True, note
        last_note = note
    elif dom_note:
        last_note = f"{last_note}; {dom_note}"

    if await click_search_poster(ctx, index):
        ok, note = await _confirm_feed_open("browse_ui_poster")
        if ok:
            return True, note
        last_note = note

    best_selector = ""
    best_count = 0
    for selector in _CLICK_POSTER_SELECTORS:
        try:
            count = await page.locator(selector).count()
        except Exception:
            continue
        if count > index and count > best_count:
            best_count = count
            best_selector = selector

    if best_selector:
        item = page.locator(best_selector).nth(index)
        try:
            with contextlib.suppress(Exception):
                await page.evaluate(
                    """(args) => {
                      const [sel, idx] = args;
                      const nodes = Array.from(document.querySelectorAll(sel));
                      const el = nodes[idx];
                      if (el) el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
                    }""",
                    [best_selector, index],
                )
                await asyncio.sleep(0.3)
            if await item.is_visible():
                await human_click(page, item, ctx.settings, tenant_id=ctx.tenant_id)
            else:
                await item.click(force=True, timeout=4000)
            ok, note = await _confirm_feed_open(f"poster_click:{best_selector}")
            if ok:
                return True, note
            last_note = note
        except Exception as exc:
            last_note = f"{best_selector}[{index}] 点击异常: {exc}"

    if await _click_video_link_at_index(ctx, index):
        ok, note = await _confirm_feed_open("link_click")
        if ok:
            return True, note
        last_note = note

    if aweme_hint and await _open_feed_via_modal_id(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("modal_fallback")
        if ok:
            return True, note

    if aweme_hint and await _open_feed_via_video_url(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("video_url_fallback")
        if ok:
            return True, note

    return False, f"{last_note}; {await _page_phase_note(page)}"


def _match_comment(comment_text: str, keywords: list[str], exclude: list[str] | None = None) -> bool:
    """简单关键词匹配，过滤招聘/广告等噪声。"""
    text = (comment_text or "").strip()
    if not text:
        return False
    exclude = exclude or []
    for word in exclude:
        if word and word in text:
            return False
    if not keywords:
        return True
    return any(k and k in text for k in keywords)


@dataclass
class StandaloneKeywordBrowseConfig:
    """独立关键词浏览任务配置（不依赖 skill / agent）。"""

    keyword: str
    days: int = 7
    content_limit: int = 5
    target_precise_leads: int = 3
    max_videos_to_browse: int = 50
    comment_days: int | None = None
    region: str | None = None
    match_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_comment_length: int = 4
    max_comments_per_video: int = 120
    comment_scroll_rounds: int = 24
    watch_seconds_min: int = 3
    watch_seconds_max: int = 8
    action_policy: dict[str, Any] = field(
        default_factory=lambda: {
            "comment_ratio": 50,
            "dm_ratio": 30,
            "follow_ratio": 20,
            "interval_min_sec": 10,
            "interval_max_sec": 30,
        }
    )
    execute_outreach: bool = False
    test_all_outreach: bool = False
    reply_text: str = ""
    dm_text: str = ""
    persist_to_db: bool = True
    use_llm_eval: bool = False
    eval_spec: dict[str, Any] | None = None
    task_brief: Any | None = None
    reuse_stable_session: bool = True
    close_browser_after: bool = False


@dataclass
class PreciseLeadRecord:
    """单条精准线索。"""

    comment_id: str
    comment_text: str
    username: str
    user_id: str
    sec_uid: str
    video_url: str
    aweme_id: str
    create_time: int
    match_score: float
    match_reason: str
    planned_action: OutreachAction
    outreach_executed: bool = False
    outreach_result: dict[str, Any] = field(default_factory=dict)
    raw_comment: dict[str, Any] = field(default_factory=dict)


@dataclass
class StandaloneKeywordBrowseResult:
    ok: bool
    keyword: str
    search_url: str = ""
    videos_processed: int = 0
    comments_scanned: int = 0
    duplicates_skipped: int = 0
    precise_leads: list[PreciseLeadRecord] = field(default_factory=list)
    phase_log: list[str] = field(default_factory=list)
    diagnostic: str | None = None
    output_file: str | None = None
    error: str | None = None
    target_reached: bool = False


async def _count_search_posters(page: Page) -> int:
    best = 0
    for selector in (*_POSTER_SELECTORS, *_VIDEO_CARD_SELECTORS):
        try:
            best = max(best, await page.locator(selector).count())
        except Exception:
            continue
    return best


async def _sync_search_aweme_ids_from_dom(ctx: DouyinUiSession) -> list[str]:
    """从搜索列表 DOM 链接或 data-aweme-id 补齐 aweme_id 顺序（API 未拦截时的兜底）。"""
    existing = list(ctx.state.get("search_aweme_ids") or [])
    if existing:
        return existing
    page = ctx.page
    try:
        dom_ids = await page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              const nodes = document.querySelectorAll(
                '[data-aweme-id], [class*="discover-video-card"], div.search-result-card, [data-e2e="search-card-video"]'
              );
              for (const el of nodes) {
                const raw = String(el.getAttribute('data-aweme-id') || '').trim();
                if (/^\\d{8,22}$/.test(raw) && !seen.has(raw)) {
                  seen.add(raw);
                  out.push(raw);
                  continue;
                }
                const href = (el.closest('a[href*="/video/"]') || el.querySelector('a[href*="/video/"]'))?.href || '';
                const part = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
                if (/^\\d{8,22}$/.test(part) && !seen.has(part)) {
                  seen.add(part);
                  out.push(part);
                }
              }
              return out;
            }"""
        )
        if isinstance(dom_ids, list):
            ids = [str(i) for i in dom_ids if re.fullmatch(r"\d{8,22}", str(i))]
            if ids:
                ctx.state["search_aweme_ids"] = ids
                ctx.state["search_poster_mode"] = True
                return ids
    except Exception:
        pass
    try:
        cards = await page.evaluate(_SEARCH_CARD_PICK_JS)
        if isinstance(cards, list):
            ids: list[str] = []
            seen: set[str] = set()
            for card in cards:
                part = str((card or {}).get("aweme") or "")
                if re.fullmatch(r"\d{8,22}", part) and part not in seen:
                    seen.add(part)
                    ids.append(part)
            if ids:
                ctx.state["search_aweme_ids"] = ids
                ctx.state["search_poster_mode"] = True
                return ids
    except Exception:
        pass
    urls = await collect_video_urls_from_page(page, limit=max(10, int(ctx.params.content_limit or 5) * 3))
    ids: list[str] = []
    seen: set[str] = set()
    for url in urls:
        part = str(url or "").rstrip("/").split("/")[-1]
        if re.fullmatch(r"\d{8,22}", part) and part not in seen:
            seen.add(part)
            ids.append(part)
    if ids:
        ctx.state["search_aweme_ids"] = ids
        ctx.state["search_poster_mode"] = True
    return ids


async def _prepare_search_list_for_browse(ctx: DouyinUiSession) -> bool:
    """搜索完成后等待列表可点：确保在搜索页，DOM 海报或 API aweme_id 任一就绪。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id
    search_url = str(ctx.state.get("search_url") or page.url or "")

    if search_url and not _on_search_results_url(page.url or ""):
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
        except Exception:
            pass

    deadline = asyncio.get_running_loop().time() + 28.0
    round_idx = 0
    while asyncio.get_running_loop().time() < deadline:
        aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
        if aweme_ids:
            return True
        poster_count = await _count_search_posters(page)
        if poster_count > 0:
            await _sync_search_aweme_ids_from_dom(ctx)
            return True
        if ctx.video_urls:
            return True
        if round_idx % 3 == 2 and _on_search_results_url(page.url or ""):
            await scroll_search_results_page(page, settings, tenant_id=tenant_id)
        await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
        round_idx += 1

    return bool(ctx.state.get("search_aweme_ids")) or await _count_search_posters(page) > 0


async def _open_feed_via_video_url(ctx: DouyinUiSession, aweme_id: str) -> bool:
    """无搜索列表 DOM 时，直链打开视频页作为兜底。"""
    if not aweme_id or not re.fullmatch(r"\d{8,22}", str(aweme_id)):
        return False
    page = ctx.page
    try:
        await page.goto(
            f"https://www.douyin.com/video/{aweme_id}",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await human_delay(page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        ctx.state["feed_mode"] = True
        return await wait_feed_detail(page, max_sec=6.0) or "/video/" in (page.url or "")
    except Exception:
        return False


async def _ensure_search_item_index(ctx: DouyinUiSession, index: int) -> bool:
    """列表 item 不足时滚动加载，直到 index 可点或达到尝试上限。"""
    page = ctx.page
    aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
    if len(aweme_ids) > index:
        return True
    if not await search_list_visible(page):
        return len(aweme_ids) > index
    if await _count_search_posters(page) > index:
        return True
    for _ in range(4):
        if not await search_list_visible(page):
            break
        if await _count_search_posters(page) > index:
            return True
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(random.uniform(0.5, 1.0))
    return len(aweme_ids) > index or await _count_search_posters(page) > index


def _persist_precise_lead(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> int:
    """单条精准线索入库。"""
    if not lead.comment_id:
        return 0
    block = {
        "platform": PLATFORM,
        "aweme_id": lead.aweme_id,
        "video_url": lead.video_url,
        "comments": [lead.raw_comment],
        "keyword_context": {"keyword": config.keyword, "capture_mode": CAPTURE_METHOD, "status": "precise"},
    }
    try:
        return persist_crawl_skill_result(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=PLATFORM,
            skill_result={"results": [block]},
            source_keyword=config.keyword,
        )
    except Exception:
        return 0


async def _execute_all_outreach_for_lead(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> dict[str, Any]:
    """命中精准线索后依次测试：回复 → 关注 → 私信。"""
    from app.services.social_roam.human.douyin.actions import (
        human_follow_user,
        human_open_profile_from_comment,
        human_reply_comment,
        human_send_dm,
    )

    results: dict[str, Any] = {}
    policy = config.action_policy or {}
    interval = lambda: random_interval_sec(
        int(policy.get("interval_min_sec") or 8),
        int(policy.get("interval_max_sec") or 18),
    )

    if config.reply_text:
        await set_page_step_hint(
            page,
            "触达：回复评论",
            sub=(lead.username or lead.comment_text or "")[:40],
            title="Huoke · 抖音浏览",
        )
        results["reply"] = await human_reply_comment(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=lead.video_url,
            reply_text=config.reply_text,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
        )
        await asyncio.sleep(interval())

    profile_page = None
    if lead.sec_uid:
        profile_page, open_meta = await human_open_profile_from_comment(
            page,
            settings,
            tenant_id=tenant_id,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
        )
        results["open_profile"] = open_meta
        if not open_meta.get("ok"):
            return results
        await asyncio.sleep(interval())

    if lead.sec_uid:
        await set_page_step_hint(page, "触达：关注用户", sub=lead.username or lead.sec_uid[:16])
        results["follow"] = await human_follow_user(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            sec_uid=lead.sec_uid,
            user_id=lead.user_id,
            username=lead.username,
            profile_page=profile_page,
        )
        await asyncio.sleep(interval())

    if config.dm_text and lead.sec_uid:
        await set_page_step_hint(page, "触达：发送私信", sub=config.dm_text)
        results["dm"] = await human_send_dm(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            sec_uid=lead.sec_uid,
            message=config.dm_text,
            username=lead.username,
            profile_page=profile_page,
        )

    results["ok"] = any(
        isinstance(v, dict) and v.get("ok") for k, v in results.items() if k in {"reply", "follow", "dm"}
    )
    return results


def _comment_id_from_row(row: dict[str, Any]) -> str:
    return str(row.get("comment_id") or "").strip()


def _take_unique_comments(
    rows: list[dict[str, Any]],
    seen_comment_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """按 comment_id 去重：跨视频、跨滚动轮次均不重复处理。"""
    unique: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        cid = _comment_id_from_row(row)
        if not cid:
            continue
        if cid in seen_comment_ids:
            skipped += 1
            continue
        seen_comment_ids.add(cid)
        unique.append(row)
    return unique, skipped


def _build_ui_session(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    config: StandaloneKeywordBrowseConfig,
) -> DouyinUiSession:
    raw: dict[str, Any] = {
        "keyword": config.keyword,
        "content_limit": max(1, int(config.content_limit)),
        "days": config.days,
        "ui_search_only": True,
        "inline_ui_outreach": False,
        "platform_options": {"entry": "home"},
    }
    if config.region:
        raw["region"] = config.region
    params = parse_ui_flow_params(raw, platform="douyin")
    return DouyinUiSession(
        settings=settings,
        tenant_id=tenant_id,
        account_id=account_id,
        params=params,
        page=page,
    )


async def _report_step(
    ctx: DouyinUiSession,
    message: str,
    *,
    sub: str = "",
    log: bool = True,
) -> None:
    """右上角步骤条 + phase_log 同步更新。"""
    if log:
        line = message if not sub else f"{message} | {sub}"
        ctx.phase_log.append(line[:240])
    await set_page_step_hint(ctx.page, message, sub=sub, title="Huoke · 抖音浏览")


async def _wait_captcha_if_needed(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    headless: bool = False,
    max_wait_sec: int = 300,
) -> None:
    """可见浏览器：遇验证码时等待人工完成，而非立即失败。"""
    if not await is_captcha_page(page):
        return
    await set_page_step_hint(page, "等待验证码", sub="请在浏览器中完成人机验证", title="Huoke · 抖音浏览")
    if headless:
        raise HumanBrowseGuardError("命中验证码中间页，请用有头浏览器完成验证后重试")
    deadline = asyncio.get_running_loop().time() + max(30, int(max_wait_sec))
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(2.5)
        if not await is_captcha_page(page):
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            return
    raise HumanBrowseGuardError("验证码等待超时，请在浏览器中完成人机验证后重试")


async def _open_douyin_home(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    store: DouyinSessionStore,
    headless: bool = False,
    stable_session: Any | None = None,
) -> None:
    """步骤 1：打开抖音首页并等待加载完成。

    稳定基座模式下若当前标签已在抖音首页，则跳过 goto，复用桌面已登录会话。
    """
    from app.services.browser_workbench import is_douyin_home_like, should_skip_stable_goto

    await set_page_step_hint(page, "步骤 1/7：打开抖音首页", title="Huoke · 抖音浏览")
    skip_goto = False
    if stable_session is not None:
        skip, reason = should_skip_stable_goto(stable_session, DOUYIN_ENTRY_URL)
        if skip:
            skip_goto = True
        elif is_douyin_home_like(page.url or ""):
            skip_goto = True
            reason = "already_on_home"
        if skip_goto:
            await set_page_step_hint(page, "步骤 1/7：复用已打开首页", sub=reason or "")
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
            await assert_douyin_human_ready(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                store=store,
                stage="home",
                goto_home=False,
            )
            return

    await page.goto(DOUYIN_ENTRY_URL, wait_until="domcontentloaded", timeout=60000)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="home",
        goto_home=False,
    )


async def _run_search_phase(
    ctx: DouyinUiSession,
    *,
    config: StandaloneKeywordBrowseConfig,
) -> tuple[bool, str]:
    """步骤 2–3：逐字搜索 + 时间筛选。

    成功判定：搜索页 URL + 列表已展示（DOM 或 search API），不依赖 video_urls。
    """
    del config
    page = ctx.page
    await _report_step(
        ctx,
        "步骤 2/7：搜索关键词",
        sub=f"「{ctx.params.keyword}」· 筛选 {ctx.params.days} 天内",
        log=False,
    )
    api_items: dict[str, dict] = {}
    search_flags: dict[str, Any] = {}

    async def on_search_response(resp) -> None:
        if not is_search_result_api(str(resp.url or "")) or resp.status >= 400:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        need = search_api_min_items(ctx.params.content_limit)
        outcome = analyze_search_api_response(data, min_items=need)
        mark_search_api_flags(search_flags, outcome)
        if outcome.ready:
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = outcome.reason
        for row in extract_aweme_items_from_json(data):
            api_items.setdefault(str(row.get("aweme_id") or ""), row)
        if len(api_items) >= need:
            search_flags["api_complete"] = True
            search_flags["api_complete_reason"] = f"items={len(api_items)}"
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = search_flags["api_complete_reason"]

    page.on("response", on_search_response)
    try:
        await _report_step(ctx, "正在输入搜索词并提交…", log=False)
        search_result = await run_search(ctx)
        for _ in range(12):
            if api_items:
                break
            await asyncio.sleep(0.25)
        if search_result.ok and isinstance(search_result.data, dict):
            result_ids = search_result.data.get("search_aweme_ids") or []
            if result_ids:
                ctx.state["search_aweme_ids"] = [str(i) for i in result_ids if str(i)]
        aweme_ids = _sync_search_aweme_ids_from_api(ctx, api_items)
        list_ready = await _is_search_list_ready(page, api_items, ctx=ctx)

        if search_result.ok:
            if not aweme_ids:
                _sync_search_aweme_ids_from_api(ctx, api_items)
            ctx.state["search_ready"] = True
            ctx.state.setdefault("search_url", page.url)
            ctx.state["search_poster_mode"] = True
            api_count = len(api_items)
            api_reason = ctx.state.get("search_api_complete_reason") or search_flags.get("api_complete_reason")
            diag = search_result.diagnostic or "搜索完成"
            if api_count:
                diag += f"；api_videos={api_count}"
            if api_reason:
                diag += f"；api_status={api_reason}"
            await _report_step(
                ctx,
                "步骤 3/7：搜索完成",
                sub=f"已识别 {api_count or len(aweme_ids)} 个视频"
                + (f" · {api_reason}" if api_reason else ""),
                log=False,
            )
            return True, diag

        if list_ready:
            ctx.state["search_ready"] = True
            ctx.state["search_url"] = ctx.state.get("search_url") or page.url
            ctx.state["search_poster_mode"] = True
            ctx.phase_log.append(
                f"SEARCH_FALLBACK list_visible api={len(api_items)} url={page.url}"
            )
            await release_searchbar_focus(page)
            await _report_step(
                ctx,
                "步骤 3/7：列表已展示",
                sub=(
                    f"API {len(api_items)} 条"
                    + (
                        f" · {ctx.state.get('search_api_complete_reason')}"
                        if ctx.state.get("search_api_complete_reason")
                        else ""
                    )
                    + "，准备点击视频"
                ),
                log=False,
            )
            return True, (
                f"列表已展示，按 DOM 顺序点击（api={len(api_items)}）；"
                f"原判定={search_result.error or search_result.diagnostic or 'unknown'}"
            )

        return False, search_result.diagnostic or search_result.error or "搜索失败"
    finally:
        try:
            page.remove_listener("response", on_search_response)
        except Exception:
            pass


def _keyword_matches_comment(config: StandaloneKeywordBrowseConfig, text: str) -> bool:
    comment = (text or "").strip()
    if len(comment) < max(1, int(config.min_comment_length)):
        return False
    keywords = config.match_keywords or [config.keyword]
    return _match_comment(comment, keywords, config.exclude_keywords)


async def _evaluate_comments_batch(
    rows: list[dict[str, Any]],
    config: StandaloneKeywordBrowseConfig,
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    """评估评论：默认关键词匹配；可选 LLM 意图评估。"""
    out: dict[str, dict[str, Any]] = {}
    if config.use_llm_eval and config.eval_spec and config.task_brief:
        from app.services.lead_evaluation_service import (
            accept_evaluation_result,
            evaluate_comments_batch,
            is_precise_lead,
        )

        classified = await evaluate_comments_batch(
            rows,
            config.eval_spec,
            config.task_brief,
            settings=settings,
        )
        for cid, result in classified.items():
            if accept_evaluation_result(result, config.eval_spec) and is_precise_lead(result, config.eval_spec):
                out[cid] = result
        return out

    for row in rows:
        cid = str(row.get("comment_id") or "").strip()
        text = str(row.get("comment") or "").strip()
        if not cid or not _keyword_matches_comment(config, text):
            continue
        out[cid] = {
            "comment_id": cid,
            "is_lead": True,
            "score": 0.85,
            "reason": "关键词匹配",
            "worth_outreach": True,
        }
    return out


def _comment_response_handler(
    captured_pages: list[dict[str, Any]],
    *,
    seen_signatures: set[str],
):
    async def on_response(resp) -> None:
        url = str(resp.url or "")
        if COMMENT_PATH not in url or resp.status >= 400 or "/reply" in url:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        if not isinstance(data, dict):
            return
        sig = _page_signature(data)
        if sig in seen_signatures:
            return
        seen_signatures.add(sig)
        captured_pages.append(data)

    return on_response


async def _decide_outreach_action(
    config: StandaloneKeywordBrowseConfig,
    stats: dict[str, int],
) -> OutreachAction:
    policy = config.action_policy or {}
    action = choose_outreach_action(
        comment_ratio=int(policy.get("comment_ratio") or 50),
        dm_ratio=int(policy.get("dm_ratio") or 30),
        follow_ratio=int(policy.get("follow_ratio") or 20),
    )
    if action == "reply" and stats.get("replies", 0) >= int(policy.get("max_replies") or 9999):
        action = "dm"
    if action == "dm" and stats.get("dms", 0) >= int(policy.get("max_dms") or 9999):
        action = "follow"
    if action == "follow" and stats.get("follows", 0) >= int(policy.get("max_follows") or 9999):
        action = "skip"
    return action


async def _execute_outreach_if_needed(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    action: OutreachAction,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> dict[str, Any]:
    if not config.execute_outreach or action == "skip":
        return {"ok": False, "skipped": True, "action": action}

    if action == "reply" and config.reply_text:
        from app.services.social_roam.human.douyin.actions import human_reply_comment

        return await human_reply_comment(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=lead.video_url,
            reply_text=config.reply_text,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
        )
    if action in {"follow", "dm"} and lead.sec_uid:
        from app.services.social_roam.human.douyin.actions import (
            human_follow_user,
            human_open_profile_from_comment,
            human_send_dm,
        )

        profile_page, open_meta = await human_open_profile_from_comment(
            page,
            settings,
            tenant_id=tenant_id,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
        )
        if not open_meta.get("ok"):
            return {**open_meta, "action": action}
        if action == "follow":
            return await human_follow_user(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                sec_uid=lead.sec_uid,
                user_id=lead.user_id,
                username=lead.username,
                profile_page=profile_page,
            )
        if action == "dm" and config.dm_text:
            return await human_send_dm(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                sec_uid=lead.sec_uid,
                message=config.dm_text,
                username=lead.username,
                profile_page=profile_page,
            )
    return {"ok": False, "skipped": True, "action": action, "reason": "缺少触达文案或未实现"}


async def _browse_video_comments(
    ctx: DouyinUiSession,
    *,
    config: StandaloneKeywordBrowseConfig,
    video_index: int,
    video_url: str,
    seen_comment_ids: set[str],
    outreach_stats: dict[str, int],
    dedupe_stats: dict[str, int],
    db_session: Session | None = None,
    leads_before: int = 0,
) -> tuple[list[PreciseLeadRecord], int, str]:
    """步骤 5–7：单视频评论浏览、评估、保存线索。"""
    page = ctx.page
    leads: list[PreciseLeadRecord] = []
    comment_days = config.comment_days if config.comment_days is not None else config.days
    cutoff_ts = _days_cutoff_ts(comment_days)
    max_comments = max(1, int(config.max_comments_per_video))
    max_rounds = max(8, min(40, int(config.comment_scroll_rounds)))
    target = max(1, int(config.target_precise_leads))

    if not await _back_to_search_list(ctx):
        return leads, 0, "未能返回搜索列表，无法点下一个视频"

    if not await _ensure_search_item_index(ctx, video_index):
        return leads, 0, f"搜索列表第 {video_index + 1} 项不可用（滚动后仍不足）"

    clicked, click_note = await _click_search_result_item(ctx, video_index, skip_back=True)
    if not clicked:
        await _report_step(ctx, f"视频 {video_index + 1}：点击失败", sub=click_note, log=False)
        return leads, 0, f"未能点击第 {video_index + 1} 个视频；{click_note}"

    snap_after = await classify_douyin_page(page)
    ctx.phase_log.append(
        f"PAGE_AFTER_CLICK phase={snap_after.get('phase')} feed={snap_after.get('feed_visible')} "
        f"list={snap_after.get('list_visible')} url={str(page.url or '')[:96]}"
    )
    if snap_after.get("list_visible") and not snap_after.get("feed_visible"):
        return leads, 0, f"点击后仍在搜索列表，未进详情；{click_note}"

    if not await wait_feed_detail(page, max_sec=4.0):
        await _report_step(ctx, "详情页未就绪", sub=await _page_phase_note(page), log=False)
        return leads, 0, f"进详情后 Feed 未就绪；{await _page_phase_note(page)}"

    ctx.phase_log.append(f"ITEM_CLICK index={video_index} {click_note}")
    await _report_step(
        ctx,
        f"步骤 4/7：点击第 {video_index + 1} 个视频",
        sub=click_note[:48] if click_note else "进入详情…",
        log=False,
    )

    await _report_step(ctx, f"步骤 5/7：打开评论侧栏", sub=f"视频 {video_index + 1}", log=False)

    # 进详情后尽快点评论：短暂停留即点，避免干等 watch_seconds
    await asyncio.sleep(random.uniform(0.8, 1.6))

    if not await is_feed_detail_open(page):
        return leads, 0, f"打开评论前不在详情页；{await _page_phase_note(page)}"

    captured_pages: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    handler = _comment_response_handler(captured_pages, seen_signatures=seen_signatures)
    page.on("response", handler)

    ctx.phase_log.append("COMMENT_OPEN start")
    sidebar_ok = await activate_comment_sidebar_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    ctx.phase_log.append(f"COMMENT_OPEN ok={sidebar_ok} {await _page_phase_note(page)}")
    if sidebar_ok:
        await _report_step(
            ctx,
            "步骤 6/7：浏览评论",
            sub="拦截 comment/list · 评估线索",
            log=False,
        )
    else:
        await _report_step(ctx, "评论侧栏打开失败", sub="未点到评论入口", log=False)
    if not sidebar_ok:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
        await close_feed_detail_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        return leads, 0, "未能打开评论侧栏（未点到评论入口）"

    sort_latest_ok = await select_latest_comment_sort_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    min_time_rounds = 1 if sort_latest_ok else 2
    await asyncio.sleep(random.uniform(0.6, 1.2))

    aweme_id = ""
    try:
        aweme_id = _extract_aweme_id(video_url or page.url)
    except ValueError:
        aweme_id = str(ctx.state.get("search_aweme_ids", [""])[video_index] if video_index < len(ctx.state.get("search_aweme_ids") or []) else "")

    stop_reason = ""
    scanned = 0
    stale_scrolls = 0
    prev_filtered = 0

    try:
        for round_idx in range(max_rounds + 1):
            if round_idx > 0 and not await _comment_sidebar_active(page):
                stop_reason = "评论侧栏已关闭，停止滚动"
                break

            comments_map, _api_total = _merge_captured_pages(captured_pages)
            filtered = _filter_comments_by_days(
                comments_map,
                cutoff_ts=cutoff_ts,
                max_comments=max_comments,
            )
            scanned = len(comments_map)
            if round_idx > 0 and round_idx % 4 == 0:
                await _report_step(
                    ctx,
                    "步骤 6/7：滚动评论",
                    sub=f"第 {round_idx} 轮 · 已扫描 {scanned} 条",
                    log=False,
                )
            last_page = _last_list_page(captured_pages)

            candidate_rows = [
                row for row in filtered if not row.get("parent_comment_id")
            ]
            new_rows, dup_skipped = _take_unique_comments(candidate_rows, seen_comment_ids)
            dedupe_stats["duplicates_skipped"] = dedupe_stats.get("duplicates_skipped", 0) + dup_skipped
            if new_rows:
                eval_map = await _evaluate_comments_batch(new_rows, config, ctx.settings)
                for row in new_rows:
                    cid = _comment_id_from_row(row)
                    if not cid or cid not in eval_map:
                        continue

                    eval_row = eval_map[cid]
                    action = await _decide_outreach_action(config, outreach_stats)
                    lead = PreciseLeadRecord(
                        comment_id=cid,
                        comment_text=str(row.get("comment") or ""),
                        username=str(row.get("username") or ""),
                        user_id=str(row.get("user_id") or ""),
                        sec_uid=str(row.get("sec_uid") or ""),
                        video_url=video_url or page.url,
                        aweme_id=aweme_id,
                        create_time=int(row.get("create_time") or 0),
                        match_score=float(eval_row.get("score") or 0),
                        match_reason=str(eval_row.get("reason") or ""),
                        planned_action=action,
                        raw_comment=row,
                    )

                    outreach_result: dict[str, Any] = {}
                    if config.execute_outreach:
                        if config.test_all_outreach:
                            outreach_result = await _execute_all_outreach_for_lead(
                                page,
                                ctx.settings,
                                tenant_id=ctx.tenant_id,
                                account_id=ctx.account_id,
                                lead=lead,
                                config=config,
                            )
                            lead.outreach_executed = bool(outreach_result.get("ok"))
                            if outreach_result.get("reply", {}).get("ok"):
                                outreach_stats["replies"] = outreach_stats.get("replies", 0) + 1
                            if outreach_result.get("dm", {}).get("ok"):
                                outreach_stats["dms"] = outreach_stats.get("dms", 0) + 1
                            if outreach_result.get("follow", {}).get("ok"):
                                outreach_stats["follows"] = outreach_stats.get("follows", 0) + 1
                        else:
                            outreach_result = await _execute_outreach_if_needed(
                                page,
                                ctx.settings,
                                tenant_id=ctx.tenant_id,
                                account_id=ctx.account_id,
                                action=action,
                                lead=lead,
                                config=config,
                            )
                            lead.outreach_executed = bool(outreach_result.get("ok"))
                            if lead.outreach_executed:
                                if action == "reply":
                                    outreach_stats["replies"] = outreach_stats.get("replies", 0) + 1
                                elif action == "dm":
                                    outreach_stats["dms"] = outreach_stats.get("dms", 0) + 1
                                elif action == "follow":
                                    outreach_stats["follows"] = outreach_stats.get("follows", 0) + 1
                        lead.outreach_result = outreach_result

                    if config.persist_to_db and db_session is not None:
                        saved = _persist_precise_lead(
                            db_session,
                            ctx.settings,
                            tenant_id=ctx.tenant_id,
                            lead=lead,
                            config=config,
                        )
                        if saved:
                            ctx.phase_log.append(f"SAVED lead cid={cid[:8]} rows={saved}")

                    leads.append(lead)
                    ctx.phase_log.append(
                        f"LEAD video={video_index + 1} cid={cid[:8]} action={action} score={lead.match_score:.2f}"
                    )
                    await _report_step(
                        ctx,
                        f"精准线索 {leads_before + len(leads)}/{target}",
                        sub=f"@{lead.username} · {lead.comment_text[:24]}",
                        log=False,
                    )

                    if leads_before + len(leads) >= target:
                        stop_reason = f"已达目标精准线索 {target} 条"
                        break

                    policy = config.action_policy or {}
                    interval = random_interval_sec(
                        int(policy.get("interval_min_sec") or 10),
                        int(policy.get("interval_max_sec") or 30),
                    )
                    await asyncio.sleep(interval)

            if stop_reason:
                break

            if _should_stop_for_time_window(
                cutoff_ts=cutoff_ts,
                round_idx=round_idx,
                filtered_count=len(filtered),
                last_page=last_page,
                min_scroll_before_time_stop=min_time_rounds,
            ):
                stop_reason = f"评论已超过 {comment_days} 天，结束本视频"
                await _report_step(
                    ctx,
                    f"视频 {video_index + 1}：评论过旧",
                    sub=f"超过 {comment_days} 天窗口，切换下一个视频",
                    log=False,
                )
                ctx.phase_log.append(
                    f"TIME_STOP video={video_index + 1} days={comment_days} scanned={scanned}"
                )
                break

            top_count = len([r for r in filtered if not r.get("parent_comment_id")])
            if top_count >= max_comments:
                stop_reason = f"已浏览 {top_count} 条评论"
                break

            has_more = int(last_page.get("has_more") or 0)
            if not has_more and round_idx > 1 and captured_pages:
                stop_reason = "评论已全部加载"
                break

            if round_idx >= max_rounds:
                stop_reason = f"达到最大滚动轮次 {max_rounds}"
                break

            if len(filtered) == prev_filtered:
                stale_scrolls += 1
            else:
                stale_scrolls = 0
            prev_filtered = len(filtered)
            if stale_scrolls >= 2 and not captured_pages:
                stop_reason = "评论侧栏无数据（可能未点开评论）"
                break
            if stale_scrolls >= 3:
                stop_reason = "连续滚动无新评论"
                break

            await scroll_comment_sidebar_on_page(
                page,
                ctx.settings,
                tenant_id=ctx.tenant_id,
                rounds=1,
            )
            await asyncio.sleep(random.uniform(1.8, 3.5))
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass

    for _ in range(2):
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.15)
    await close_feed_detail_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    ctx.state["feed_mode"] = False
    await human_delay(page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")

    if not stop_reason and _newest_top_create_time_in_page(_last_list_page(captured_pages)) is None:
        stop_reason = "未拦截到评论数据"
    return leads, scanned, stop_reason or "单视频评论浏览结束"


def _serialize_leads(leads: list[PreciseLeadRecord]) -> list[dict[str, Any]]:
    return [
        {
            "comment_id": lead.comment_id,
            "comment": lead.comment_text,
            "username": lead.username,
            "user_id": lead.user_id,
            "sec_uid": lead.sec_uid,
            "video_url": lead.video_url,
            "aweme_id": lead.aweme_id,
            "create_time": lead.create_time,
            "match_score": lead.match_score,
            "match_reason": lead.match_reason,
            "planned_action": lead.planned_action,
            "outreach_executed": lead.outreach_executed,
            "outreach_result": lead.outreach_result,
            "status": "precise",
            "capture_method": CAPTURE_METHOD,
        }
        for lead in leads
    ]


async def _persist_session_storage(
    store: DouyinSessionStore,
    *,
    tenant_id: str,
    account_id: str,
    context: Any | None,
) -> None:
    if context is None:
        return
    try:
        await store.save_from_context(tenant_id, context, account_id)
    except Exception:
        pass


async def run_standalone_keyword_browse(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str = "default",
    config: StandaloneKeywordBrowseConfig,
    db_session: Session | None = None,
    headless: bool = False,
    stable_session: Any | None = None,
) -> StandaloneKeywordBrowseResult:
    """独立抖音关键词浏览主入口（固定 UI 流程，全程模拟人类操作）。"""
    store = DouyinSessionStore(settings)
    ctx = _build_ui_session(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
    )
    result = StandaloneKeywordBrowseResult(ok=False, keyword=config.keyword)
    seen_comment_ids: set[str] = set()
    outreach_stats: dict[str, int] = {"replies": 0, "dms": 0, "follows": 0}
    dedupe_stats: dict[str, int] = {"duplicates_skipped": 0}
    all_leads: list[PreciseLeadRecord] = []

    try:
        await _report_step(
            ctx,
            "准备开始",
            sub=f"关键词「{config.keyword}」· {config.content_limit} 个视频",
            log=False,
        )
        ctx.phase_log.append("STEP1 open_home")
        await _open_douyin_home(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            store=store,
            headless=headless,
            stable_session=stable_session,
        )

        ctx.phase_log.append("STEP2 search")
        search_ok, search_diag = await _run_search_phase(ctx, config=config)
        if not search_ok:
            result.error = "E_SEARCH"
            result.diagnostic = search_diag
            result.phase_log = list(ctx.phase_log)
            await _report_step(ctx, "搜索失败", sub=search_diag or "", log=False)
            return result

        result.search_url = str(ctx.state.get("search_url") or page.url)
        ctx.phase_log.append(f"STEP3 search_ok url={result.search_url}")

        list_prepared = await _prepare_search_list_for_browse(ctx)
        poster_n = await _count_search_posters(page)
        aweme_n = len(ctx.state.get("search_aweme_ids") or [])
        ctx.phase_log.append(
            f"STEP3b list_prepared={list_prepared} posters={poster_n} aweme_ids={aweme_n}"
        )
        if not list_prepared:
            result.error = "E_NO_LIST"
            result.diagnostic = (
                f"搜索完成但列表不可点（海报={poster_n}，api_aweme={aweme_n}）；"
                f"url={page.url}"
            )
            result.phase_log = list(ctx.phase_log)
            await _report_step(ctx, "列表未就绪", sub=result.diagnostic, log=False)
            return result

        target = max(1, int(config.target_precise_leads))
        max_videos = max(target, int(config.max_videos_to_browse))
        aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
        video_index = 0
        stop_browse_reason = ""

        while len(all_leads) < target and video_index < max_videos:
            ctx.phase_log.append(f"STEP4 video_index={video_index}")
            await _report_step(
                ctx,
                f"步骤 4/7：浏览视频 {video_index + 1}",
                sub=f"精准线索 {len(all_leads)}/{target} · 继续直到凑够",
                log=False,
            )
            if video_index < len(ctx.video_urls):
                video_url = ctx.video_urls[video_index]
            elif video_index < len(aweme_ids) and aweme_ids[video_index]:
                video_url = f"https://www.douyin.com/video/{aweme_ids[video_index]}"
            else:
                video_url = ""

            video_leads, scanned, stop_note = await _browse_video_comments(
                ctx,
                config=config,
                video_index=video_index,
                video_url=video_url,
                seen_comment_ids=seen_comment_ids,
                outreach_stats=outreach_stats,
                dedupe_stats=dedupe_stats,
                db_session=db_session,
                leads_before=len(all_leads),
            )
            all_leads.extend(video_leads)
            result.comments_scanned += scanned
            result.videos_processed += 1
            ctx.phase_log.append(
                f"STEP7 video={video_index + 1} leads={len(video_leads)} "
                f"total={len(all_leads)}/{target} scanned={scanned} note={stop_note}"
            )
            await human_delay(page, settings, tenant_id=tenant_id, profile="fast")

            if len(all_leads) >= target:
                stop_browse_reason = f"已达目标 {target} 条精准线索"
                break
            if stop_note.startswith("已达目标精准线索"):
                break

            video_index += 1

        result.target_reached = len(all_leads) >= target
        result.precise_leads = all_leads
        result.duplicates_skipped = int(dedupe_stats.get("duplicates_skipped") or 0)
        result.ok = result.target_reached
        result.phase_log = list(ctx.phase_log)
        if result.target_reached:
            result.diagnostic = (
                f"已找到 {len(all_leads)} 条精准线索（目标 {target}），"
                f"浏览 {result.videos_processed} 个视频，去重跳过 {result.duplicates_skipped} 条"
            )
            if stop_browse_reason:
                result.diagnostic += f"；{stop_browse_reason}"
        else:
            result.error = result.error or "E_TARGET_NOT_MET"
            result.diagnostic = (
                f"未凑够目标：精准线索 {len(all_leads)}/{target}，"
                f"已浏览 {result.videos_processed} 个视频（上限 {max_videos}）"
            )
        await _report_step(
            ctx,
            "步骤 7/7：完成" if result.target_reached else "未达目标",
            sub=result.diagnostic or "",
            log=False,
        )

        payload = {
            "platform": PLATFORM,
            "keyword": config.keyword,
            "search_url": result.search_url,
            "capture_method": CAPTURE_METHOD,
            "videos_processed": result.videos_processed,
            "comments_scanned": result.comments_scanned,
            "duplicates_skipped": result.duplicates_skipped,
            "unique_comments_seen": len(seen_comment_ids),
            "precise_lead_count": len(all_leads),
            "precise_leads": _serialize_leads(all_leads),
            "phase_log": result.phase_log,
            "outreach_stats": outreach_stats,
            "target_precise_leads": target,
            "target_reached": result.target_reached,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        output = (
            settings.report_output_dir
            / f"standalone_douyin_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        result.output_file = str(output)

    except HumanBrowseGuardError as exc:
        result.error = "E_GUARD"
        result.diagnostic = str(exc)
        result.phase_log = list(ctx.phase_log)
        await _report_step(ctx, "已停止", sub=str(exc), log=False)
    except Exception as exc:
        result.error = "E_RUNTIME"
        result.diagnostic = str(exc)
        result.phase_log = list(ctx.phase_log)
        await _report_step(ctx, "运行出错", sub=str(exc)[:120], log=False)

    return result


async def run_standalone_keyword_browse_with_browser(
    settings: Settings,
    *,
    tenant_id: str = "default",
    account_id: str = "default",
    config: StandaloneKeywordBrowseConfig,
    db_session: Session | None = None,
    headless: bool = False,
) -> StandaloneKeywordBrowseResult:
    """自带浏览器会话的便捷入口（调试 / 脚本调用）。

    默认复用 AgentSessionManager 稳定基座（与桌面 App / Supervisor 相同），
    优先使用已打开的 Chrome 标签，避免每次新建空上下文再灌 Cookie。
    """
    from app.core.antibot import headless_for_platform
    from app.services.agent_browser_session import AgentSessionManager
    from app.services.playwright_pool import PlaywrightPool

    store = DouyinSessionStore(settings)
    resolved_headless = headless_for_platform(settings, PLATFORM, headless)

    if config.reuse_stable_session:
        session = await AgentSessionManager.get_instance().create_stable(
            tenant_id,
            PLATFORM,
            settings,
            account_id=account_id,
            headless=resolved_headless,
        )
        page = session.page
        try:
            result = await run_standalone_keyword_browse(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                config=config,
                db_session=db_session,
                headless=resolved_headless,
                stable_session=session,
            )
        finally:
            await _persist_session_storage(
                store,
                tenant_id=tenant_id,
                account_id=account_id,
                context=session._context,
            )
            if config.close_browser_after:
                await AgentSessionManager.get_instance().close(session.session_id)
        return result

    pool = PlaywrightPool.get()
    async with pool.tenant_context(
        PLATFORM,
        tenant_id,
        store,
        settings,
        headless=resolved_headless,
        account_id=account_id,
    ) as (_context, page):
        return await run_standalone_keyword_browse(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            config=config,
            db_session=db_session,
            headless=resolved_headless,
        )
