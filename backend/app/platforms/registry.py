from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.platforms.types import normalize_platform
from app.platforms.xiaohongshu.comments import XhsCommentCrawler
from app.platforms.xiaohongshu.crawler import XhsCrawler
from app.platforms.xiaohongshu.session import XhsSessionStore


def get_session_store(settings: Settings, platform: str) -> PlatformSessionStore:
    platform = normalize_platform(platform)
    if platform == "douyin":
        return DouyinSessionStore(settings)
    if platform == "xiaohongshu":
        return XhsSessionStore(settings)
    raise ValueError(f"平台 {platform} 尚未实现 SessionStore")


def get_hot_crawler(settings: Settings, platform: str, tenant_id: str):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        return DouyinCrawler(settings, tenant_id, store)
    if platform == "xiaohongshu":
        return XhsCrawler(settings, tenant_id, store)
    raise ValueError(f"平台 {platform} 尚未实现热榜爬虫")


def get_comment_crawler(settings: Settings, platform: str, tenant_id: str):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.comments import DouyinCommentCrawler

        return DouyinCommentCrawler(settings, tenant_id, store)
    if platform == "xiaohongshu":
        return XhsCommentCrawler(settings, tenant_id, store)
    raise ValueError(f"平台 {platform} 尚未实现评论爬虫")


def list_platforms() -> list[dict]:
    return [
        {
            "id": "douyin",
            "name": "抖音",
            "capabilities": ["hot", "comments", "login", "keyword_search"],
        },
        {
            "id": "xiaohongshu",
            "name": "小红书",
            "capabilities": ["hot", "comments", "login", "keyword_search"],
        },
    ]
