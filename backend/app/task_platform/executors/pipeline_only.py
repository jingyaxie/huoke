from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from app.task_platform.executors.base import TaskContext, TaskExecutor, TaskResult, ValidationResult
from app.task_platform.invokers.pipeline_invoker import PipelineInvoker
from app.task_platform.schemas.instance import LeadCrawlTaskSpec
from app.task_platform.schemas.template import TaskTemplateOut


def _update_overall_progress(progress: dict[str, Any]) -> dict[str, Any]:
    crawl = progress.get("crawl") if isinstance(progress.get("crawl"), dict) else {}
    done = int(crawl.get("done") or 0)
    total = int(crawl.get("total") or 0)
    percent = int(min(100, round(done * 100 / total))) if total > 0 else 0
    progress["overall_percent"] = percent
    return progress


class PipelineOnlyExecutor:
    """lead-crawl：Pipeline 分批抓取。"""

    executor_id = "pipeline_only"
    supported_templates = ("lead-crawl",)

    async def validate_spec(self, spec: dict[str, Any], template: TaskTemplateOut) -> ValidationResult:
        try:
            parsed = LeadCrawlTaskSpec.model_validate(spec)
        except ValidationError as exc:
            return ValidationResult(ok=False, error=str(exc))
        if template.template_id not in self.supported_templates:
            return ValidationResult(ok=False, error=f"executor {self.executor_id} 不支持模板 {template.template_id}")
        if template.platforms and parsed.platform not in template.platforms:
            return ValidationResult(ok=False, error=f"平台 {parsed.platform} 不在模板支持范围")
        return ValidationResult(ok=True, spec=parsed.model_dump(mode="json"))

    async def execute(self, ctx: TaskContext) -> TaskResult:
        try:
            spec = LeadCrawlTaskSpec.model_validate(ctx.instance.spec)
        except ValidationError as exc:
            return TaskResult(status="failed", error=str(exc))

        invoker = PipelineInvoker()
        target = spec.crawl.target_leads
        batch_size = spec.crawl.video_limit_per_batch
        max_batches = spec.crawl.max_batches

        ctx.instance.current_phase = "crawl"
        progress = dict(ctx.instance.progress or {})
        crawl_progress = {
            "done": int((progress.get("crawl") or {}).get("done") or 0),
            "total": target,
            "batches": 0,
        }
        progress["crawl"] = crawl_progress
        ctx.instance.progress = _update_overall_progress(progress)

        batches: list[dict[str, Any]] = []
        collected = crawl_progress["done"]
        batch_index = 0

        while collected < target and batch_index < max_batches:
            if ctx.cancel_requested:
                return TaskResult(status="cancelled", result={"batches": batches, "collected": collected})

            batch_index += 1
            try:
                batch_result = await invoker.run_batch(
                    ctx,
                    spec=spec,
                    video_limit=batch_size,
                    batch_index=batch_index,
                )
            except Exception as exc:
                return TaskResult(
                    status="failed",
                    error=str(exc),
                    result={"batches": batches, "collected": collected},
                )

            leads_in_batch = int(batch_result.get("leads_in_batch") or 0)
            collected += leads_in_batch
            batches.append(
                {
                    "batch": batch_index,
                    "status": batch_result.get("status"),
                    "leads_in_batch": leads_in_batch,
                }
            )

            crawl_progress["done"] = min(collected, target)
            crawl_progress["batches"] = batch_index
            progress["crawl"] = crawl_progress
            ctx.instance.progress = _update_overall_progress(progress)

            if batch_result.get("status") not in {"completed", "partial"}:
                return TaskResult(
                    status="failed",
                    error=f"第 {batch_index} 批 Pipeline 失败",
                    result={"batches": batches, "last_batch": batch_result, "collected": collected},
                )

            if leads_in_batch <= 0:
                break

            await asyncio.sleep(1)

        ctx.instance.current_phase = "finalize"
        final = {
            "template_id": ctx.template.template_id,
            "keyword": spec.keyword,
            "platform": spec.platform,
            "target_leads": target,
            "collected_leads": min(collected, target),
            "batches_run": batch_index,
            "batches": batches,
        }
        return TaskResult(status="completed", result=final)
