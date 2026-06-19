from __future__ import annotations

import pytest

from app.platforms.douyin.standalone_keyword_browse import (
    CAPTURE_METHOD,
    StandaloneKeywordBrowseConfig,
    _is_search_list_ready,
    _keyword_matches_comment,
    _match_comment,
    _on_search_results_url,
    _sync_search_aweme_ids_from_api,
    _take_unique_comments,
)


def test_capture_method_constant():
    assert CAPTURE_METHOD == "standalone_keyword_browse"


def test_keyword_matches_comment_uses_search_keyword_by_default():
    config = StandaloneKeywordBrowseConfig(keyword="淋浴房", min_comment_length=2)
    assert _keyword_matches_comment(config, "我家淋浴房漏水怎么办")
    assert not _keyword_matches_comment(config, "招聘销售")


def test_keyword_matches_with_exclude():
    config = StandaloneKeywordBrowseConfig(
        keyword="淋浴房",
        match_keywords=["报价", "多少钱"],
        exclude_keywords=["招聘"],
        min_comment_length=2,
    )
    assert _keyword_matches_comment(config, "淋浴房报价多少")
    assert not _keyword_matches_comment(config, "招聘淋浴房安装工")


def test_action_policy_defaults():
    config = StandaloneKeywordBrowseConfig(keyword="test")
    assert config.action_policy["comment_ratio"] == 50
    assert config.action_policy["dm_ratio"] == 30
    assert config.action_policy["follow_ratio"] == 20
    assert config.reuse_stable_session is True
    assert config.close_browser_after is False


def test_take_unique_comments_dedupes_across_batches():
    seen: set[str] = set()
    batch1 = [{"comment_id": "1", "comment": "a"}, {"comment_id": "2", "comment": "b"}]
    batch2 = [{"comment_id": "1", "comment": "a"}, {"comment_id": "3", "comment": "c"}]
    u1, s1 = _take_unique_comments(batch1, seen)
    u2, s2 = _take_unique_comments(batch2, seen)
    assert [r["comment_id"] for r in u1] == ["1", "2"]
    assert s1 == 0
    assert [r["comment_id"] for r in u2] == ["3"]
    assert s2 == 1


def test_on_search_results_url_accepts_jingxuan_search():
    assert _on_search_results_url("https://www.douyin.com/jingxuan/search/AI%E8%8E%B7%E5%AE%A2?type=general")
    assert not _on_search_results_url("https://www.douyin.com/jingxuan")


def test_sync_search_aweme_ids_from_api():
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    params = parse_ui_flow_params({"keyword": "AI获客", "content_limit": 3}, platform="douyin")
    ctx = DouyinUiSession(
        settings=None,  # type: ignore[arg-type]
        tenant_id="default",
        account_id="default",
        params=params,
        page=None,  # type: ignore[arg-type]
    )
    api_items = {
        "111": {"aweme_id": "111", "title": "AI获客工具", "digg_count": 10},
        "222": {"aweme_id": "222", "title": "其它", "digg_count": 5},
    }
    ids = _sync_search_aweme_ids_from_api(ctx, api_items)
    assert ids[0] == "111"
    assert ctx.state["search_poster_mode"] is True


@pytest.mark.asyncio
async def test_is_search_list_ready_with_api_items():
    class _Page:
        url = "https://www.douyin.com/jingxuan/search/test?type=general"

    assert await _is_search_list_ready(_Page(), {"1": {"aweme_id": "1"}}) is True
    assert await _is_search_list_ready(_Page(), {}) is False


@pytest.mark.asyncio
async def test_is_search_list_ready_with_api_complete_state():
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    class _Page:
        url = "https://www.douyin.com/jingxuan/search/test?type=general"

    params = parse_ui_flow_params({"keyword": "AI获客", "content_limit": 3}, platform="douyin")
    ctx = DouyinUiSession(
        settings=None,  # type: ignore[arg-type]
        tenant_id="default",
        account_id="default",
        params=params,
        page=None,  # type: ignore[arg-type]
    )
    ctx.state["search_api_complete"] = True
    ctx.state["search_api_complete_reason"] = "items=2"
    assert await _is_search_list_ready(_Page(), {}, ctx=ctx) is True
