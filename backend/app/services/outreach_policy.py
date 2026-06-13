from __future__ import annotations

import random
from typing import Any, Literal

OutreachAction = Literal["reply", "dm", "skip"]


def random_interval_sec(interval_min: int, interval_max: int) -> float:
    low = max(1, int(interval_min))
    high = max(low, int(interval_max))
    return random.uniform(float(low), float(high))


def choose_outreach_action(*, comment_ratio: int, dm_ratio: int) -> OutreachAction:
    """按评论/私信比例随机选择触达方式。"""
    comment_ratio = max(0, min(100, int(comment_ratio)))
    dm_ratio = max(0, min(100, int(dm_ratio)))
    total = comment_ratio + dm_ratio
    if total <= 0:
        return "skip"
    roll = random.uniform(0, total)
    if roll < comment_ratio:
        return "reply"
    if roll < comment_ratio + dm_ratio:
        return "dm"
    return "skip"


def remaining_task_quota(
    stats: dict[str, Any],
    *,
    max_replies: int,
    max_follows: int,
    max_dms: int,
) -> dict[str, int]:
    return {
        "replies": max(0, max_replies - int(stats.get("replies") or 0)),
        "follows": max(0, max_follows - int(stats.get("follows") or 0)),
        "dms": max(0, max_dms - int(stats.get("dms") or 0)),
    }


def daily_quota_ok(
    quota_stats: dict[str, Any],
    action: OutreachAction,
) -> bool:
    if action == "reply":
        return bool((quota_stats.get("reply") or {}).get("quota_ok", True))
    if action == "dm":
        return bool((quota_stats.get("dm") or {}).get("quota_ok", True))
    return True
