from __future__ import annotations

import re

from app.platforms.huoshan.constants import ITEM_ID_PATTERN, REFLOW_URL, WEB_VIDEO_URL


def extract_item_id(url_or_path: str) -> str:
    text = (url_or_path or "").strip()
    if not text:
        raise ValueError("火山视频链接不能为空")
    if text.isdigit() and len(text) >= 8:
        return text
    match = ITEM_ID_PATTERN.search(text)
    if match:
        return match.group(1)
    raise ValueError(
        "无法解析火山/抖音视频 ID，请提供 item_id、"
        "share.huoshan.com 分享链接或 douyin.com/video 链接"
    )


def build_video_url(item_id: str, *, prefer_reflow: bool = False) -> str:
    if prefer_reflow:
        return REFLOW_URL.format(item_id=item_id)
    return WEB_VIDEO_URL.format(item_id=item_id)


def build_reflow_url(item_id: str) -> str:
    return REFLOW_URL.format(item_id=item_id)


def normalize_video_url(url: str) -> str:
    item_id = extract_item_id(url)
    return build_video_url(item_id)


def is_huoshan_share_url(url: str) -> bool:
    return bool(re.search(r"share\.huoshan\.com|huoshan\.com/hotsoon|api\.huoshan\.com/hotsoon", url or ""))
