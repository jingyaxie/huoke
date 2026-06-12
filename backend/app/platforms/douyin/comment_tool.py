from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.js_constants import (
    DEFAULT_MAX_COMMENTS,
    PLATFORM,
    _build_comment_list_url,
    _build_next_url,
    _extract_aweme_id,
    _normalize_comment,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class DouyinCommentTool(DouyinJsApiTool):
    """抖音视频评论抓取工具。"""

    async def crawl_note_comments(
        self,
        content_url: str,
        show_browser: bool = False,
        *,
        page=None,
        template_url: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        aweme_id = _extract_aweme_id(content_url)
        payload = await self._fetch_video_comments(
            video_url=content_url,
            headless=not show_browser,
            page=page,
            template_url=template_url,
            max_comments=max_comments,
        )
        payload["platform"] = PLATFORM
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output


    async def crawl_video_comments(self, video_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        return await self.crawl_note_comments(video_url, show_browser=show_browser)


    async def _fetch_comments_from_api(
        self,
        page,
        aweme_id: str,
        video_url: str,
        template_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        comments_map: dict[str, dict] = {}
        api_url = _build_comment_list_url(template_url, aweme_id, cursor=0, count=20)
        api_total = 0
        cursor = 0
        has_more = 1
        guard = 0
        top_count = 0

        def merge_page(data: dict) -> None:
            nonlocal top_count
            for c in data.get("comments") or []:
                row = _normalize_comment(c)
                if row["comment_id"]:
                    if row["comment_id"] not in comments_map and not row.get("parent_comment_id"):
                        top_count += 1
                    comments_map[row["comment_id"]] = row
                    for reply in c.get("reply_comment") or []:
                        reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                        if reply_row["comment_id"]:
                            comments_map[reply_row["comment_id"]] = reply_row

        while has_more and guard < 30 and top_count < max_comments:
            guard += 1
            page_url = _build_next_url(api_url, cursor) if guard > 1 else api_url
            data = await self.fetch_json_via_page(page, page_url)
            if not data.get("comments") and guard == 1 and template_url != api_url:
                api_url = _build_comment_list_url(template_url, aweme_id, cursor=0, count=20)
                data = await self.fetch_json_via_page(page, api_url)
            if guard == 1:
                api_total = int(data.get("total") or 0)
            merge_page(data)
            cursor = int(data.get("cursor") or cursor)
            has_more = int(data.get("has_more") or 0)
            if not data.get("comments"):
                break

        return self._build_comment_payload(
            aweme_id=aweme_id,
            video_url=video_url,
            comments_map=comments_map,
            api_total=api_total,
            max_comments=max_comments,
            capture_method="js_api" if comments_map else "api_empty",
        )

    def _build_comment_payload(
        self,
        *,
        aweme_id: str,
        video_url: str,
        comments_map: dict[str, dict],
        api_total: int,
        max_comments: int,
        capture_method: str,
    ) -> dict:
        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
        kept_ids = {row["comment_id"] for row in top_rows}
        kept_ids.update(
            row["comment_id"]
            for row in comments
            if row.get("parent_comment_id") in kept_ids and row.get("comment_id")
        )
        comments = [row for row in comments if row.get("comment_id") in kept_ids]
        preview_reply_rows = [row for row in comments if row.get("parent_comment_id")]
        expected_reply_total = sum(int(row.get("reply_comment_total") or 0) for row in top_rows)
        warning = None
        if not top_rows:
            warning = "评论接口未返回数据，请确认已登录且 Cookie 有效。"
        elif api_total > max_comments:
            warning = f"已限制抓取前 {max_comments} 条顶层评论（接口总数 {api_total}）。"
        return {
            "platform": PLATFORM,
            "aweme_id": aweme_id,
            "video_url": video_url,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(top_rows),
            "reply_comments_captured_preview": len(preview_reply_rows),
            "expected_reply_total_from_top_comments": expected_reply_total,
            "total_comments_captured": len(comments),
            "capture_method": capture_method,
            "warning": warning,
            "comments": comments,
        }

    async def _fetch_comments_via_page_network(
        self,
        page,
        aweme_id: str,
        video_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict | None:
        captured_pages: list[dict] = []

        async def on_response(resp) -> None:
            if "comment/list" not in resp.url or resp.status >= 400:
                return
            try:
                data = await resp.json()
            except Exception:
                return
            if isinstance(data, dict):
                captured_pages.append(data)

        page.on("response", on_response)
        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 700)")
                await page.wait_for_timeout(1200)
            await page.wait_for_timeout(1500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        if not captured_pages:
            return None

        comments_map: dict[str, dict] = {}
        api_total = 0
        for index, data in enumerate(captured_pages):
            if index == 0:
                api_total = int(data.get("total") or 0)
            for c in data.get("comments") or []:
                row = _normalize_comment(c)
                if row["comment_id"]:
                    comments_map[row["comment_id"]] = row
                    for reply in c.get("reply_comment") or []:
                        reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                        if reply_row["comment_id"]:
                            comments_map[reply_row["comment_id"]] = reply_row

        if not comments_map:
            return None

        return self._build_comment_payload(
            aweme_id=aweme_id,
            video_url=video_url,
            comments_map=comments_map,
            api_total=api_total,
            max_comments=max_comments,
            capture_method="page_network",
        )

    async def _fetch_comments_via_dom(
        self,
        page,
        aweme_id: str,
        video_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict | None:
        if video_url not in (page.url or ""):
            await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 700)")
                await page.wait_for_timeout(1000)
        rows = await self._extract_comments_from_dom(page)
        if not rows:
            return None
        comments_map: dict[str, dict] = {}
        for index, row in enumerate(rows[:max_comments], start=1):
            normalized = dict(row)
            normalized["comment_id"] = normalized.get("comment_id") or f"dom_{index}"
            comments_map[normalized["comment_id"]] = normalized
        return self._build_comment_payload(
            aweme_id=aweme_id,
            video_url=video_url,
            comments_map=comments_map,
            api_total=len(rows),
            max_comments=max_comments,
            capture_method="dom_fallback",
        )


    async def _fetch_video_comments(
        self,
        video_url: str,
        headless: bool = True,
        *,
        page=None,
        template_url: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        aweme_id = _extract_aweme_id(video_url)
        if page is not None:
            resolved_template = template_url or await self.pick_api_template_url(page)
            return await self._fetch_comments_from_api(
                page,
                aweme_id,
                video_url,
                resolved_template,
                max_comments=max_comments,
            )

        pool = PlaywrightPool.get()
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        captured_api_urls: list[str] = []

        async def on_response(resp):
            if "/aweme/v1/web/" in resp.url:
                captured_api_urls.append(resp.url)

        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, session_page):
            session_page.on("response", on_response)
            try:
                network_payload = await self._fetch_comments_via_page_network(
                    session_page,
                    aweme_id,
                    video_url,
                    max_comments=max_comments,
                )
                if network_payload and network_payload.get("total_comments_captured", 0) > 0:
                    return network_payload

                await self.warmup_for_js_api(session_page, captured_api_urls)
                resolved_template = template_url or await self.pick_api_template_url(session_page, captured_api_urls)
                api_payload = await self._fetch_comments_from_api(
                    session_page,
                    aweme_id,
                    video_url,
                    resolved_template,
                    max_comments=max_comments,
                )
                if api_payload.get("total_comments_captured", 0) > 0:
                    return api_payload

                dom_payload = await self._fetch_comments_via_dom(
                    session_page,
                    aweme_id,
                    video_url,
                    max_comments=max_comments,
                )
                return dom_payload or api_payload
            finally:
                try:
                    session_page.remove_listener("response", on_response)
                except Exception:
                    pass


    async def _extract_comments_from_dom(self, page) -> list[dict]:
        rows = await page.evaluate(
            """() => {
                const pickText = (el, sels) => {
                    for (const s of sels) {
                        const n = el.querySelector(s);
                        if (n && n.textContent && n.textContent.trim()) return n.textContent.trim();
                    }
                    return "";
                };
                const pickHrefUid = (el) => {
                    const a = el.querySelector('a[href*="user/"], a[href*="sec_uid="]');
                    if (!a || !a.getAttribute('href')) return "";
                    const href = a.getAttribute('href');
                    const m = href.match(/user\\/([^/?]+)/) || href.match(/sec_uid=([^&]+)/);
                    return m ? m[1] : "";
                };
                const pickAvatar = (el) => {
                    const img = el.querySelector('img');
                    return img && img.src ? img.src : "";
                };

                const candidates = Array.from(
                    document.querySelectorAll('[data-e2e*="comment"], [class*="comment"], li, article, div')
                );
                const out = [];
                const seen = new Set();
                for (const el of candidates) {
                    const comment = pickText(el, [
                        '[data-e2e*="content"]',
                        '[class*="content"]',
                        'p',
                        'span',
                    ]);
                    const username = pickText(el, [
                        '[data-e2e*="user"]',
                        '[class*="name"]',
                        'a',
                    ]);
                    if (!comment || comment.length < 2 || !username) continue;
                    const key = `${username}__${comment}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({
                        comment_id: "",
                        parent_comment_id: null,
                        comment,
                        create_time: null,
                        digg_count: 0,
                        reply_comment_total: 0,
                        username,
                        user_id: pickHrefUid(el),
                        sec_uid: "",
                        avatar: pickAvatar(el),
                    });
                    if (out.length >= 200) break;
                }
                return out;
            }"""
        )
        return rows if isinstance(rows, list) else []