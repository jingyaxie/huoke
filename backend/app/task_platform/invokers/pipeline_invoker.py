from __future__ import annotations

from typing import Any

from app.schemas.open_pipeline import KeywordVideoCommentsRequest
from app.services.open_pipeline_service import OpenPipelineService
from app.task_platform.executors.base import TaskContext
from app.task_platform.schemas.instance import LeadCrawlTaskSpec


def _count_leads_from_pipeline(result: dict[str, Any]) -> int:
    total = 0
    for item in result.get("platforms") or []:
        if not isinstance(item, dict):
            continue
        inner = item.get("result") if isinstance(item.get("result"), dict) else item
        comments = inner.get("comments") if isinstance(inner, dict) else None
        if isinstance(comments, list):
            total += len(comments)
            continue
        summary = str(item.get("summary") or "")
        if "评论" in summary:
            digits = "".join(ch if ch.isdigit() else " " for ch in summary).split()
            if digits:
                try:
                    total += int(digits[0])
                except ValueError:
                    pass
    return total


class PipelineInvoker:
    capability_id = "pipeline_keyword_comments"

    async def run_batch(
        self,
        ctx: TaskContext,
        *,
        spec: LeadCrawlTaskSpec,
        video_limit: int,
        batch_index: int,
    ) -> dict[str, Any]:
        comment_days = spec.crawl.comment_days or 3
        req = KeywordVideoCommentsRequest(
            keyword=spec.keyword,
            platforms=[spec.platform],  # type: ignore[list-item]
            video_limit=video_limit,
            days=comment_days,
            video_publish_days=spec.crawl.video_publish_days,
            region=spec.region,
            provider=spec.provider,
            timeout_seconds=spec.timeout_seconds,
            headless=spec.headless,
            force_refresh=spec.crawl.force_refresh and batch_index == 0,
            async_job=False,
        )
        service = OpenPipelineService(ctx.settings, ctx.tenant_id, db_session=ctx.db_session)
        response = await service.run_keyword_video_comments(req, account_id=spec.account_id)
        payload = response.model_dump(mode="json")
        payload["leads_in_batch"] = _count_leads_from_pipeline(payload)
        return payload
