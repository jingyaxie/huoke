from __future__ import annotations

import re
from typing import Any

from app.platforms.douyin.js_constants import _SEARCH_API_EXCLUDES, _SEARCH_RESULT_API_MARKERS


def is_search_result_api(url: str) -> bool:
    if not url or "douyin.com/aweme/v1/web/" not in url:
        return False
    if any(marker in url for marker in _SEARCH_API_EXCLUDES):
        return False
    return any(marker in url for marker in _SEARCH_RESULT_API_MARKERS)


def search_nil_type(data: dict) -> str | None:
    nil = data.get("search_nil_info")
    if not isinstance(nil, dict):
        return None
    return str(nil.get("search_nil_type") or nil.get("search_nil_item") or "").strip() or None


def normalize_search_aweme(node: dict) -> dict | None:
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
        "create_time": aweme.get("create_time"),
    }


def extract_aweme_items_from_json(data: Any) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "aweme_info" in node or (
                "aweme_id" in node and ("desc" in node or "author" in node)
            ):
                row = normalize_search_aweme(node)
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


def rank_search_items(items: list[dict], keyword: str) -> list[dict]:
    tokens = [token for token in re.split(r"\s+", keyword.strip()) if token]
    if not tokens:
        return items

    def score(row: dict) -> int:
        title = (row.get("title") or "").lower()
        if not title:
            return 0
        return sum(2 if token in title else 0 for token in tokens)

    ranked = sorted(items, key=lambda row: (score(row), row.get("digg_count") or 0), reverse=True)
    matched = [row for row in ranked if any(token in (row.get("title") or "").lower() for token in tokens)]
    return matched or ranked
