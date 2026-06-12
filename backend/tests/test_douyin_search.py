from __future__ import annotations

import inspect

from app.core.config import Settings
from app.platforms.douyin.search import DouyinSearchTool
from app.platforms.douyin.session import DouyinSessionStore


def test_record_search_nil_accepts_empty_hints_dict():
    hints: dict[str, str] = {}
    data = {
        "search_nil_info": {
            "search_nil_type": "verify_check",
            "search_nil_item": "verify_check",
        }
    }
    DouyinSearchTool._record_search_nil(data, hints)
    assert hints.get("nil_type") == "verify_check"
    assert "verify_check" in (hints.get("diagnostic") or "")


def test_search_nil_verify_check_diagnostic():
    data = {
        "status_code": 0,
        "data": [],
        "search_nil_info": {
            "search_nil_type": "verify_check",
            "search_nil_item": "verify_check",
            "text_type": 9,
        },
    }
    msg = DouyinSearchTool._search_nil_diagnostic(data)
    assert msg is not None
    assert "verify_check" in msg
    assert "VNC" in msg


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
        "search_hints",
    ]
    raw = DouyinSearchTool.__dict__["_search_videos_via_thin_nav"]
    assert not isinstance(raw, staticmethod)

    tool = DouyinSearchTool(Settings(), "default", DouyinSessionStore(Settings()))
    bound = tool._search_videos_via_thin_nav
    assert getattr(bound, "__self__", None) is tool
