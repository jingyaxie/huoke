from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from playwright.async_api import Page

from app.core.antibot import human_delay, human_scroll
from app.core.config import Settings
from app.platforms.huoshan.constants import PLATFORM, USER_POST_PATH, USER_PROFILE_URL
from app.platforms.huoshan.utils import build_reflow_url, build_video_url
from app.schemas.crawl import CrawlItem
from app.utils.parsers import parse_count


def parse_seed_user_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[\n,;]+", text) if part.strip()]


def user_profile_url(sec_uid: str) -> str:
    return USER_PROFILE_URL.format(sec_uid=quote(sec_uid, safe=""))


def aweme_to_crawl_item(
    aweme: dict[str, Any],
    *,
    rank: int,
    tenant_id: str,
    seed_user_id: str,
    author_name: str | None = None,
) -> CrawlItem | None:
    item_id = str(aweme.get("aweme_id") or aweme.get("item_id") or "")
    if not re.fullmatch(r"\d{8,22}", item_id):
        return None
    author = aweme.get("author") or {}
    stats = aweme.get("statistics") or {}
    title = str(aweme.get("desc") or aweme.get("title") or "").strip()
    if not title:
        title = f"火山视频 {item_id[:8]}"
    nickname = author_name or author.get("nickname") or author.get("unique_id")
    publish_time = None
    create_time = aweme.get("create_time")
    if create_time:
        try:
            publish_time = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            publish_time = None
    cover_url = _pick_cover(aweme)
    sec_uid = author.get("sec_uid") or seed_user_id
    return CrawlItem(
        platform=PLATFORM,
        rank=rank,
        title=title[:500],
        author_name=nickname,
        external_id=item_id,
        douyin_video_id=item_id,
        video_url=build_video_url(item_id),
        cover_url=cover_url,
        like_count=int(stats.get("digg_count") or stats.get("like_count") or 0),
        comment_count=parse_count(stats.get("comment_count")),
        share_count=parse_count(stats.get("share_count")),
        publish_time=publish_time,
        author_avatar_url=_pick_avatar(author),
        author_profile_url=user_profile_url(sec_uid) if sec_uid else None,
        raw_data={
            "platform": PLATFORM,
            "tenant_id": tenant_id,
            "hot_source": "seed_user",
            "seed_user_id": seed_user_id,
            "author_sec_uid": sec_uid,
            "huoshan_reflow_url": build_reflow_url(item_id),
            "aweme_id": item_id,
        },
    )


async def fetch_seed_user_videos(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    sec_uid: str,
    limit: int,
) -> list[CrawlItem]:
    captured_posts: list[dict[str, Any]] = []

    async def on_response(resp) -> None:
        try:
            if USER_POST_PATH not in resp.url or resp.status != 200:
                return
            data = await resp.json()
            if isinstance(data, dict) and isinstance(data.get("aweme_list"), list):
                captured_posts.append(data)
        except Exception:
            return

    page.on("response", on_response)
    try:
        await page.goto(user_profile_url(sec_uid), wait_until="domcontentloaded", timeout=120000)
        await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
        for _ in range(8):
            items = _items_from_posts(captured_posts, tenant_id=tenant_id, seed_user_id=sec_uid)
            if len(items) >= limit:
                return items[:limit]
            await human_scroll(page, settings, tenant_id=tenant_id)
        items = _items_from_posts(captured_posts, tenant_id=tenant_id, seed_user_id=sec_uid)
        if items:
            return items[:limit]
        return await _items_from_dom(page, tenant_id=tenant_id, seed_user_id=sec_uid, limit=limit)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def _items_from_posts(
    payloads: list[dict[str, Any]],
    *,
    tenant_id: str,
    seed_user_id: str,
) -> list[CrawlItem]:
    results: list[CrawlItem] = []
    seen: set[str] = set()
    for payload in payloads:
        for aweme in payload.get("aweme_list") or []:
            if not isinstance(aweme, dict):
                continue
            item = aweme_to_crawl_item(
                aweme,
                rank=len(results) + 1,
                tenant_id=tenant_id,
                seed_user_id=seed_user_id,
            )
            if not item or not item.external_id or item.external_id in seen:
                continue
            seen.add(item.external_id)
            results.append(item)
    return results


async def _items_from_dom(
    page: Page,
    *,
    tenant_id: str,
    seed_user_id: str,
    limit: int,
) -> list[CrawlItem]:
    links = await page.locator('a[href*="/video/"]').evaluate_all(
        "els => [...new Set(els.map(e => ({ href: e.href, text: (e.innerText || '').trim() })))]"
    )
    results: list[CrawlItem] = []
    seen: set[str] = set()
    for link in links:
        href = link.get("href") or ""
        match = re.search(r"/video/(\d{8,22})", href)
        if not match:
            continue
        item_id = match.group(1)
        if item_id in seen:
            continue
        seen.add(item_id)
        text = (link.get("text") or "").strip()
        title = text if len(text) >= 2 else f"火山视频 {item_id[:8]}"
        results.append(
            CrawlItem(
                platform=PLATFORM,
                rank=len(results) + 1,
                title=title[:500],
                external_id=item_id,
                douyin_video_id=item_id,
                video_url=build_video_url(item_id),
                raw_data={
                    "platform": PLATFORM,
                    "tenant_id": tenant_id,
                    "hot_source": "seed_user_dom",
                    "seed_user_id": seed_user_id,
                    "huoshan_reflow_url": build_reflow_url(item_id),
                },
            )
        )
        if len(results) >= limit:
            break
    return results


def _pick_cover(aweme: dict[str, Any]) -> str | None:
    video = aweme.get("video") or {}
    cover = video.get("cover") or video.get("origin_cover") or {}
    if isinstance(cover, dict):
        urls = cover.get("url_list") or []
        if urls and isinstance(urls[0], str):
            return urls[0]
    return None


def _pick_avatar(author: dict[str, Any]) -> str | None:
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        avatar = author.get(key) or {}
        if isinstance(avatar, dict):
            urls = avatar.get("url_list") or []
            if urls and isinstance(urls[0], str):
                return urls[0]
    return None
