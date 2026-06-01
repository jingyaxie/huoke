from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    human_delay,
    human_pause,
    human_scroll,
    launch_args,
    require_login,
)
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import (
    COMMENT_PAGE_PATH,
    COMMENT_SUB_PATH,
    PLATFORM,
)
from app.platforms.xiaohongshu.crawler import XhsCrawler
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.utils import extract_note_id, normalize_xhs_comment


class XhsCommentCrawler:
    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.store = store or XhsSessionStore(settings)
        self.hot_crawler = XhsCrawler(settings, tenant_id, self.store, account_id=account_id)

    async def crawl_note_comments(self, note_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        note_id = extract_note_id(note_url)
        payload = await self._fetch_note_comments(note_url=note_url, headless=not show_browser)
        output = (
            self.settings.report_output_dir
            / f"comments_{PLATFORM}_{self.tenant_id}_{note_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if show_browser and not XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await self.hot_crawler.start_interactive_login_session()
        if show_browser:
            session = XhsCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
            if session:
                note_urls, diagnostic = await self._search_from_existing_page(session["page"], keyword, limit)
            else:
                note_urls, diagnostic = await self.hot_crawler.search_note_urls(keyword, limit, headless=False)
        else:
            note_urls, diagnostic = await self.hot_crawler.search_note_urls(keyword, limit, headless=True)

        results: list[dict] = []
        files: list[Path] = []
        for url in note_urls:
            payload, output = await self.crawl_note_comments(url, show_browser=False)
            payload["keyword_context"] = {"keyword": keyword, "days": days, "region": region}
            payload["video_url"] = payload.get("note_url") or url
            results.append(payload)
            files.append(output)
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")
        return results, files, diagnostic

    async def _search_from_existing_page(self, page, keyword: str, limit: int) -> tuple[list[str], str | None]:
        from urllib.parse import quote

        note_urls: list[str] = []
        captured_ids: list[str] = []

        async def on_response(resp):
            try:
                if "/search/notes" not in resp.url:
                    return
                data = await resp.json()
                from app.platforms.xiaohongshu.utils import walk_note_ids

                for note_id in walk_note_ids(data):
                    if note_id not in captured_ids:
                        captured_ids.append(note_id)
            except Exception:
                return

        page.on("response", on_response)
        try:
            await page.goto(
                f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes",
                wait_until="domcontentloaded",
                timeout=120000,
            )
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]').evaluate_all(
                "els => els.map(e => e.href)"
            )
            for href in links:
                match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", href or "")
                if match and href not in note_urls:
                    note_urls.append(href.split("?")[0] if "?" not in href else href)
                if len(note_urls) >= limit:
                    break
            if not note_urls and captured_ids:
                from app.platforms.xiaohongshu.utils import build_note_url

                note_urls = [build_note_url(note_id) for note_id in captured_ids[:limit]]
            diagnostic = "已在可见浏览器中完成小红书关键词搜索。" if note_urls else "可见浏览器未提取到笔记链接。"
            return note_urls[:limit], diagnostic
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _fetch_note_comments(self, note_url: str, headless: bool = True) -> dict:
        note_id = extract_note_id(note_url)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=launch_args())
            kwargs = context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))
            context = await browser.new_context(**kwargs)
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()
            captured_pages: list[dict] = []

            async def on_response(resp):
                try:
                    url = resp.url
                    if COMMENT_PAGE_PATH not in url and COMMENT_SUB_PATH not in url:
                        return
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    if isinstance(data, dict):
                        captured_pages.append({"url": url, "data": data})
                except Exception:
                    return

            page.on("response", on_response)
            await page.goto(note_url, wait_until="domcontentloaded", timeout=120000)
            for _ in range(5):
                if captured_pages:
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                for selector in ('[class*="comment"]', 'span:has-text("评论")', 'div:has-text("条评论")'):
                    loc = page.locator(selector).first
                    try:
                        if await loc.count() > 0:
                            await loc.click(force=True, timeout=800)
                            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                    except Exception:
                        continue

            comments_map: dict[str, dict] = {}
            api_total = 0
            for packet in captured_pages:
                body = packet.get("data") or {}
                data = body.get("data") if isinstance(body.get("data"), dict) else body
                comments = data.get("comments") or []
                if not api_total:
                    api_total = int(data.get("comment_count") or data.get("total") or len(comments) or 0)
                for item in comments:
                    row = normalize_xhs_comment(item)
                    if row["comment_id"]:
                        comments_map[row["comment_id"]] = row
                    for sub in item.get("sub_comments") or []:
                        sub_row = normalize_xhs_comment(sub, parent_comment_id=row["comment_id"])
                        if sub_row["comment_id"]:
                            comments_map[sub_row["comment_id"]] = sub_row

            if not comments_map:
                dom_rows = await self._extract_comments_from_dom(page)
                await context.close()
                await browser.close()
                return {
                    "platform": PLATFORM,
                    "note_id": note_id,
                    "note_url": note_url,
                    "video_url": note_url,
                    "api_total_top_comments": 0,
                    "top_comments_captured": len(dom_rows),
                    "reply_comments_captured_preview": 0,
                    "expected_reply_total_from_top_comments": 0,
                    "total_comments_captured": len(dom_rows),
                    "capture_method": "dom_fallback",
                    "warning": "未捕获到小红书评论接口，结果来自页面可见评论（可能不全）。建议先登录小红书。",
                    "comments": dom_rows,
                }

            await context.close()
            await browser.close()

        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = [row for row in comments if not row.get("parent_comment_id")]
        preview_reply_rows = [row for row in comments if row.get("parent_comment_id")]
        expected_reply_total = sum(int(row.get("reply_comment_total") or 0) for row in top_rows)
        return {
            "platform": PLATFORM,
            "note_id": note_id,
            "note_url": note_url,
            "video_url": note_url,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(top_rows),
            "reply_comments_captured_preview": len(preview_reply_rows),
            "expected_reply_total_from_top_comments": expected_reply_total,
            "total_comments_captured": len(comments),
            "capture_method": "network_api",
            "comments": comments,
        }

    async def _extract_comments_from_dom(self, page) -> list[dict]:
        rows = await page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const nodes = document.querySelectorAll('[class*="comment"], [class*="Comment"], .note-comment-item, li');
                for (const el of nodes) {
                    const textEl = el.querySelector('[class*="content"], [class*="text"], p, span');
                    const userEl = el.querySelector('[class*="name"], [class*="nickname"], a');
                    const comment = textEl ? (textEl.textContent || '').trim() : (el.textContent || '').trim();
                    const username = userEl ? (userEl.textContent || '').trim() : '';
                    if (!comment || comment.length < 2 || !username) continue;
                    const key = username + '::' + comment;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({
                        comment_id: '',
                        parent_comment_id: null,
                        comment,
                        create_time: null,
                        digg_count: 0,
                        reply_comment_total: 0,
                        username,
                        user_id: '',
                        sec_uid: '',
                        avatar: '',
                    });
                    if (out.length >= 200) break;
                }
                return out;
            }"""
        )
        return rows if isinstance(rows, list) else []
