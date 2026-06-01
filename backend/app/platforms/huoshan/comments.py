from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import human_pause, require_login
from app.core.config import Settings
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.huoshan.constants import PLATFORM
from app.platforms.huoshan.crawler import HuoshanCrawler
from app.platforms.huoshan.session import HuoshanSessionStore
from app.platforms.huoshan.utils import extract_item_id, is_huoshan_share_url, normalize_video_url
from app.platforms.session_store import PlatformSessionStore
from playwright.async_api import async_playwright


async def resolve_huoshan_video_url(video_url: str, *, headless: bool = True) -> str:
    if not is_huoshan_share_url(video_url) or "hotsoon/s/" not in video_url:
        return normalize_video_url(video_url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=120000)
            import re

            for pattern in (
                r"item_id=(\d{8,22})",
                r"aweme_id=(\d{8,22})",
                r"/video/(\d{8,22})",
            ):
                match = re.search(pattern, page.url) or re.search(pattern, await page.content())
                if match:
                    return normalize_video_url(match.group(1))
            raise ValueError("无法从火山分享短链解析视频 ID")
        finally:
            await context.close()
            await browser.close()


class HuoshanCommentCrawler(DouyinCommentCrawler):
    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store or HuoshanSessionStore(settings), account_id=account_id)
        self.platform = PLATFORM

    @property
    def entry_url(self) -> str:
        return self.settings.huoshan_hot_url

    async def crawl_note_comments(self, content_url: str, show_browser: bool = False) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if is_huoshan_share_url(content_url) and "hotsoon/s/" in content_url:
            content_url = await resolve_huoshan_video_url(content_url, headless=not show_browser)
        else:
            content_url = normalize_video_url(content_url)
        item_id = extract_item_id(content_url)
        payload = await self._fetch_video_comments(video_url=content_url, headless=not show_browser)
        payload["platform"] = PLATFORM
        payload["item_id"] = item_id
        payload["source_url"] = content_url
        payload["note"] = "评论通过抖音 Web 接口抓取，与火山版 item_id 互通。"
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{item_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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
        crawler = HuoshanCrawler(self.settings, self.tenant_id, self.store, account_id=self.account_id)
        if show_browser and not HuoshanCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await crawler.start_interactive_login_session()
        if show_browser:
            session = HuoshanCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
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
        if diagnostic:
            diagnostic = f"{diagnostic}（关键词搜索走抖音 Web，item_id 与火山版互通）"
        results: list[dict] = []
        files: list[Path] = []
        for url in video_urls:
            payload, output = await self.crawl_note_comments(url, show_browser=False)
            payload["keyword_context"] = {"keyword": keyword, "days": days, "region": region}
            results.append(payload)
            files.append(output)
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")
        return results, files, diagnostic
