from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    human_delay,
    human_pause,
    launch_args,
    require_login,
)
from app.core.config import Settings
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore

PLATFORM = "douyin"


COMMENT_PATH = "/aweme/v1/web/comment/list"
REPLY_COMMENT_PATH = "/aweme/v1/web/comment/list/reply"
DROP_QUERY_KEYS = {"a_bogus", "x-secsdk-web-signature", "msToken"}


def _extract_aweme_id(video_url: str) -> str:
    match = re.search(r"/video/(\d+)", video_url)
    if not match:
        raise ValueError(f"无法从链接解析 aweme_id: {video_url}")
    return match.group(1)


def _normalize_comment(item: dict, parent_comment_id: str | None = None) -> dict:
    user = item.get("user") or {}
    avatar = user.get("avatar_larger") or user.get("avatar_medium") or user.get("avatar_thumb") or {}
    avatar_url_list = avatar.get("url_list") or []
    return {
        "comment_id": str(item.get("cid") or ""),
        "parent_comment_id": parent_comment_id,
        "comment": item.get("text") or "",
        "create_time": item.get("create_time"),
        "digg_count": int(item.get("digg_count") or 0),
        "reply_comment_total": int(item.get("reply_comment_total") or 0),
        "username": user.get("nickname") or "",
        "user_id": str(user.get("uid") or ""),
        "sec_uid": user.get("sec_uid") or "",
        "avatar": avatar_url_list[0] if avatar_url_list else "",
    }


def _build_next_url(base_url: str, cursor: int) -> str:
    split = urlsplit(base_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["cursor"] = str(cursor)
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True), ""))


def _set_query(url: str, patch: dict[str, str | int]) -> str:
    split = urlsplit(url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    for key, value in patch.items():
        query[key] = str(value)
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True), ""))


async def _launch_browser(playwright, headless: bool):
    try:
        return await playwright.chromium.launch(headless=headless, args=launch_args()), headless
    except Exception as exc:
        message = str(exc)
        if not headless and ("XServer" in message or "DISPLAY" in message or "headed browser" in message):
            return await playwright.chromium.launch(headless=True, args=launch_args()), True
        raise


