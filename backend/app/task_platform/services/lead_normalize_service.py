from __future__ import annotations

from typing import Any

from app.platforms.search_filters import within_days
from app.services.social_roam.matcher import match_spec, resolve_follow_match
from app.services.social_roam.normalizer import normalize_crawl_results
from app.services.social_roam.types import _default_comment_match


def _raw_results_from_batch(batch_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 Pipeline 批次响应中提取原始 crawl results。"""
    rows: list[dict[str, Any]] = []
    for platform_item in batch_payload.get("platforms") or []:
        if not isinstance(platform_item, dict):
            continue
        inner = platform_item.get("result") if isinstance(platform_item.get("result"), dict) else {}
        builtin_results = inner.get("results")
        if isinstance(builtin_results, list) and builtin_results:
            rows.extend(item for item in builtin_results if isinstance(item, dict))
            continue
        for block in inner.get("comments_by_video") or []:
            if not isinstance(block, dict):
                continue
            note_id = str(block.get("note_id") or block.get("content_id") or "")
            note_url = str(block.get("note_url") or block.get("content_url") or "")
            comments = block.get("comments") or []
            if not comments:
                continue
            rows.append(
                {
                    "aweme_id": note_id,
                    "content_id": note_id,
                    "video_url": note_url,
                    "note_url": note_url,
                    "comments": [
                        {
                            "comment_id": c.get("comment_id"),
                            "comment": c.get("text") or c.get("comment"),
                            "nickname": c.get("username") or c.get("nickname"),
                            "user_id": c.get("user_id"),
                            "sec_uid": c.get("sec_uid"),
                            "create_time": c.get("create_time"),
                        }
                        for c in comments
                        if isinstance(c, dict)
                    ],
                }
            )
    return rows


def pipeline_batch_to_leads(
    batch_payload: dict[str, Any],
    *,
    task_id: str,
    keyword: str,
    platform: str,
    comment_days: int | None,
) -> list[dict[str, Any]]:
    raw = _raw_results_from_batch(batch_payload)
    leads = normalize_crawl_results(raw, task_id=task_id, keyword=keyword, platform=platform)
    if comment_days and comment_days > 0:
        leads = [
            lead
            for lead in leads
            if within_days(lead.get("comment", {}).get("create_time"), comment_days)
        ]
    return leads


def match_leads(
    leads: list[dict[str, Any]],
    *,
    comment_match: dict[str, Any] | None,
    follow_match: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    spec = comment_match or _default_comment_match()
    matched: list[dict[str, Any]] = []
    for lead in leads:
        comment_text = str(lead.get("comment", {}).get("text") or "")
        reply_ok, reply_reason = match_spec(comment_text, spec)
        follow_ok, follow_reason = resolve_follow_match(comment_text, spec, follow_match)
        lead["matched"] = reply_ok or follow_ok
        lead["match_reason"] = reply_reason if reply_ok else follow_reason
        lead["reply_match"] = reply_ok
        lead["follow_match"] = follow_ok
        if lead["matched"]:
            matched.append(lead)
    return matched
