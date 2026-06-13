from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from app.core.antibot import headless_for_platform
from app.services.agent_browser_session import AgentSessionManager
from app.task_platform.executors.base import TaskContext, TaskResult, ValidationResult
from app.task_platform.executors.pipeline_only import _update_overall_progress
from app.task_platform.invokers.pipeline_invoker import PipelineInvoker
from app.task_platform.schemas.instance import LeadAcquisitionTaskSpec
from app.task_platform.schemas.template import TaskTemplateOut
from app.task_platform.services.lead_normalize_service import match_leads, pipeline_batch_to_leads
from app.task_platform.services.lead_outreach_service import LeadOutreachService
from app.services.social_roam.types import _default_comment_match


def _save_checkpoint(ctx: TaskContext, **fields: Any) -> None:
    result = dict(ctx.instance.result or {})
    checkpoint = dict(result.get("checkpoint") or {})
    checkpoint.update(fields)
    result["checkpoint"] = checkpoint
    ctx.instance.result = result


def _load_checkpoint(ctx: TaskContext) -> dict[str, Any] | None:
    if not bool((ctx.instance.spec or {}).get("_resume")):
        return None
    result = ctx.instance.result if isinstance(ctx.instance.result, dict) else {}
    checkpoint = result.get("checkpoint")
    return dict(checkpoint) if isinstance(checkpoint, dict) and checkpoint else None


def _failure_result(ctx: TaskContext, *, error: str, extra: dict[str, Any] | None = None) -> TaskResult:
    payload = dict(extra or {})
    result = dict(ctx.instance.result or {})
    if isinstance(result.get("checkpoint"), dict):
        payload["checkpoint"] = result["checkpoint"]
    return TaskResult(status="failed", error=error, result=payload)


