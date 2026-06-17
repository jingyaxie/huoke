"""按计划驱动模拟 Supervisor 执行（dry-run，不调用真实 Skill/浏览器）。"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.agent_strategy import resolve_agent_strategy
from app.services.external_task_service import enrich_brief_from_external_config, normalize_external_create
from app.services.task_brief_service import TaskBrief
from app.services.task_config_update_service import update_task_config
from app.services.task_execution_plan import (
    build_supervisor_execution_plan,
    ensure_supervisor_execution_plan,
    plan_driven_supervisor_decision,
)
from app.services.task_round_service import (
    complete_current_round,
    effective_target_leads,
    round_loop_enabled,
    start_next_round,
)
from app.services.task_supervisor_service import TaskSupervisorService


@dataclass
class SimulationStep:
    cycle: int
    action: str
    params: dict[str, Any]
    plan_step_id: str | None = None


@dataclass
class SimulationResult:
    trace: list[SimulationStep] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    terminal: str | None = None
    completion_outcome: str | None = None

    @property
    def actions(self) -> list[str]:
        return [row.action for row in self.trace]


async def build_brief_from_external_payload(
    payload: dict[str, Any],
    *,
    settings: Settings,
    tenant_id: str = "default",
    provider: str = "deepseek",
) -> tuple[TaskBrief, dict[str, Any]]:
    """镜像 submit_async 中的 brief 构建链路。"""
    request = ExternalTaskCreateRequest.model_validate(payload)
    message, config, _correlation = normalize_external_create(request)
    brief = TaskBrief(
        brief_md=message,
        platform=str(request.platform or "douyin"),
        title=request.name,
        keyword=config.get("keyword"),
        region=config.get("region"),
        agent_strategy=request.agent_strategy,
    )
    brief, _meta = await update_task_config(
        brief,
        config=config,
        settings=settings,
        tenant_id=tenant_id,
        provider=provider,
    )
    brief = enrich_brief_from_external_config(brief, config)
    strategy = resolve_agent_strategy(brief.agent_strategy, platform=brief.platform or request.platform)
    brief.goals["execution_mode"] = strategy.execution_mode
    brief.agent_strategy = strategy.id
    return brief, config


def mock_interaction_stats(
    brief: TaskBrief,
    *,
    reply_used: int = 0,
    dm_used: int = 0,
    follow_used: int = 0,
) -> dict[str, Any]:
    constraints = brief.constraints if isinstance(brief.constraints, dict) else {}
    reply_limit = int(constraints.get("daily_reply_limit") or constraints.get("follow_per_day") or 30)
    dm_limit = int(constraints.get("daily_dm_limit") or constraints.get("dm_per_day") or 30)
    follow_limit = int(constraints.get("daily_follow_limit") or constraints.get("follow_per_day") or 30)

    def bucket(used: int, limit: int) -> dict[str, Any]:
        return {"count": used, "limit": limit, "can_do": used < limit}

    return {
        "reply": bucket(reply_used, reply_limit),
        "dm": bucket(dm_used, dm_limit),
        "follow": bucket(follow_used, follow_limit),
    }


def mock_skill_result(
    action: str,
    brief: TaskBrief,
    state: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    target = effective_target_leads(brief, state) or int(brief.goals.get("target_leads") or 0)
    if action == "crawl_keyword":
        return {
            "status": "completed",
            "total_comments_captured": 20,
            "videos_processed": 3,
            "comments_persisted": 20,
            "keyword": brief.keyword,
        }
    if action == "crawl_content_url":
        return {
            "status": "completed",
            "total_comments_captured": 12,
            "videos_processed": 1,
            "video_url": state.get("_last_video_url") or brief.goals.get("video_url"),
        }
    if action == "crawl_profile":
        return {
            "status": "completed",
            "total_comments_captured": 18,
            "videos_processed": int(brief.goals.get("crawl_video_limit") or 5),
            "profile_url": brief.goals.get("profile_url"),
        }
    if action == "evaluate_leads":
        return {
            "status": "completed",
            "evaluated": 20,
            "qualified": max(target, 3),
            "summary": f"评估完成，{max(target, 3)} 条符合标准",
        }
    if action == "query_stats":
        return {"status": "completed", "result": stats}
    if action in {"reply", "dm", "follow"}:
        remaining = target - int(state.get("leads_collected") or 0)
        batch = min(3, max(remaining, 1))
        return {
            "status": "completed",
            "summary": f"模拟触达 {action}",
            "inline_outreach": {"ok": batch},
        }
    return {"status": "completed"}


def simulate_planned_execution(
    *,
    settings: Settings,
    brief: TaskBrief,
    plan: dict[str, Any] | None = None,
    tenant_id: str = "default",
    account_id: str = "default",
    max_cycles: int = 120,
    simulate_until: set[str] | None = None,
    run_to_completion: bool = True,
) -> SimulationResult:
    """按 execution_plan 逐步决策并 dry-run 更新状态。"""
    platform = str(brief.platform or "douyin")
    svc = TaskSupervisorService(settings, tenant_id, platform, account_id)
    execution_plan = copy.deepcopy(plan or build_supervisor_execution_plan(brief, {}))
    state: dict[str, Any] = {
        "execution_plan": execution_plan,
        "job_id": "sim-job",
    }
    stats = mock_interaction_stats(brief)
    trace: list[SimulationStep] = []
    terminal: str | None = None
    completion_outcome: str | None = None
    seen: set[str] = set()

    for cycle in range(1, max_cycles + 1):
        live_stats = state.get("last_stats") if isinstance(state.get("last_stats"), dict) else stats
        decision = plan_driven_supervisor_decision(
            state["execution_plan"],
            brief,
            state,
            stats=live_stats,
        )
        if not decision:
            terminal = "no_decision"
            break

        action = str(decision.get("action") or "")
        params = dict(decision.get("params") or {})
        trace.append(
            SimulationStep(
                cycle=cycle,
                action=action,
                params=params,
                plan_step_id=decision.get("plan_step_id"),
            )
        )
        seen.add(action)

        if simulate_until and simulate_until.issubset(seen):
            terminal = "partial"
            break

        if action == "complete":
            terminal = "complete"
            completion_outcome = str(decision.get("completion_outcome") or "")
            break
        if action == "suspend":
            terminal = "suspend"
            completion_outcome = str(decision.get("completion_outcome") or "")
            break

        if action == "crawl_content_url":
            state["_last_video_url"] = params.get("video_url")

        skill_result = mock_skill_result(action, brief, state, stats)
        ok = not skill_result.get("error") and str(skill_result.get("status", "")).lower() != "failed"
        svc._update_state(
            state,
            action,
            skill_result,
            brief,
            dry_run=True,
            params=params,
        )
        if action in {"crawl_keyword", "crawl_content_url", "crawl_profile"} and ok:
            state["crawl_done"] = True
        if action == "evaluate_leads":
            target = effective_target_leads(brief, state) or int(brief.goals.get("target_leads") or 0)
            state["leads_qualified"] = max(target, 3)
        if action in {"reply", "dm", "follow"} and ok:
            batch = 1
            inline = skill_result.get("inline_outreach")
            if isinstance(inline, dict):
                batch = int(inline.get("ok") or 1)
            from app.services.task_supervisor_service import _add_leads_to_state

            _add_leads_to_state(brief, state, max(batch - 1, 0))

        if svc._goal_reached(brief, state):
            if round_loop_enabled(brief):
                complete_current_round(brief, state)
                if start_next_round(brief, state):
                    state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)
                    continue
                terminal = "complete"
                completion_outcome = "max_rounds_reached"
                break
            terminal = "complete"
            completion_outcome = "goal_reached"
            break

        if not run_to_completion and simulate_until is None:
            terminal = "single_step"
            break
    else:
        terminal = "max_cycles"

    return SimulationResult(
        trace=trace,
        state=state,
        terminal=terminal,
        completion_outcome=completion_outcome,
    )
