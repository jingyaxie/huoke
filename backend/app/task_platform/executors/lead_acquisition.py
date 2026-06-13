from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError

from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager
from app.task_platform.executors.base import TaskContext, TaskResult, ValidationResult
from app.task_platform.executors.pipeline_only import _update_overall_progress
from app.task_platform.invokers.pipeline_invoker import PipelineInvoker
from app.task_platform.schemas.instance import LeadAcquisitionTaskSpec
from app.task_platform.schemas.template import TaskTemplateOut
from app.task_platform.services.lead_normalize_service import match_leads, pipeline_batch_to_leads
from app.task_platform.services.lead_outreach_service import LeadOutreachService
from app.services.social_roam.types import _default_comment_match


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

        task_id = ctx.instance.task_id
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
        all_leads: list[dict[str, Any]] = []
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

            if batch_result.get("status") not in {"completed", "partial"}:
                return TaskResult(
                    status="failed",
                    error=f"第 {batch_index} 批 Pipeline 失败",
                    result={"batches": batches, "last_batch": batch_result, "collected": collected},
                )

            if leads_in_batch <= 0:
                break

            await asyncio.sleep(1)

        ctx.instance.current_phase = "normalize"
        comment_match = spec.comment_match or _default_comment_match()
        matched_leads = match_leads(all_leads, comment_match=comment_match)
        matched_leads = matched_leads[:target]

        ctx.instance.current_phase = "outreach"
        outreach_progress = {"matched": len(matched_leads), "replies": 0, "dms": 0}
        progress["outreach"] = outreach_progress
        ctx.instance.progress = _update_overall_progress(progress)

        outreach_result: dict[str, Any] = {"status": "skipped", "stats": {}}
        if matched_leads:
            manager = AgentSessionManager.get_instance()
            session = await manager.create(
                ctx.tenant_id,
                spec.platform,
                ctx.settings,
                account_id=spec.account_id,
                headless=True,
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
        final = {
            "template_id": ctx.template.template_id,
            "keyword": spec.keyword,
            "platform": spec.platform,
            "target_leads": target,
            "collected_leads": min(collected, target),
            "matched_leads": len(matched_leads),
            "batches_run": batch_index,
            "batches": batches,
            "outreach": outreach_result,
        }
        return TaskResult(status="completed", result=final)
