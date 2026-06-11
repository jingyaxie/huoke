from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.huoshan.comments import HuoshanCommentCrawler
from app.platforms.huoshan.crawler import HuoshanCrawler
from app.platforms.huoshan.session import HuoshanSessionStore
from app.platforms.kuaishou.crawler import KuaishouCrawler
from app.platforms.kuaishou.session import KuaishouSessionStore
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
    if platform == "huoshan":
        return HuoshanSessionStore(settings)
    if platform == "kuaishou":
        return KuaishouSessionStore(settings)
    raise ValueError(f"平台 {platform} 尚未实现 SessionStore")


def get_hot_crawler(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        return DouyinCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        return XhsCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "huoshan":
        return HuoshanCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        return KuaishouCrawler(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现热榜爬虫")


def get_search_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.search import DouyinSearchTool

        return DouyinSearchTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现搜索工具")


def get_comment_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.comment_tool import DouyinCommentTool

        return DouyinCommentTool(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        return XhsCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "huoshan":
        return HuoshanCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        raise ValueError("快手评论抓取尚未实现")
    raise ValueError(f"平台 {platform} 尚未实现评论工具")


def get_follow_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.follow import DouyinFollowTool

        return DouyinFollowTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现关注工具")


def get_dm_tool(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.dm import DouyinDmTool

        return DouyinDmTool(settings, tenant_id, store, account_id=account_id)
    raise ValueError(f"平台 {platform} 尚未实现私信工具")


def get_comment_crawler(settings: Settings, platform: str, tenant_id: str, account_id: str = "default"):
    platform = normalize_platform(platform)
    store = get_session_store(settings, platform)
    if platform == "douyin":
        from app.platforms.douyin.comments import DouyinCommentCrawler

        return DouyinCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "xiaohongshu":
        return XhsCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "huoshan":
        return HuoshanCommentCrawler(settings, tenant_id, store, account_id=account_id)
    if platform == "kuaishou":
        raise ValueError("快手评论抓取尚未实现")
    raise ValueError(f"平台 {platform} 尚未实现评论爬虫")


def list_platforms() -> list[dict]:
    return [
        {
            "id": "douyin",
            "name": "抖音",
            "capabilities": ["hot", "comments", "login", "keyword_search", "follow", "dm"],
        },
        {
            "id": "xiaohongshu",
            "name": "小红书",
            "capabilities": ["hot", "comments", "login", "keyword_search"],
        },
        {
            "id": "kuaishou",
            "name": "快手",
            "capabilities": ["hot", "login", "account_bind"],
        },
        {
            "id": "huoshan",
            "name": "抖音火山版",
            "capabilities": ["hot", "comments", "login", "keyword_search", "seed_user_feed"],
            "deprecated": True,
            "notes": [
                "已弃用，请使用快手(kuaishou)平台",
                "无独立 Web 热榜，可配置 seed 用户(sec_uid) 拉取作品列表",
            ],
        },
    ]