class DouyinCommentCrawler:
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
        self.platform = PLATFORM
        self.store = store or DouyinSessionStore(settings)

    @property
    def entry_url(self) -> str:
        return self.settings.douyin_hot_url

    async def crawl_note_comments(self, content_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        aweme_id = _extract_aweme_id(content_url)
        payload = await self._fetch_video_comments(video_url=content_url, headless=not show_browser)
        payload["platform"] = PLATFORM
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output

    async def crawl_video_comments(self, video_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        return await self.crawl_note_comments(video_url, show_browser=show_browser)

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        crawler = DouyinCrawler(self.settings, self.tenant_id, self.store)
        if show_browser and not DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await crawler.start_interactive_login_session()
        if show_browser:
            session = DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
            if session:
                video_urls, diagnostic = await self.search_videos_from_existing_page(
                    page=session["page"],
                    keyword=keyword,
                    limit=limit,
                )
            else:
                video_urls, diagnostic = await self.search_videos_by_keyword(
                    keyword=keyword,
                    limit=limit,
                    headless=False,
                    manual_search=True,
                )
        else:
            video_urls, diagnostic = await self.search_videos_by_keyword(
                keyword=keyword,
                limit=limit,
                headless=True,
                manual_search=False,
            )
        results: list[dict] = []
        files: list[Path] = []
        for url in video_urls:
            payload, output = await self.crawl_note_comments(url, show_browser=False)
            payload["keyword_context"] = {"keyword": keyword, "days": days, "region": region}
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")
        return results, files, diagnostic

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

    async def search_videos_by_keyword(
        self,
        keyword: str,
        limit: int,
        headless: bool = True,
        manual_search: bool = False,
    ) -> tuple[list[str], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        async with async_playwright() as p:
            browser, actual_headless = await _launch_browser(p, headless=headless)
            kwargs = context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))
            has_storage_state = self.store.is_ready(self.store.load(self.tenant_id, self.account_id))
            context = await browser.new_context(**kwargs)
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()
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
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            search_input = page.locator('[data-e2e="searchbar-input"]').first
            if manual_search:
                if await search_input.count() > 0:
                    try:
                        await search_input.click(force=True)
                        await search_input.fill(keyword)
                    except Exception:
                        pass
            else:
                # Try to search from hot page first (more stable than direct search URL)
                if await search_input.count() > 0:
                    await search_input.evaluate(
                        """(el, kw) => {
                            el.value = kw;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""",
                        keyword,
                    )
                    btn = page.locator('[data-e2e="searchbar-button"]').first
                    if await btn.count() > 0:
                        await btn.click(force=True)
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                # If we already captured IDs from search API on current page, do not jump again.
                if not api_aweme_ids and "/search/" not in page.url:
                    await page.goto(f"https://www.douyin.com/search/{quote(keyword)}?source=search_all", wait_until="domcontentloaded")
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")

            # If risk-control/captcha page appears, allow manual verification in visible mode.
            if await self._is_captcha_page(page):
                if headless:
                    await context.close()
                    await browser.close()
                    return [], "关键词搜索命中抖音验证码中间页。请开启“可见浏览器”并在登录窗口完成验证后重试。"
                solved = False
                for _ in range(200):  # up to ~600s
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                    if not await self._is_captcha_page(page):
                        solved = True
                        break
                if not solved:
                    await context.close()
                    await browser.close()
                    return [], "可见浏览器已等待 10 分钟，但验证码仍未通过。请在服务器浏览器中完成验证后重试。"

            links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
            if manual_search and not links:
                # Wait for the user to manually search in the visible browser.
                for _ in range(200):  # up to ~10 minutes
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                    links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                    if links or api_aweme_ids:
                        break
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

            diagnostic: str | None = None
            if not uniq:
                body_text = ""
                try:
                    body_text = (await page.locator("body").inner_text(timeout=3000))[:2000]
                except Exception:
                    body_text = ""
                if not has_storage_state:
                    diagnostic = "未检测到登录 Cookie，关键词搜索可能被限制。请先点击“登录抖音”。"
                elif await self._is_captcha_page(page):
                    diagnostic = "关键词搜索命中抖音验证码中间页，请在服务器浏览器中手动完成搜索后重试。"
                elif actual_headless and not headless:
                    diagnostic = "当前环境无法启动可见浏览器，已自动回退无头模式，建议检查服务器图形环境。"
                elif any(k in body_text for k in ("验证", "验证码", "风险", "异常", "登录后继续")):
                    diagnostic = "疑似触发抖音风控或登录校验，请完成验证后重试。"
                else:
                    diagnostic = "搜索页未识别到视频卡片，可能是关键词结果受限或页面结构变化。"
            elif await self._is_captcha_page(page):
                diagnostic = "已从页面缓存数据提取到视频ID并继续抓取（页面仍处于风控状态）。"
            elif manual_search:
                diagnostic = "已在可见浏览器中接收到了搜索结果，后续将自动抓取这些视频的评论。"

            await context.close()
            await browser.close()
            return uniq[:limit], diagnostic

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
                if "aweme_id" in node and ("desc" in node or "author" in node or "aweme_info" in node):
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

    async def search_videos(
        self,
        keyword: str,
        limit: int = 20,
        show_browser: bool = False,
    ) -> tuple[dict, Path]:
        """Search Douyin by keyword and return structured video list via API interception."""
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        headless = not show_browser
        api_items: dict[str, dict] = {}
        api_aweme_ids: list[str] = []
        uniq_urls: list[str] = []
        diagnostic: str | None = None

        async def on_response(resp):
            try:
                url = resp.url
                if "/aweme/v1/web/" not in url or "search" not in url:
                    return
                data = await resp.json()
            except Exception:
                return
            for row in self._extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)
            for vid in self._extract_aweme_ids_from_json(data):
                if vid not in api_aweme_ids:
                    api_aweme_ids.append(vid)

        async with async_playwright() as p:
            browser, actual_headless = await _launch_browser(p, headless=headless)
            kwargs = context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))
            has_storage_state = self.store.is_ready(self.store.load(self.tenant_id, self.account_id))
            context = await browser.new_context(**kwargs)
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()
            page.on("response", on_response)
            manual_search = show_browser
            try:
                await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
                search_input = page.locator('[data-e2e="searchbar-input"]').first
                if manual_search:
                    if await search_input.count() > 0:
                        try:
                            await search_input.click(force=True)
                            await search_input.fill(keyword)
                        except Exception:
                            pass
                else:
                    if await search_input.count() > 0:
                        await search_input.evaluate(
                            """(el, kw) => {
                                el.value = kw;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""",
                            keyword,
                        )
                        btn = page.locator('[data-e2e="searchbar-button"]').first
                        if await btn.count() > 0:
                            await btn.click(force=True)
                        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                    if not api_aweme_ids and "/search/" not in page.url:
                        await page.goto(
                            f"https://www.douyin.com/search/{quote(keyword)}?source=search_all",
                            wait_until="domcontentloaded",
                        )
                        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")

                if await self._is_captcha_page(page):
                    if headless:
                        diagnostic = "关键词搜索命中抖音验证码中间页。请开启可见浏览器并完成验证后重试。"
                        await context.close()
                        await browser.close()
                        payload = {
                            "platform": PLATFORM,
                            "keyword": keyword,
                            "video_count": 0,
                            "capture_method": "failed",
                            "diagnostic": diagnostic,
                            "videos": [],
                        }
                        output = self._search_videos_output_path(keyword)
                        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                        return payload, output
                    for _ in range(200):
                        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                        if not await self._is_captcha_page(page):
                            break

                links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                if manual_search and not links:
                    for _ in range(200):
                        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                        links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                        if links or api_aweme_ids:
                            break
                if not links and api_aweme_ids:
                    links = [f"https://www.douyin.com/video/{vid}" for vid in api_aweme_ids[:limit]]
                if not links:
                    links = await self._extract_video_urls_from_page_payload(page, limit=limit)

                uniq_urls: list[str] = []
                seen_href = set()
                for href in links:
                    if href and href not in seen_href:
                        seen_href.add(href)
                        uniq_urls.append(href.split("?")[0])
                    if len(uniq_urls) >= limit:
                        break

                if not uniq_urls:
                    body_text = ""
                    try:
                        body_text = (await page.locator("body").inner_text(timeout=3000))[:2000]
                    except Exception:
                        body_text = ""
                    if not has_storage_state:
                        diagnostic = "未检测到登录 Cookie，关键词搜索可能被限制。请先登录抖音。"
                    elif await self._is_captcha_page(page):
                        diagnostic = "关键词搜索命中验证码中间页，请完成验证后重试。"
                    elif any(k in body_text for k in ("验证", "验证码", "风险", "异常", "登录后继续")):
                        diagnostic = "疑似触发抖音风控或登录校验，请完成验证后重试。"
                    else:
                        diagnostic = "搜索页未识别到视频结果，可能是关键词受限或页面结构变化。"
                elif manual_search:
                    diagnostic = "已在可见浏览器中接收到搜索结果。"
            finally:
                try:
                    page.remove_listener("response", on_response)
                except Exception:
                    pass
                await context.close()
                await browser.close()

        videos: list[dict] = []
        seen_ids: set[str] = set()
        for url in uniq_urls:
            match = re.search(r"/video/(\d{8,22})", url)
            aweme_id = match.group(1) if match else ""
            if not aweme_id or aweme_id in seen_ids:
                continue
            seen_ids.add(aweme_id)
            videos.append(api_items.get(aweme_id) or {
                "aweme_id": aweme_id,
                "video_url": url,
                "title": "",
                "author": "",
                "author_id": "",
                "sec_uid": "",
                "digg_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "create_time": None,
            })
        for aweme_id, row in api_items.items():
            if aweme_id in seen_ids or len(videos) >= limit:
                continue
            seen_ids.add(aweme_id)
            videos.append(row)
        videos = videos[:limit]

        capture_method = "network_api" if any(v.get("title") for v in videos) else "url_fallback"
        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "video_count": len(videos),
            "capture_method": capture_method,
            "diagnostic": diagnostic,
            "videos": videos,
        }
        output = self._search_videos_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output

    def _search_videos_output_path(self, keyword: str) -> Path:
        safe_keyword = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", keyword)[:32]
        path = (
            self.settings.report_output_dir
            / f"search_videos_{PLATFORM}_{self.tenant_id}_{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def _fetch_video_comments(self, video_url: str, headless: bool = True) -> dict:
        aweme_id = _extract_aweme_id(video_url)
        async with async_playwright() as p:
            browser, _ = await _launch_browser(p, headless=headless)
            kwargs = context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))
            context = await browser.new_context(**kwargs)
            await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
            page = await context.new_page()
            first_response: dict = {"url": None, "data": None}
            captured_pages: list[tuple[str, dict]] = []

            async def on_response(resp):
                if COMMENT_PATH in resp.url:
                    try:
                        data = await resp.json()
                        if isinstance(data, dict) and ("comments" in data or "total" in data):
                            first_response["url"] = resp.url
                            first_response["data"] = data
                            captured_pages.append((resp.url, data))
                    except Exception:
                        return

            page.on("response", on_response)
            await page.goto(video_url, wait_until="domcontentloaded", timeout=120000)

            # Try several times to trigger comment requests, because Douyin often lazy-loads comments.
            for _ in range(4):
                if first_response["url"] and first_response["data"]:
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                # Try clicking likely comment entry points to trigger requests.
                for selector in ('[data-e2e*="comment"]', 'button:has-text("评论")', 'span:has-text("评论")'):
                    loc = page.locator(selector).first
                    try:
                        if await loc.count() > 0:
                            await loc.click(force=True, timeout=1000)
                            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                    except Exception:
                        continue

                # Fallback: inspect resource entries in case response event was missed.
                if not first_response["url"]:
                    resource_url = await page.evaluate(
                        """(pathPart) => {
                            const list = performance.getEntriesByType('resource')
                                .map(e => e.name)
                                .filter(u => u.includes(pathPart));
                            return list.length ? list[list.length - 1] : null;
                        }""",
                        COMMENT_PATH,
                    )
                    if resource_url:
                        try:
                            data = await page.evaluate(
                                """async (url) => {
                                    const resp = await fetch(url, { credentials: 'include' });
                                    const text = await resp.text();
                                    if (!text) return {};
                                    try {
                                        return JSON.parse(text);
                                    } catch {
                                        return {};
                                    }
                                }""",
                                resource_url,
                            )
                            if isinstance(data, dict) and ("comments" in data or "total" in data):
                                first_response["url"] = resource_url
                                first_response["data"] = data
                                break
                        except Exception:
                            pass

            if not first_response["url"] or not first_response["data"]:
                dom_comments = await self._extract_comments_from_dom(page)
                await context.close()
                await browser.close()
                return {
                    "platform": PLATFORM,
                    "aweme_id": aweme_id,
                    "video_url": video_url,
                    "api_total_top_comments": 0,
                    "top_comments_captured": len(dom_comments),
                    "reply_comments_captured_preview": 0,
                    "expected_reply_total_from_top_comments": 0,
                    "total_comments_captured": len(dom_comments),
                    "capture_method": "dom_fallback",
                    "warning": "未捕获到评论接口响应，结果来自页面可见评论（可能不全）。如需全量请先登录并完成验证码。",
                    "comments": dom_comments,
                }

            comments_map: dict[str, dict] = {}
            first_data: dict = first_response["data"]
            api_total = int(first_data.get("total") or 0)
            api_url = first_response["url"]
            consumed_cursors: set[int] = set()

            def merge_page(data: dict) -> None:
                for c in data.get("comments") or []:
                    row = _normalize_comment(c)
                    if row["comment_id"]:
                        comments_map[row["comment_id"]] = row
                    for reply in c.get("reply_comment") or []:
                        reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                        if reply_row["comment_id"]:
                            comments_map[reply_row["comment_id"]] = reply_row

            # 1) 优先合并页面已返回的数据（接口监听结果）
            for _, data in captured_pages:
                try:
                    consumed_cursors.add(int(data.get("cursor") or 0))
                except Exception:
                    pass
                merge_page(data)

            cursor = 0
            has_more = 1
            guard = 0
            while has_more and guard < 50:
                guard += 1
                if cursor in consumed_cursors and guard > 1:
                    has_more = 1
                    cursor += 20
                    continue
                page_url = _build_next_url(api_url, cursor).replace("count=5", "count=20")
                data = await page.evaluate(
                    """async (url) => {
                        const resp = await fetch(url, { credentials: 'include' });
                        const text = await resp.text();
                        if (!text) return {};
                        try {
                            return JSON.parse(text);
                        } catch {
                            return {};
                        }
                    }""",
                    page_url,
                )
                if not isinstance(data, dict):
                    data = {}
                merge_page(data)
                cursor = int(data.get("cursor") or cursor)
                has_more = int(data.get("has_more") or 0)
                if not data.get("comments"):
                    break

            # 2) 对回复总数大于预览数量的评论，主动拉 reply 接口补齐
            reply_api_url = _set_query(
                api_url.replace(COMMENT_PATH, REPLY_COMMENT_PATH),
                {"aweme_id": aweme_id, "item_id": aweme_id, "count": 20},
            )
            top_rows_snapshot = [row for row in comments_map.values() if not row.get("parent_comment_id")]
            for top in top_rows_snapshot:
                cid = top.get("comment_id")
                if not cid:
                    continue
                need_total = int(top.get("reply_comment_total") or 0)
                if need_total <= 0:
                    continue
                current_reply = sum(1 for row in comments_map.values() if row.get("parent_comment_id") == cid)
                if current_reply >= need_total:
                    continue
                reply_cursor = 0
                reply_guard = 0
                while reply_guard < 50:
                    reply_guard += 1
                    url = _set_query(
                        reply_api_url,
                        {"comment_id": cid, "cursor": reply_cursor, "count": 20},
                    )
                    data = await page.evaluate(
                        """async (url) => {
                            const resp = await fetch(url, { credentials: 'include' });
                            const text = await resp.text();
                            if (!text) return {};
                            try {
                                return JSON.parse(text);
                            } catch {
                                return {};
                            }
                        }""",
                        url,
                    )
                    if not isinstance(data, dict):
                        data = {}
                    rows = data.get("comments") or data.get("reply_comments") or []
                    if not rows:
                        break
                    for reply in rows:
                        reply_row = _normalize_comment(reply, parent_comment_id=cid)
                        if reply_row["comment_id"]:
                            comments_map[reply_row["comment_id"]] = reply_row
                    current_reply = sum(1 for row in comments_map.values() if row.get("parent_comment_id") == cid)
                    has_more_reply = int(data.get("has_more") or 0)
                    if not has_more_reply or current_reply >= need_total:
                        break
                    reply_cursor = int(data.get("cursor") or (reply_cursor + 20))

            await context.close()
            await browser.close()

        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = [row for row in comments if not row.get("parent_comment_id")]
        preview_reply_rows = [row for row in comments if row.get("parent_comment_id")]
        expected_reply_total = sum(int(row.get("reply_comment_total") or 0) for row in top_rows)
        return {
            "platform": PLATFORM,
            "aweme_id": aweme_id,
            "video_url": video_url,
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
