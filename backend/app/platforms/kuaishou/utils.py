from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from app.platforms.kuaishou.constants import VIDEO_URL_PATTERN


def extract_photo_id(url_or_path: str) -> str:
    match = VIDEO_URL_PATTERN.search(url_or_path)
    if not match:
        raise ValueError(f"无法从快手链接解析 photo_id: {url_or_path}")
    return match.group(1)


def build_video_url(photo_id: str) -> str:
    return f"https://www.kuaishou.com/short-video/{photo_id}"


def build_profile_url(user_id: str) -> str:
    return f"https://www.kuaishou.com/profile/{user_id}"


def build_search_url(keyword: str) -> str:
    return f"https://www.kuaishou.com/search/video?searchKey={quote(keyword.strip())}"


def parse_video_detail(data: dict | None) -> dict[str, str | None]:
    """从 visionVideoDetail GraphQL 响应提取回复所需字段。"""
    detail = (data or {}).get("data", {}).get("visionVideoDetail") if isinstance(data, dict) else None
    if not isinstance(detail, dict):
        detail = data if isinstance(data, dict) else {}
    author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
    photo = detail.get("photo") if isinstance(detail.get("photo"), dict) else {}
    return {
        "photo_author_id": str(author.get("id") or "") or None,
        "photo_author_name": str(author.get("name") or "") or None,
        "exp_tag": str(photo.get("expTag") or "") or None,
        "photo_id": str(photo.get("id") or "") or None,
    }


def find_comment_author_id(comments: list[dict], comment_id: str) -> str | None:
    target = str(comment_id or "").strip()
    if not target:
        return None
    for row in comments:
        if not isinstance(row, dict):
            continue
        if str(row.get("comment_id") or row.get("commentId") or "") == target:
            author_id = row.get("user_id") or row.get("authorId") or row.get("author_id")
            if author_id:
                return str(author_id)
    return None


def normalize_ks_comment(item: dict, parent_comment_id: str | None = None) -> dict:
    return {
        "comment_id": str(item.get("commentId") or item.get("comment_id") or ""),
        "parent_comment_id": parent_comment_id,
        "comment": item.get("content") or item.get("text") or "",
        "create_time": item.get("timestamp") or item.get("create_time"),
        "digg_count": int(item.get("likedCount") or item.get("liked_count") or 0),
        "reply_comment_total": 1 if item.get("hasSubComments") else 0,
        "username": item.get("authorName") or item.get("author_name") or "",
        "user_id": str(item.get("authorId") or item.get("author_id") or ""),
        "sec_uid": "",
        "avatar": item.get("headurl") or item.get("avatar") or "",
    }


def parse_search_feed_item(feed: dict, *, tenant_id: str) -> dict | None:
    if not isinstance(feed, dict):
        return None
    photo = feed.get("photo") or feed
    author = feed.get("author") or {}
    photo_id = str(photo.get("id") or photo.get("photoId") or "")
    if not re.fullmatch(r"[0-9a-zA-Z]{8,32}", photo_id):
        return None
    user_id = str(author.get("id") or "")
    caption = (photo.get("caption") or photo.get("title") or "").strip()
    location = photo.get("location") or feed.get("location") or ""
    create_time = photo.get("timestamp") or photo.get("create_time")
    return {
        "photo_id": photo_id,
        "video_url": build_video_url(photo_id),
        "title": caption[:500] or f"快手视频 {photo_id[:8]}",
        "author": (author.get("name") or "").strip(),
        "author_id": user_id,
        "location": str(location).strip(),
        "create_time": create_time,
        "like_count": int(photo.get("likeCount") or photo.get("realLikeCount") or 0),
        "comment_count": int(photo.get("commentCount") or 0),
        "raw_data": {
            "photo_id": photo_id,
            "author_id": user_id,
            "tenant_id": tenant_id,
            "platform": "kuaishou",
            "feed": feed,
        },
    }


def walk_photo_ids(data: Any) -> list[str]:
    ids: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"photoId", "photo_id", "id"} and isinstance(value, str):
                    if re.fullmatch(r"[0-9a-zA-Z]{8,32}", value) and value.startswith("3x"):
                        ids.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    uniq: list[str] = []
    seen: set[str] = set()
    for photo_id in ids:
        if photo_id in seen:
            continue
        seen.add(photo_id)
        uniq.append(photo_id)
    return uniq
