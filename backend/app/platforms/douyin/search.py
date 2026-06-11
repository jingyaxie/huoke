from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    human_click,
    human_delay,
    human_type,
    launch_browser,
    require_login,
)
from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.js_constants import (
    PLATFORM,
    _FIRE_FETCH_JS,
    _SEARCH_API_EXCLUDES,
    _SEARCH_JS_CHANNELS,
    _SEARCH_RESULT_API_MARKERS,
    _build_search_api_url,
    _build_search_sug_url,
    _encode_search_keyword,
    _extract_search_id_from_sug,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class DouyinSearchTool(DouyinJsApiTool):
    """抖音关键词搜索工具（薄浏览器 + API 拦截）。"""

    def entry_url(self) -> str:
        """UI 搜索回退入口（热榜页，已验证可点搜索框）。"""
        return self.settings.douyin_hot_url

    @property

    def js_warmup_urls(self) -> tuple[str, ...]:
        """JS 直调预热：首页参数更全，热榜兜底。"""
        return (self.settings.douyin_home_url, self.settings.douyin_hot_url)


    async def _thin_browser_keyword_search(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        captured_api_urls: list[str],
    ) -> tuple[list[str], str | None, str]:
        """薄浏览器：首页预热 → 搜索页拦截 API（主路径）→ 回首页 fetch 评论。"""
        await self.warmup_for_js_api(page, captured_api_urls)
        comment_template = await self.pick_api_template_url(page, captured_api_urls)
        api_items: dict[str, dict] = {}
        nav_result = await self._search_videos_via_thin_nav(
            page,
            keyword,
            limit,
            api_items,
            captured_api_urls,
            template_url=comment_template,
        )
        if not nav_result:
            search_template = await self.pick_api_template_url(page, captured_api_urls) or comment_template
            js_result = await self._search_videos_via_js_api(
                page, keyword, limit, search_template, api_items, max_attempts=1
            )
            nav_result = js_result
        if nav_result:
            await self._restore_comment_api_context(page, comment_template)
            return nav_result[0], nav_result[1], comment_template
        await self._restore_comment_api_context(page, comment_template)
        return (
            [],
            "薄浏览器搜索未返回视频，请确认 Cookie 有效或在 VNC 手动搜索后设 show_browser=true。",
            comment_template,
        )


    async def _restore_comment_api_context(self, page, warmup_url: str | None = None) -> None:
        """评论 fetch 需在首页上下文；搜索页同域 fetch comment/list 会挂起。"""
        current = page.url or ""
        if "/search/" not in current:
            return
        target = self.settings.douyin_home_url
        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)


    async def search_videos_from_existing_page(self, page, keyword: str, limit: int) -> tuple[list[str], str | None]:
        api_aweme_ids: list[str] = []

        async def on_response(resp):
            try:
                url = resp.url
                if "/aweme/v1/web/" not in url or "search" not in url:
                    return
                data = await resp.json()
            except Exception:
                return
            for vid in self._extract_aweme_ids_from_json(data):
                if vid not in api_aweme_ids:
                    api_aweme_ids.append(vid)
                    if len(api_aweme_ids) >= max(limit * 3, 20):
                        break

        page.on("response", on_response)
        try:
            search_input = page.locator('[data-e2e="searchbar-input"]').first
            if await search_input.count() > 0:
                await search_input.click(force=True)
                await search_input.fill(keyword)
                btn = page.locator('[data-e2e="searchbar-button"]').first
                if await btn.count() > 0:
                    await btn.click(force=True)
            # wait up to ~5 min for either links or captured ids
            links: list[str] = []
            for _ in range(100):
                links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                if links or api_aweme_ids:
                    break
                await page.wait_for_timeout(3000)
            if not links and api_aweme_ids:
                links = [f"https://www.douyin.com/video/{vid}" for vid in api_aweme_ids[:limit]]
            if not links:
                links = await self._extract_video_urls_from_page_payload(page, limit=limit)
            uniq: list[str] = []
            seen = set()
            for href in links:
                if href and href not in seen:
                    seen.add(href)
                    uniq.append(href.split("?")[0])
                if len(uniq) >= limit:
                    break
            if uniq:
                return uniq, "已复用服务器可见浏览器会话提取到视频并自动抓取评论。"
            if await self._is_captcha_page(page):
                return [], "可见浏览器当前仍在验证码中间页，未提取到可用视频。请先在该窗口完成人工操作。"
            return [], "可见浏览器会话未检测到视频结果，请重试搜索词或重新触发搜索。"
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    @staticmethod

    def _is_search_result_api(url: str) -> bool:
        if any(ex in url for ex in _SEARCH_API_EXCLUDES):
            return False
        return any(marker in url for marker in _SEARCH_RESULT_API_MARKERS)

    @staticmethod

    def _keyword_tokens(keyword: str) -> list[str]:
        tokens = [t.strip() for t in re.split(r"[\s,，、]+", keyword) if len(t.strip()) >= 2]
        return tokens or [keyword.strip()]


    def _title_matches_keyword(self, title: str, keyword: str) -> bool:
        if not title:
            return False
        text = title.lower()
        tokens = self._keyword_tokens(keyword)
        core = [t for t in tokens if len(t) >= 3]
        check = core or tokens
        return any(token.lower() in text for token in check)


    def _rank_search_items(self, items: list[dict], keyword: str) -> list[dict]:
        tokens = [t.lower() for t in self._keyword_tokens(keyword)]

        def score(row: dict) -> int:
            title = (row.get("title") or "").lower()
            if not title:
                return 0
            return sum(2 if token in title else 0 for token in tokens)

        ranked = sorted(items, key=lambda row: (score(row), row.get("digg_count") or 0), reverse=True)
        matched = [row for row in ranked if self._title_matches_keyword(row.get("title") or "", keyword)]
        return matched or ranked


    async def _switch_to_video_tab(self, page, *, profile: str = "fast") -> None:
        selectors = (
            '[data-e2e="search-tab-video"]',
            '[data-e2e="tab-video"]',
            'text=视频',
            'a[href*="type=video"]',
        )
        for selector in selectors:
            tab = page.locator(selector).first
            if await tab.count() == 0:
                continue
            try:
                await human_click(page, tab, self.settings, tenant_id=self.tenant_id, timeout=5000)
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=profile)
                return
            except Exception:
                continue

    @staticmethod

    async def _search_videos_via_thin_nav(
        self,
        page,
        keyword: str,
        limit: int,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        *,
        template_url: str,
    ) -> tuple[list[str], str | None] | None:
        """主路径：搜索页建立上下文 → 触发已签名 search 请求 → response 拦截解析。"""
        search_url = f"https://www.douyin.com/search/{_encode_search_keyword(keyword)}?type=video"
        target_count = max(limit * 3, 15)
        processed_responses: set[int] = set()
        listener, pending_tasks = self._make_search_response_listener(
            api_items, target_count, captured_api_urls, processed_responses
        )
        page.on("response", listener)
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._drain_search_ingest_tasks(pending_tasks)

            if not api_items:
                await self._fire_search_api_requests(
                    page,
                    keyword,
                    template_url,
                    api_items,
                    captured_api_urls,
                    pending_tasks,
                    processed_responses,
                    target_count=target_count,
                )
            await self._wait_search_ingest(
                page, pending_tasks, api_items, target_count=limit, rounds=12
            )

            if len(api_items) < limit and not await self._is_captcha_page(page):
                await page.mouse.wheel(0, 800)
                await page.wait_for_timeout(1500)
                await self._fire_search_api_requests(
                    page,
                    keyword,
                    template_url,
                    api_items,
                    captured_api_urls,
                    pending_tasks,
                    processed_responses,
                    target_count=target_count,
                    offset=10,
                )
                await self._wait_search_ingest(
                    page, pending_tasks, api_items, target_count=limit, rounds=8
                )
        finally:
            await self._wait_search_ingest(
                page, pending_tasks, api_items, target_count=limit, rounds=10
            )
            try:
                page.remove_listener("response", listener)
            except Exception:
                pass

        if api_items:
            return self._finalize_search_results(api_items, keyword, limit, mode="thin_nav_api")
        if await self._is_captcha_page(page):
            return None
        return None


    async def _fire_search_api_requests(
        self,
        page,
        keyword: str,
        template_url: str,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        pending_tasks: list[asyncio.Task],
        processed_responses: set[int],
        *,
        target_count: int,
        offset: int = 0,
    ) -> None:
        """仅触发 fetch，不在 evaluate 内解析；响应由监听器拦截。"""
        sug_data = await self.fetch_json_via_page(
            page, _build_search_sug_url(template_url, keyword), timeout_ms=8000
        )
        search_id = _extract_search_id_from_sug(sug_data)
        fetch_count = max(target_count, 15)
        for path, channel in _SEARCH_JS_CHANNELS:
            if len(api_items) >= target_count:
                break
            url = _build_search_api_url(
                template_url,
                keyword,
                path=path,
                offset=offset,
                count=fetch_count,
                search_channel=channel,
                search_id=search_id,
            )
            try:
                async with page.expect_response(
                    lambda resp: self._is_search_result_api(resp.url),
                    timeout=15000,
                ) as resp_info:
                    await page.evaluate(_FIRE_FETCH_JS, {"url": url, "timeoutMs": 15000})
                await self._ingest_search_response(
                    await resp_info.value,
                    api_items,
                    captured_api_urls,
                    target_count,
                    processed_responses,
                )
            except Exception:
                await page.evaluate(_FIRE_FETCH_JS, {"url": url, "timeoutMs": 15000})
                await self._wait_search_ingest(
                    page, pending_tasks, api_items, target_count=1, rounds=6
                )
            if api_items:
                break

    @staticmethod

    async def _drain_search_ingest_tasks(tasks: list[asyncio.Task]) -> None:
        if not tasks:
            return
        batch = list(tasks)
        tasks.clear()
        await asyncio.gather(*batch, return_exceptions=True)


    async def _wait_search_ingest(
        self,
        page,
        pending_tasks: list[asyncio.Task],
        api_items: dict[str, dict],
        *,
        target_count: int,
        rounds: int,
    ) -> None:
        for _ in range(rounds):
            await self._drain_search_ingest_tasks(pending_tasks)
            if len(api_items) >= target_count:
                return
            await page.wait_for_timeout(500)


    def _make_search_response_listener(
        self,
        api_items: dict[str, dict],
        target_count: int,
        captured_api_urls: list[str],
        processed_responses: set[int],
    ) -> tuple[object, list[asyncio.Task]]:
        pending_tasks: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not self._is_search_result_api(resp.url):
                return
            pending_tasks.append(
                asyncio.create_task(
                    self._ingest_search_response(
                        resp,
                        api_items,
                        captured_api_urls,
                        target_count,
                        processed_responses,
                    )
                )
            )

        return on_response, pending_tasks


    async def _ingest_search_response(
        self,
        resp,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        target_count: int,
        processed_responses: set[int],
    ) -> None:
        if id(resp) in processed_responses:
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
        processed_responses.add(id(resp))
        for row in self._extract_aweme_items_from_json(data):
            api_items.setdefault(row["aweme_id"], row)
            if len(api_items) >= target_count:
                return
        for vid in self._extract_aweme_ids_from_json(data):
            if len(api_items) >= target_count:
                return
            if vid in api_items:
                continue
            api_items[vid] = {
                "aweme_id": vid,
                "video_url": f"https://www.douyin.com/video/{vid}",
                "title": "",
                "author": "",
                "author_id": "",
                "sec_uid": "",
                "digg_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "create_time": None,
            }


    def _finalize_search_results(
        self,
        api_items: dict[str, dict],
        keyword: str,
        limit: int,
        *,
        mode: str,
    ) -> tuple[list[str], str | None] | None:
        ranked = self._rank_search_items(list(api_items.values()), keyword)
        uniq: list[str] = []
        seen: set[str] = set()
        for row in ranked:
            url = row.get("video_url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            uniq.append(url.split("?")[0])
            if len(uniq) >= limit:
                break
        if not uniq:
            return None
        label = "thin_nav_api" if mode == "thin_nav_api" else "thin_js_api"
        diagnostic = f"关键词「{keyword}」搜索成功（{label}，{len(uniq)} 条视频）"
        if ranked and not self._title_matches_keyword(ranked[0].get("title") or "", keyword):
            diagnostic = (
                f"{label} 已返回结果但标题与「{keyword}」匹配度低"
                f"（首条：{ranked[0].get('title', '')[:40]}）"
            )
        return uniq[:limit], diagnostic


    async def _search_videos_via_js_api(
        self,
        page,
        keyword: str,
        limit: int,
        template_url: str,
        api_items: dict[str, dict],
        *,
        max_attempts: int = 6,
    ) -> tuple[list[str], str | None] | None:
        """兜底：fetch 搜索 API（部分环境缺 a_bogus 会挂起，仅少量尝试）。"""
        sug_data = await self.fetch_json_via_page(
            page, _build_search_sug_url(template_url, keyword), timeout_ms=8000
        )
        search_id = _extract_search_id_from_sug(sug_data)
        fetch_count = max(limit * 3, 15)
        attempts = 0
        for path, channel in _SEARCH_JS_CHANNELS:
            for offset in (0, 10):
                if attempts >= max_attempts:
                    break
                attempts += 1
                url = _build_search_api_url(
                    template_url,
                    keyword,
                    path=path,
                    offset=offset,
                    count=fetch_count,
                    search_channel=channel,
                    search_id=search_id,
                )
                data = await self.fetch_json_via_page(page, url, timeout_ms=8000)
                if not data:
                    continue
                status_code = data.get("status_code")
                if status_code not in (None, 0):
                    continue
                for row in self._extract_aweme_items_from_json(data):
                    api_items.setdefault(row["aweme_id"], row)
                if api_items:
                    return self._finalize_search_results(api_items, keyword, limit, mode="thin_js_api")
        return None


    async def _trigger_keyword_search(
        self,
        page,
        keyword: str,
        *,
        manual_search: bool,
        search_started: dict[str, bool],
        skip_goto: bool = False,
    ) -> None:
        if manual_search:
            search_started["value"] = True
            return
        delay_profile = "fast"
        if not skip_goto:
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=60000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=delay_profile)
        search_input = page.locator('[data-e2e="searchbar-input"]').first
        if await search_input.count() == 0:
            return
        await human_click(page, search_input, self.settings, tenant_id=self.tenant_id)
        await human_type(page, search_input, keyword, self.settings, tenant_id=self.tenant_id)
        search_started["value"] = True

        async def _submit_search() -> None:
            btn = page.locator('[data-e2e="searchbar-button"]').first
            if await btn.count() > 0:
                await btn.click(force=True)
            else:
                await page.keyboard.press("Enter")

        try:
            async with page.expect_response(
                lambda resp: self._is_search_result_api(resp.url),
                timeout=25000,
            ):
                await _submit_search()
        except Exception:
            await _submit_search()
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=delay_profile)

        for _ in range(10):
            if "/search/" in page.url:
                break
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=delay_profile)
        await self._switch_to_video_tab(page)


    async def _collect_keyword_search_results(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        headless: bool,
        manual_search: bool,
        api_items: dict[str, dict],
        has_storage_state: bool,
        search_started: dict[str, bool],
        captured_api_urls: list[str] | None = None,
    ) -> tuple[list[str], str | None]:
        if not manual_search:
            urls, diag, _ = await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls or [],
            )
            return urls, diag
        else:
            await self._switch_to_video_tab(page)

        if await self._is_captcha_page(page):
            if headless:
                return [], "关键词搜索命中抖音验证码中间页。请打开 VNC 可见浏览器完成验证后重试。"
            for _ in range(120):
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                if not await self._is_captcha_page(page):
                    break
            else:
                return [], "可见浏览器已等待较长时间，验证码仍未通过。请在 VNC 中手动完成验证。"

        scroll_profile = "fast" if not manual_search else "scroll"
        for _ in range(4 if not manual_search else 12):
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=scroll_profile)
            await page.mouse.wheel(0, 900)
            if api_items:
                break

        ranked = self._rank_search_items(list(api_items.values()), keyword)
        uniq: list[str] = []
        seen: set[str] = set()
        for row in ranked:
            url = row.get("video_url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            uniq.append(url.split("?")[0])
            if len(uniq) >= limit:
                break

        if not uniq and "/search/" in page.url:
            links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
            for href in links:
                if href and href not in seen:
                    seen.add(href)
                    uniq.append(href.split("?")[0])
                if len(uniq) >= limit:
                    break

        if manual_search and not uniq:
            for _ in range(120):
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                ranked = self._rank_search_items(list(api_items.values()), keyword)
                if ranked:
                    uniq = [row["video_url"].split("?")[0] for row in ranked[:limit]]
                    break
                links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                if links:
                    uniq = [h.split("?")[0] for h in links[:limit]]
                    break

        diagnostic: str | None = None
        if not uniq:
            if not has_storage_state:
                diagnostic = "未检测到登录 Cookie，请先登录抖音。"
            elif await self._is_captcha_page(page):
                diagnostic = "命中验证码中间页，请在 VNC 中完成验证。"
            elif "/search/" not in page.url and not api_items:
                diagnostic = "搜索未进入结果页，请确认关键词或在 VNC 手动搜索后重试。"
            else:
                diagnostic = f"搜索「{keyword}」未找到相关视频，请换关键词或在 VNC 手动切到「视频」标签后重试。"
        elif ranked and not self._title_matches_keyword(ranked[0].get("title") or "", keyword):
            diagnostic = (
                f"已取搜索结果但标题与「{keyword}」匹配度低"
                f"（首条：{ranked[0].get('title', '')[:40]}），请人工核对。"
            )
        elif manual_search:
            diagnostic = "已在可见浏览器中接收到搜索结果。"
        return uniq[:limit], diagnostic


    async def search_videos_by_keyword(
        self,
        keyword: str,
        limit: int,
        headless: bool | None = None,
        manual_search: bool = False,
    ) -> tuple[list[str], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        has_storage_state = self.store.is_ready(self.store.load(self.tenant_id, self.account_id))
        api_items: dict[str, dict] = {}
        search_started: dict[str, bool] = {"value": manual_search}

        async def on_response(resp):
            if not search_started["value"]:
                return
            try:
                url = resp.url
                if not self._is_search_result_api(url):
                    return
                data = await resp.json()
            except Exception:
                return
            for row in self._extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)
                if len(api_items) >= max(limit * 5, 30):
                    break

        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            page.on("response", on_response)
            try:
                return await self._collect_keyword_search_results(
                    page,
                    keyword=keyword,
                    limit=limit,
                    headless=resolved_headless,
                    manual_search=manual_search,
                    api_items=api_items,
                    has_storage_state=has_storage_state,
                    search_started=search_started,
                )
            finally:
                try:
                    page.remove_listener("response", on_response)
                except Exception:
                    pass


    async def _is_captcha_page(self, page) -> bool:
        try:
            title = (await page.title()) or ""
            if "验证码中间页" in title:
                return True
            body_text = await page.locator("body").inner_text(timeout=1500)
            return "验证码中间页" in body_text
        except Exception:
            return False


    async def _extract_video_urls_from_page_payload(self, page, limit: int) -> list[str]:
        candidates: list[str] = []
        # 1) from full html
        try:
            html = await page.content()
            candidates.extend(re.findall(r"/video/(\d{8,22})", html))
            candidates.extend(re.findall(r'"aweme_id"\s*:\s*"(\d{8,22})"', html))
        except Exception:
            pass
        # 2) from inline script text
        try:
            script_texts = await page.locator("script").evaluate_all("els => els.map(e => e.textContent || '').slice(0, 200)")
            for text in script_texts:
                if not text:
                    continue
                candidates.extend(re.findall(r"/video/(\d{8,22})", text))
                candidates.extend(re.findall(r'"aweme_id"\s*:\s*"(\d{8,22})"', text))
        except Exception:
            pass
        # 3) from performance resource urls
        try:
            urls = await page.evaluate(
                """() => performance.getEntriesByType('resource').map(e => e.name).slice(-400)"""
            )
            for url in urls or []:
                candidates.extend(re.findall(r"/video/(\d{8,22})", url))
                candidates.extend(re.findall(r"aweme_id=(\d{8,22})", url))
        except Exception:
            pass
        uniq_ids: list[str] = []
        seen = set()
        for vid in candidates:
            if not vid or vid in seen:
                continue
            seen.add(vid)
            uniq_ids.append(vid)
            if len(uniq_ids) >= limit:
                break
        return [f"https://www.douyin.com/video/{vid}" for vid in uniq_ids]


    def _extract_aweme_ids_from_json(self, data) -> list[str]:
        ids: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "aweme_id" and isinstance(v, (str, int)):
                        vid = str(v)
                        if re.fullmatch(r"\d{8,22}", vid):
                            ids.append(vid)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        uniq: list[str] = []
        seen = set()
        for vid in ids:
            if vid in seen:
                continue
            seen.add(vid)
            uniq.append(vid)
        return uniq


    def _normalize_search_aweme(self, node: dict) -> dict | None:
        aweme = node.get("aweme_info") if isinstance(node.get("aweme_info"), dict) else node
        if not isinstance(aweme, dict):
            return None
        aweme_id = str(aweme.get("aweme_id") or "")
        if not re.fullmatch(r"\d{8,22}", aweme_id):
            return None
        author = aweme.get("author") or {}
        stats = aweme.get("statistics") or {}
        return {
            "aweme_id": aweme_id,
            "video_url": f"https://www.douyin.com/video/{aweme_id}",
            "title": (aweme.get("desc") or "").strip(),
            "author": (author.get("nickname") or "").strip(),
            "author_id": str(author.get("uid") or ""),
            "sec_uid": author.get("sec_uid") or "",
            "digg_count": int(stats.get("digg_count") or 0),
            "comment_count": int(stats.get("comment_count") or 0),
            "share_count": int(stats.get("share_count") or 0),
            "create_time": aweme.get("create_time"),
        }


    def _extract_aweme_items_from_json(self, data) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                if "aweme_info" in node or (
                    "aweme_id" in node and ("desc" in node or "author" in node)
                ):
                    row = self._normalize_search_aweme(node)
                    if row and row["aweme_id"] not in seen:
                        seen.add(row["aweme_id"])
                        items.append(row)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return items

    def _search_videos_output_path(self, keyword: str) -> Path:
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
        """关键词搜索视频（薄浏览器主路径），返回结构化结果与报告路径。"""
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
            video_urls, diagnostic, _ = await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
            )

        videos: list[dict] = []
        seen: set[str] = set()
        for url in video_urls:
            match = re.search(r"/video/(\d{8,22})", url)
            if not match:
                continue
            aweme_id = match.group(1)
            if aweme_id in seen:
                continue
            seen.add(aweme_id)
            videos.append({"aweme_id": aweme_id, "video_url": url.split("?")[0]})

        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "video_count": len(videos),
            "capture_method": "thin_nav_api" if videos else "empty",
            "diagnostic": diagnostic,
            "videos": videos[:limit],
        }
        output = self._search_videos_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
