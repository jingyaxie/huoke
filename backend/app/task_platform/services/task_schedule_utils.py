from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_scheduled_at(value: Any) -> datetime | None:
    """解析 ISO8601 / Unix 时间戳为 UTC naive datetime。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_initial_task_status(scheduled_at: datetime | None, *, now: datetime | None = None) -> str:
    """未来 scheduled_at → scheduled；否则 queued。"""
    if scheduled_at is None:
        return "queued"
    current = now or utc_now_naive()
    if scheduled_at > current:
        return "scheduled"
    return "queued"
