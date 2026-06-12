from __future__ import annotations

import inspect

from app.core.config import Settings
from app.platforms.douyin.search import DouyinSearchTool
from app.platforms.douyin.session import DouyinSessionStore


def test_thin_nav_search_is_instance_method():
    """Regression: @staticmethod on _search_videos_via_thin_nav broke captured_api_urls binding."""
    sig = inspect.signature(DouyinSearchTool._search_videos_via_thin_nav)
    params = list(sig.parameters.keys())
    assert params == [
        "self",
        "page",
        "filters",
        "limit",
        "api_items",
        "captured_api_urls",
        "template_url",
    ]
    raw = DouyinSearchTool.__dict__["_search_videos_via_thin_nav"]
    assert not isinstance(raw, staticmethod)

    tool = DouyinSearchTool(Settings(), "default", DouyinSessionStore(Settings()))
    bound = tool._search_videos_via_thin_nav
    assert getattr(bound, "__self__", None) is tool
