from __future__ import annotations

from typing import Any

from app.task_platform.registry.adapter_registry import TaskAdapterRegistry

ADAPTER_ID = "yingxiaoyi-lead-v1"

# 盈小蚁「创建任务」表单 → canonical spec 路径
FIELD_MAP: dict[str, str] = {
    "task_name": "task_name",
    "name": "task_name",
    "region": "region",
    "account_id": "account_id",
    "platform": "platform",
    "channel": "platform",
    "keyword": "keyword",
    "product_keyword": "keyword",
    "keywords": "keyword",
    "video_publish_days": "crawl.video_publish_days",
    "video_time": "crawl.video_publish_days",
    "comment_days": "crawl.comment_days",
    "comment_collect_days": "crawl.comment_days",
    "target_count": "crawl.target_leads",
    "target_leads": "crawl.target_leads",
    "crawl_quantity": "crawl.target_leads",
    "interval_min": "action_policy.interval_min_sec",
    "interval_max": "action_policy.interval_max_sec",
    "comment_ratio": "action_policy.comment_ratio",
    "dm_ratio": "action_policy.dm_ratio",
    "daily_follow_limit": "daily_limits.max_follows",
    "daily_dm_limit": "daily_limits.max_dms",
}

PLATFORM_ALIASES = {
    "douyin": "douyin",
    "抖音": "douyin",
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "小红书": "xiaohongshu",
}

VIDEO_TIME_ENUM = {
    "不限": None,
    "unlimited": None,
    None: None,
    0: None,
    "1": 1,
    "1天": 1,
    "1天内": 1,
    "3": 3,
    "3天": 3,
    "3天内": 3,
    "7": 7,
    "1周": 7,
    "1周内": 7,
    "180": 180,
    "半年": 180,
    "半年内": 180,
}


def _set_nested(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _normalize_platform(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return PLATFORM_ALIASES.get(text) or PLATFORM_ALIASES.get(str(value).strip())


def _normalize_video_days(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if value in VIDEO_TIME_ENUM:
        return VIDEO_TIME_ENUM[value]
    if isinstance(value, str):
        key = value.strip()
        if key in VIDEO_TIME_ENUM:
            return VIDEO_TIME_ENUM[key]
    try:
        num = int(value)
        return num if num > 0 else None
    except (TypeError, ValueError):
        return None


def _normalize_comment_days(value: Any) -> int | None:
    if value is None or value == "" or str(value).strip() in {"不限", "unlimited"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_outreach_fields(spec: dict[str, Any]) -> bool:
    if spec.get("action_policy") or spec.get("daily_limits"):
        return True
    return False


class YingxiaoyiLeadV1Adapter:
    adapter_id = ADAPTER_ID
    template_id = "lead-crawl"

    def compile_payload(self, raw: dict[str, Any], *, intent: str | None = None) -> dict[str, Any]:
        spec: dict[str, Any] = {}
        unmapped: list[str] = []
        mapped_keys: set[str] = set()

        for key, value in raw.items():
            if key in {"webhook_url", "external_ref", "external_id", "task_id"}:
                continue
            path = FIELD_MAP.get(key)
            if path is None:
                unmapped.append(key)
                continue
            mapped_keys.add(key)
            if path == "platform":
                value = _normalize_platform(value)
            elif path == "crawl.video_publish_days":
                value = _normalize_video_days(value)
            elif path == "crawl.comment_days":
                value = _normalize_comment_days(value)
            if value is not None and value != "":
                _set_nested(spec, path, value)

        keyword = spec.get("keyword") or raw.get("keyword") or raw.get("product_keyword")
        if keyword and "keyword" not in spec:
            spec["keyword"] = str(keyword).strip()

        platform = spec.get("platform") or _normalize_platform(raw.get("platform") or raw.get("channel"))
        if platform:
            spec["platform"] = platform
        elif "douyin" not in spec:
            spec.setdefault("platform", "douyin")

        crawl = spec.get("crawl")
        if not isinstance(crawl, dict):
            crawl = {}
            spec["crawl"] = crawl
        crawl.setdefault("comment_days", 3)
        crawl.setdefault("target_leads", 100)

        template_id = self.template_id
        if intent == "lead_acquisition" or _has_outreach_fields(spec):
            template_id = "lead-acquisition"

        confidence = 0.55
        if spec.get("keyword"):
            confidence += 0.25
        if spec.get("platform"):
            confidence += 0.1
        if mapped_keys:
            confidence += min(0.1, len(mapped_keys) * 0.02)
        confidence = min(1.0, confidence)

        return {
            "template_id": template_id,
            "spec": spec,
            "confidence": confidence,
            "unmapped_fields": unmapped,
            "reasoning": f"规则映射 adapter={ADAPTER_ID}，命中字段 {len(mapped_keys)} 个",
        }


def register_yingxiaoyi_adapter() -> None:
    TaskAdapterRegistry.register(YingxiaoyiLeadV1Adapter())
