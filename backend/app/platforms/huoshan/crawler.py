from __future__ import annotations

from app.core.antibot import human_pause, require_login
from app.core.config import Settings
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.huoshan.constants import (
    HOT_MODE_DOUYIN_ONLY,
    HOT_MODE_SEED_ONLY,
    HOT_MODE_SEED_THEN_FALLBACK,
    PLATFORM,
)
from app.platforms.huoshan.feed import fetch_seed_user_videos, parse_seed_user_ids
from app.platforms.huoshan.session import HuoshanSessionStore
from app.platforms.huoshan.utils import build_reflow_url, build_video_url
from app.platforms.session_store import PlatformSessionStore
from app.schemas.crawl import CrawlItem
from app.services.playwright_pool import PlaywrightPool


class HuoshanCrawler(DouyinCrawler):
    platform = PLATFORM

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
        self.store = store or HuoshanSessionStore(settings)
        self.pool = PlaywrightPool.get()

    @property
    def entry_url(self) -> str:
        return self.settings.huoshan_hot_url

    def _seed_user_ids(self) -> list[str]:
        return parse_seed_user_ids(self.settings.huoshan_seed_user_ids)

    def _hot_mode(self) -> str:
        mode = (self.settings.huoshan_hot_mode or HOT_MODE_SEED_THEN_FALLBACK).strip().lower()
        if mode in {HOT_MODE_SEED_ONLY, HOT_MODE_DOUYIN_ONLY, HOT_MODE_SEED_THEN_FALLBACK}:
            return mode
        return HOT_MODE_SEED_THEN_FALLBACK

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        mode = self._hot_mode()
        seeds = self._seed_user_ids()
        results: list[CrawlItem] = []
        seen: set[str] = set()

        if seeds and mode != HOT_MODE_DOUYIN_ONLY:
            per_user = max(limit // len(seeds), 5)
            async with self.pool.tenant_context(
                self.platform, self.tenant_id, self.store, self.settings, account_id=self.account_id
            ) as (_, page):
                for index, sec_uid in enumerate(seeds):
                    if len(results) >= limit:
                        break
                    need = min(per_user, limit - len(results))
                    batch = await fetch_seed_user_videos(
                        page,
                        self.settings,
                        tenant_id=self.tenant_id,
                        sec_uid=sec_uid,
                        limit=need,
                    )
                    for item in batch:
                        content_id = item.external_id or item.douyin_video_id
                        if not content_id or content_id in seen:
                            continue
                        seen.add(content_id)
                        item.rank = len(results) + 1
                        results.append(item)
                    if index < len(seeds) - 1:
                        await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")

        if len(results) >= limit or mode == HOT_MODE_SEED_ONLY:
            return results[:limit]

        remaining = limit - len(results)
        fallback_items = await super().fetch_hot(limit=remaining)
        for item in fallback_items:
            content_id = item.external_id or item.douyin_video_id
            if content_id and content_id in seen:
                continue
            if content_id:
                seen.add(content_id)
            item.platform = PLATFORM
            item.rank = len(results) + 1
            if content_id:
                item.external_id = content_id
                item.video_url = build_video_url(content_id)
            raw = item.raw_data or {}
            raw["platform"] = PLATFORM
            raw["hot_source"] = "douyin_web_fallback"
            raw["note"] = "火山 seed 用户不足时，使用抖音 Web 热榜补齐。"
            if content_id:
                raw["huoshan_reflow_url"] = build_reflow_url(content_id)
            item.raw_data = raw
            results.append(item)
            if len(results) >= limit:
                break
        return results[:limit]
