from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from app.core.antibot import headless_for_platform, human_delay, human_scroll, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import (
    PLATFORM,
    SEARCH_NOTES_PATH,
    _build_search_url,
    _is_search_result_api,
)
from app.platforms.xiaohongshu.utils import build_note_url, parse_note_card, walk_note_ids
from app.services.playwright_pool import PlaywrightPool


class XhsSearchTool(XhsJsApiTool):
    """小红书关键词搜索工具（薄浏览器 + API 拦截）。"""

    def entry_url(self) -> str:
        return self.settings.xhs_explore_url or self.settings.xhs_home_url

    async def search_notes_from_existing_page(self, page, keyword: str, limit: int) -> tuple[list[str], str | None]:
        note_meta: dict[str, dict] = {}

        async def on_response(resp):
            try:
                if not _is_search_result_api(resp.url) or resp.status != 200:
                    return
                data = await resp.json()
            except Exception:
                return
            self._ingest_search_payload(data, note_meta, limit * 3)

        page.on("response", on_response)
        try:
            await page.goto(_build_search_url(keyword), wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            for _ in range(10):
                if len(note_meta) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
            if not note_meta:
                await self._collect_note_links_from_dom(page, note_meta, limit)
            urls = self._meta_to_urls(note_meta, limit)
            diagnostic = "已在可见浏览器中完成小红书关键词搜索。" if urls else "可见浏览器未提取到笔记链接。"
            return urls, diagnostic
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _thin_browser_keyword_search(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        captured_api_urls: list[str],
    ) -> tuple[list[str], str | None]:
        await self.warmup_for_js_api(page, captured_api_urls)
        note_meta: dict[str, dict] = {}
        target_count = max(limit * 2, 10)
        processed: set[int] = set()
        pending: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not _is_search_result_api(resp.url):
                return
            pending.append(
                asyncio.create_task(
                    self._ingest_search_response(resp, note_meta, captured_api_urls, target_count, processed)
                )
            )

        page.on("response", on_response)
        try:
            await page.goto(_build_search_url(keyword), wait_until="domcontentloaded", timeout=120000)
            await self._drain_tasks(pending)
            for _ in range(10):
                if len(note_meta) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                await self._drain_tasks(pending)
                await page.wait_for_timeout(500)
            if not note_meta:
                await self._collect_note_links_from_dom(page, note_meta, limit)
        finally:
            await self._drain_tasks(pending)
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        urls = self._meta_to_urls(note_meta, limit)
        if urls:
            return urls, f"关键词「{keyword}」搜索成功（thin_nav_api，{len(urls)} 条笔记）"
        return [], "薄浏览器搜索未返回笔记，请确认 Cookie 有效或在 VNC 手动搜索后设 show_browser=true。"

    @staticmethod
    async def _drain_tasks(tasks: list[asyncio.Task]) -> None:
        if not tasks:
            return
        batch = list(tasks)
        tasks.clear()
        await asyncio.gather(*batch, return_exceptions=True)

    async def _ingest_search_response(
        self,
        resp,
        note_meta: dict[str, dict],
        captured_api_urls: list[str],
        target_count: int,
        processed: set[int],
    ) -> None:
        if id(resp) in processed:
            return
        url = resp.url
        if url not in captured_api_urls:
            captured_api_urls.append(url)
        try:
            data = await resp.json()
        except Exception:
            try:
                raw = await resp.body()
                data = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
            except Exception:
                return
        if not isinstance(data, dict):
            return
        processed.add(id(resp))
        self._ingest_search_payload(data, note_meta, target_count)

    def _ingest_search_payload(self, data: dict, note_meta: dict[str, dict], target_count: int) -> None:
        for note_id in walk_note_ids(data):
            if note_id not in note_meta:
                note_meta[note_id] = {"note_id": note_id}
            if len(note_meta) >= target_count:
                return
        items = (data.get("data") or {}).get("items") or data.get("items") or []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            parsed = parse_note_card(raw, rank=0, tenant_id=self.tenant_id)
            if not parsed:
                continue
            note_id = parsed["external_id"]
            note_meta[note_id] = parsed.get("raw_data") or {"note_id": note_id}
            if len(note_meta) >= target_count:
                return

    async def _collect_note_links_from_dom(self, page, note_meta: dict[str, dict], limit: int) -> None:
        links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]').evaluate_all(
            "els => els.map(e => e.href)"
        )
        for href in links:
            match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", href or "")
            if match:
                note_meta.setdefault(match.group(1), {"note_id": match.group(1)})
            if len(note_meta) >= limit:
                break

    def _meta_to_urls(self, note_meta: dict[str, dict], limit: int) -> list[str]:
        urls: list[str] = []
        for note_id, meta in list(note_meta.items())[: limit * 2]:
            urls.append(
                build_note_url(
                    note_id,
                    meta.get("xsec_token"),
                    meta.get("xsec_source") or "pc_search",
                )
            )
            if len(urls) >= limit:
                break
        return urls[:limit]

    async def search_notes_by_keyword(
        self,
        keyword: str,
        limit: int,
        headless: bool | None = None,
        manual_search: bool = False,
    ) -> tuple[list[str], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        captured_api_urls: list[str] = []
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            if manual_search:
                return await self.search_notes_from_existing_page(page, keyword, limit)
            return await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
            )

    def _search_output_path(self, keyword: str) -> Path:
        safe_keyword = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", keyword)[:32]
        path = (
            self.settings.report_output_dir
            / f"search_notes_{PLATFORM}_{self.tenant_id}_{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def search_notes(
        self,
        keyword: str,
        limit: int = 10,
        show_browser: bool = False,
    ) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        headless = headless_for_platform(self.settings, PLATFORM, not show_browser)
        captured_api_urls: list[str] = []
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
            account_id=self.account_id,
        ) as (_, page):
            note_urls, diagnostic = await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
            )

        notes: list[dict] = []
        seen: set[str] = set()
        for url in note_urls:
            match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", url)
            if not match:
                continue
            note_id = match.group(1)
            if note_id in seen:
                continue
            seen.add(note_id)
            notes.append({"note_id": note_id, "note_url": url.split("?")[0] if "?" not in url else url})

        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "note_count": len(notes),
            "capture_method": "thin_nav_api" if notes else "empty",
            "diagnostic": diagnostic,
            "notes": notes[:limit],
        }
        output = self._search_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
