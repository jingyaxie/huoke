from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_delay, human_scroll, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import (
    _FIRE_FETCH_JS,
    _build_search_feed_body,
    _is_search_result_api,
)
from app.platforms.kuaishou.utils import build_search_url, build_video_url, parse_search_feed_item
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouSearchTool(KuaishouJsApiTool):
    """快手关键词搜索工具（薄浏览器 + API 拦截）。"""

    def entry_url(self) -> str:
        return self.settings.kuaishou_home_url

    async def search_videos_from_existing_page(self, page, keyword: str, limit: int) -> tuple[list[str], str | None]:
        api_items: dict[str, dict] = {}

        async def on_response(resp):
            try:
                if not _is_search_result_api(resp.url) or resp.status != 200:
                    return
                data = await resp.json()
            except Exception:
                return
            self._ingest_search_payload(data, api_items, limit * 3)

        page.on("response", on_response)
        try:
            await page.goto(build_search_url(keyword), wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            for _ in range(8):
                if len(api_items) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
            if not api_items:
                await self._collect_video_links_from_dom(page, api_items, limit)
            urls = self._items_to_urls(api_items, limit)
            diagnostic = "已在可见浏览器中完成快手关键词搜索。" if urls else "可见浏览器未提取到视频链接。"
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
        api_items: dict[str, dict] = {}
        target_count = max(limit * 2, 10)
        processed: set[int] = set()
        pending: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not _is_search_result_api(resp.url):
                return
            pending.append(
                asyncio.create_task(
                    self._ingest_search_response(resp, api_items, captured_api_urls, target_count, processed)
                )
            )

        page.on("response", on_response)
        try:
            await page.goto(build_search_url(keyword), wait_until="domcontentloaded", timeout=120000)
            await self._drain_tasks(pending)
            if len(api_items) < limit:
                template_url = await self.pick_api_template_url(page, captured_api_urls)
                await self._fire_search_feed_request(
                    page, keyword, template_url, api_items, captured_api_urls, pending, processed, target_count
                )
                await self._drain_tasks(pending)
            for _ in range(6):
                if len(api_items) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                await self._drain_tasks(pending)
                await page.wait_for_timeout(500)
            if not api_items:
                await self._collect_video_links_from_dom(page, api_items, limit)
        finally:
            await self._drain_tasks(pending)
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        urls = self._items_to_urls(api_items, limit)
        if urls:
            return urls, f"关键词「{keyword}」搜索成功（thin_nav_api，{len(urls)} 条视频）"
        return [], "薄浏览器搜索未返回视频，请确认 Cookie 有效或在 VNC 手动搜索后设 show_browser=true。"

    @staticmethod
    async def _drain_tasks(tasks: list[asyncio.Task]) -> None:
        if not tasks:
            return
        batch = list(tasks)
        tasks.clear()
        await asyncio.gather(*batch, return_exceptions=True)

    async def _fire_search_feed_request(
        self,
        page,
        keyword: str,
        template_url: str,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        pending: list[asyncio.Task],
        processed: set[int],
        target_count: int,
    ) -> None:
        body = _build_search_feed_body(keyword)
        try:
            async with page.expect_response(lambda resp: _is_search_result_api(resp.url), timeout=15000) as resp_info:
                await page.evaluate(_FIRE_FETCH_JS, {"url": template_url, "body": body, "timeoutMs": 15000})
            await self._ingest_search_response(
                await resp_info.value, api_items, captured_api_urls, target_count, processed
            )
        except Exception:
            await page.evaluate(_FIRE_FETCH_JS, {"url": template_url, "body": body, "timeoutMs": 15000})

    async def _ingest_search_response(
        self,
        resp,
        api_items: dict[str, dict],
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
        self._ingest_search_payload(data, api_items, target_count)

    def _ingest_search_payload(self, data: dict, api_items: dict[str, dict], target_count: int) -> None:
        if int(data.get("result") or 0) not in (0, 1):
            return
        for feed in data.get("feeds") or []:
            row = parse_search_feed_item(feed, tenant_id=self.tenant_id)
            if not row:
                continue
            api_items.setdefault(row["photo_id"], row)
            if len(api_items) >= target_count:
                return

    async def _collect_video_links_from_dom(self, page, api_items: dict[str, dict], limit: int) -> None:
        links = await page.locator('a[href*="/short-video/"]').evaluate_all("els => els.map(e => e.href)")
        for href in links:
            match = re.search(r"/short-video/([0-9a-zA-Z]+)", href or "")
            if match:
                photo_id = match.group(1)
                api_items.setdefault(
                    photo_id,
                    {
                        "photo_id": photo_id,
                        "video_url": build_video_url(photo_id),
                        "title": "",
                        "author": "",
                        "author_id": "",
                    },
                )
            if len(api_items) >= limit:
                break

    def _items_to_urls(self, api_items: dict[str, dict], limit: int) -> list[str]:
        urls: list[str] = []
        for row in list(api_items.values())[: limit * 2]:
            url = row.get("video_url") or build_video_url(row.get("photo_id") or "")
            if url:
                urls.append(url.split("?")[0])
            if len(urls) >= limit:
                break
        return urls[:limit]

    async def search_videos_by_keyword(
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
                return await self.search_videos_from_existing_page(page, keyword, limit)
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
            / f"search_videos_{PLATFORM}_{self.tenant_id}_{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def search_videos(
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
            video_urls, diagnostic = await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
            )

        videos: list[dict] = []
        seen: set[str] = set()
        for url in video_urls:
            match = re.search(r"/short-video/([0-9a-zA-Z]+)", url)
            if not match:
                continue
            photo_id = match.group(1)
            if photo_id in seen:
                continue
            seen.add(photo_id)
            videos.append({"photo_id": photo_id, "video_url": url.split("?")[0]})

        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "video_count": len(videos),
            "capture_method": "thin_nav_api" if videos else "empty",
            "diagnostic": diagnostic,
            "videos": videos[:limit],
        }
        output = self._search_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