class LeadAcquisitionExecutor:
    """lead-acquisition：Pipeline 分批抓取 → 匹配 → 评论/私信触达。"""

    executor_id = "lead_acquisition"
    supported_templates = ("lead-acquisition",)

    async def validate_spec(self, spec: dict[str, Any], template: TaskTemplateOut) -> ValidationResult:
        try:
            parsed = LeadAcquisitionTaskSpec.model_validate(spec)
        except ValidationError as exc:
            return ValidationResult(ok=False, error=str(exc))
        if template.template_id not in self.supported_templates:
            return ValidationResult(ok=False, error=f"executor {self.executor_id} 不支持模板 {template.template_id}")
        if template.platforms and parsed.platform not in template.platforms:
            return ValidationResult(ok=False, error=f"平台 {parsed.platform} 不在模板支持范围")
        if parsed.action_policy.interval_min_sec > parsed.action_policy.interval_max_sec:
            return ValidationResult(ok=False, error="interval_min_sec 不能大于 interval_max_sec")
        return ValidationResult(ok=True, spec=parsed.model_dump(mode="json"))

    async def execute(self, ctx: TaskContext) -> TaskResult:
        try:
            spec = LeadAcquisitionTaskSpec.model_validate(ctx.instance.spec)
        except ValidationError as exc:
            return TaskResult(status="failed", error=str(exc))

        task_id = ctx.instance.id
        target = spec.crawl.target_leads
        checkpoint = _load_checkpoint(ctx)
        progress = dict(ctx.instance.progress or {})

        matched_leads: list[dict[str, Any]] | None = None
        batches: list[dict[str, Any]] = []
        batch_index = 0
        collected = 0

        if checkpoint and checkpoint.get("phase") in {"match_done", "outreach", "outreach_partial"}:
            matched_leads = list(checkpoint.get("matched_leads") or [])
            batches = list(checkpoint.get("batches") or [])
            batch_index = int(checkpoint.get("batch_index") or 0)
            collected = int(checkpoint.get("collected") or len(matched_leads))
        else:
            invoker = PipelineInvoker()
            batch_size = spec.crawl.video_limit_per_batch
            max_batches = spec.crawl.max_batches

            ctx.instance.current_phase = "crawl"
            crawl_progress = {
                "done": int((progress.get("crawl") or {}).get("done") or 0),
                "total": target,
                "batches": int((progress.get("crawl") or {}).get("batches") or 0),
            }
            if checkpoint and checkpoint.get("phase") == "crawl_partial":
                all_leads = list(checkpoint.get("all_leads") or [])
                batches = list(checkpoint.get("batches") or [])
                batch_index = int(checkpoint.get("batch_index") or 0)
                collected = int(checkpoint.get("collected") or crawl_progress["done"])
                crawl_progress["done"] = min(collected, target)
                crawl_progress["batches"] = batch_index
            else:
                all_leads = []
                collected = crawl_progress["done"]
                batch_index = 0

            progress["crawl"] = crawl_progress
            ctx.instance.progress = _update_overall_progress(progress)

            while collected < target and batch_index < max_batches:
                if ctx.cancel_requested:
                    _save_checkpoint(
                        ctx,
                        phase="crawl_partial",
                        all_leads=all_leads,
                        batches=batches,
                        batch_index=batch_index,
                        collected=collected,
                    )
                    return TaskResult(
                        status="cancelled",
                        result={"batches": batches, "collected": collected, "checkpoint": ctx.instance.result.get("checkpoint")},
                    )

                batch_index += 1
                try:
                    batch_result = await invoker.run_batch(
                        ctx,
                        spec=spec,
                        video_limit=batch_size,
                        batch_index=batch_index,
                    )
                except Exception as exc:
                    _save_checkpoint(
                        ctx,
                        phase="crawl_partial",
                        all_leads=all_leads,
                        batches=batches,
                        batch_index=batch_index,
                        collected=collected,
                    )
                    return _failure_result(
                        ctx,
                        error=str(exc),
                        extra={"batches": batches, "collected": collected},
                    )

                batch_leads = pipeline_batch_to_leads(
                    batch_result,
                    task_id=task_id,
                    keyword=spec.keyword,
                    platform=spec.platform,
                    comment_days=spec.crawl.comment_days,
                )
                all_leads.extend(batch_leads)

                leads_in_batch = int(batch_result.get("leads_in_batch") or len(batch_leads))
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
                _save_checkpoint(
                    ctx,
                    phase="crawl_partial",
                    all_leads=all_leads,
                    batches=batches,
                    batch_index=batch_index,
                    collected=collected,
                )

                if batch_result.get("status") not in {"completed", "partial"}:
                    return _failure_result(
                        ctx,
                        error=f"第 {batch_index} 批 Pipeline 失败",
                        extra={"batches": batches, "last_batch": batch_result, "collected": collected},
                    )

                if leads_in_batch <= 0:
                    break

                await asyncio.sleep(1)

            ctx.instance.current_phase = "normalize"
            comment_match = spec.comment_match or _default_comment_match()
            matched_leads = match_leads(all_leads, comment_match=comment_match)
            matched_leads = matched_leads[:target]
            _save_checkpoint(
                ctx,
                phase="match_done",
                matched_leads=matched_leads,
                batches=batches,
                batch_index=batch_index,
                collected=min(collected, target),
            )

        assert matched_leads is not None

        ctx.instance.current_phase = "outreach"
        outreach_progress = dict(progress.get("outreach") or {})
        outreach_progress.setdefault("matched", len(matched_leads))
        outreach_progress.setdefault("replies", 0)
        outreach_progress.setdefault("dms", 0)
        progress["outreach"] = outreach_progress
        ctx.instance.progress = _update_overall_progress(progress)
        _save_checkpoint(
            ctx,
            phase="outreach",
            matched_leads=matched_leads,
            batches=batches,
            batch_index=batch_index,
            collected=min(collected, target) if collected else len(matched_leads),
        )

        outreach_result: dict[str, Any] = {"status": "skipped", "stats": {}}
        if matched_leads:
            browser_headless = headless_for_platform(ctx.settings, spec.platform, spec.headless)
            manager = AgentSessionManager.get_instance()
            session = await manager.create(
                ctx.tenant_id,
                spec.platform,
                ctx.settings,
                account_id=spec.account_id,
                headless=browser_headless,
                auto_start=False,
            )
            try:
                outreach_service = LeadOutreachService(
                    ctx.settings,
                    tenant_id=ctx.tenant_id,
                    session=session,
                    db_session=ctx.db_session,
                )
                outreach_result = await outreach_service.run(
                    matched_leads,
                    spec,
                    task_id=task_id,
                )
            finally:
                await manager.close(session.session_id)

        outreach_stats = outreach_result.get("stats") if isinstance(outreach_result.get("stats"), dict) else {}
        outreach_progress.update(
            {
                "replies": int(outreach_stats.get("replies") or 0),
                "dms": int(outreach_stats.get("dms") or 0),
                "skipped": int(outreach_stats.get("skipped") or 0),
            }
        )
        progress["outreach"] = outreach_progress
        ctx.instance.progress = _update_overall_progress(progress)

        ctx.instance.current_phase = "finalize"
        spec_data = dict(ctx.instance.spec or {})
        spec_data.pop("_resume", None)
        ctx.instance.spec = spec_data

        final = {
            "template_id": ctx.template.template_id,
            "keyword": spec.keyword,
            "platform": spec.platform,
            "target_leads": target,
            "collected_leads": min(collected, target) if collected else len(matched_leads),
            "matched_leads": len(matched_leads),
            "batches_run": batch_index,
            "batches": batches,
            "outreach": outreach_result,
            "checkpoint": {
                "phase": "match_done",
                "matched_leads": matched_leads,
                "batches": batches,
                "batch_index": batch_index,
                "collected": min(collected, target) if collected else len(matched_leads),
            },
        }
        ctx.instance.result = final
        return TaskResult(status="completed", result=final)
