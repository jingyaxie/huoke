from __future__ import annotations

from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import (
    advance_supervisor_plan,
    build_execution_note,
    build_supervisor_execution_plan,
    guard_supervisor_complete_decision,
    infer_suspend_next_action,
    plan_driven_supervisor_decision,
    reset_supervisor_state_for_manual_retry,
    supervisor_goal_reached,
)


def test_reset_supervisor_state_for_manual_retry_after_crawl_failed():
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 10, "video_limit": 1}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_failures": 1})
    plan["steps"][0]["status"] = "failed"
    state = {
        "suspended": True,
        "resume_at": "2099-01-01T00:00:00+00:00",
        "wake_reason": "抓取失败",
        "crawl_failures": 1,
        "execution_plan": plan,
    }
    reset_supervisor_state_for_manual_retry(state, plan)
    assert not state.get("suspended")
    assert state.get("crawl_failures") == 0
    assert state.get("crawl_done") is None
    assert plan["steps"][0]["status"] == "pending"
    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision.get("action") == "crawl_keyword"
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 10, "video_limit": 1}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    actions = [s["action"] for s in plan["steps"]]
    assert actions == ["crawl_keyword", "query_stats", "complete"]
    assert plan["current_index"] == 0


def test_plan_driven_decide_starts_with_crawl():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    decision = plan_driven_supervisor_decision(plan, brief, {})
    assert decision is not None
    assert decision["action"] == "crawl_keyword"
    assert decision.get("plan_step_id") == "crawl"
    assert decision["params"]["crawl_video_limit"] == 5
    assert decision["params"]["video_limit"] == 5


def test_plan_driven_skips_completed_crawl():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    decision = plan_driven_supervisor_decision(plan, brief, {"crawl_done": True})
    assert decision is not None
    assert decision["action"] == "query_stats"


def test_skill_flow_plan_includes_reply_loop():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 10, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(brief, {})
    actions = [s["action"] for s in plan["steps"]]
    assert actions == ["crawl_keyword", "evaluate_leads", "query_stats", "reply", "dm", "follow", "complete"]
    crawl_params = plan["steps"][0]["params"]
    assert crawl_params["ui_search_only"] is True
    assert crawl_params["search_url_first"] is False
    assert crawl_params["crawl_video_limit"] == 5
    assert plan["steps"][3]["repeat_until"] == "quota_or_no_targets"
    assert plan.get("pipeline") == "skill_flow"


def test_plan_uses_crawl_video_limit_alias():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5, "crawl_video_limit": 9}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    crawl_params = plan["steps"][0]["params"]
    assert crawl_params["crawl_video_limit"] == 9
    assert crawl_params["video_limit"] == 9
    assert "最多 9 个视频" in plan["steps"][0]["label"]


def test_skill_flow_plan_driven_reply_after_stats():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True, "evaluation_done": True, "stats_synced": True})
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True, "evaluation_done": True, "stats_synced": True},
        stats={"reply": {"can_do": True}},
    )
    assert decision is not None
    assert decision["action"] == "reply"
    assert decision.get("plan_step_id") == "reply"


def test_skill_flow_plan_recrawls_when_zero_qualified_leads():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    state = {
        "crawl_done": True,
        "evaluation_done": True,
        "leads_qualified": 0,
        "stats_synced": True,
        "comments_captured": 26,
        "watched_content_ids": ["v1"],
    }
    plan = build_supervisor_execution_plan(brief, state)
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        state,
        stats={"reply": {"can_do": True}},
    )
    assert decision is not None
    assert decision["action"] == "crawl_keyword"
    assert state.get("crawl_done") is None
    assert state.get("evaluation_done") is None


def test_skill_flow_next_day_resume_restarts_with_crawl():
    from datetime import datetime, timedelta, timezone

    from app.services.task_supervisor_service import TaskSupervisorService

    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        constraints={"termination_resume_next_day": True},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(
        brief,
        {"crawl_done": True, "stats_synced": True},
    )
    state = {
        "suspended": True,
        "resume_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "day_index": 1,
        "crawl_done": True,
        "stats_synced": True,
        "last_stats": {"reply": {"can_do": True}},
        "execution_plan": plan,
    }
    TaskSupervisorService._maybe_wake_suspended_state(object.__new__(TaskSupervisorService), state, brief)
    assert state.get("suspended") is False
    assert state.get("day_index") == 2
    assert state.get("crawl_done") is None
    assert state.get("stats_synced") is None
    assert state["execution_plan"]["current_index"] == 0
    decision = plan_driven_supervisor_decision(state["execution_plan"], brief, state)
    assert decision is not None
    assert decision["action"] == "crawl_keyword"


def test_advance_supervisor_plan_marks_crawl_complete():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    state: dict = {}
    plan = advance_supervisor_plan(plan, action="crawl_keyword", ok=True, state=state, brief=brief)
    assert plan["steps"][0]["status"] == "completed"
    assert plan["current_index"] == 1


def test_advance_supervisor_plan_query_stats_does_not_complete_evaluate_step():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    plan["steps"][0]["status"] = "completed"
    plan["current_index"] = 1
    evaluate_step = plan["steps"][1]
    assert evaluate_step["action"] == "evaluate_leads"
    assert evaluate_step["status"] == "pending"

    plan = advance_supervisor_plan(
        plan,
        action="query_stats",
        ok=True,
        state={"crawl_done": True, "stats_synced": True},
        brief=brief,
    )
    assert evaluate_step["status"] == "pending"
    stats_step = next(s for s in plan["steps"] if s["action"] == "query_stats")
    assert stats_step["status"] == "completed"


def test_skill_flow_plan_after_crawl_returns_evaluate_leads():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    plan["steps"][0]["status"] = "completed"
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True},
    )
    assert decision is not None
    assert decision["action"] == "evaluate_leads"


def test_plan_complete_without_goal_becomes_suspend():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 10}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True, "stats_synced": True})
    for step in plan["steps"]:
        if step["action"] in {"crawl_keyword", "query_stats"}:
            step["status"] = "completed"
    plan["current_index"] = 2
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True, "stats_synced": True, "leads_collected": 0},
    )
    assert decision is not None
    assert decision["action"] == "suspend"
    assert decision.get("completion_outcome") == "plan_incomplete"


def test_guard_complete_keeps_complete_when_goal_reached():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 3}, platform="douyin")
    decision = guard_supervisor_complete_decision(
        brief,
        {"leads_collected": 3},
        {"action": "complete", "reasoning": "done", "params": {}},
    )
    assert decision["action"] == "complete"
    assert decision.get("completion_outcome") == "goal_reached"


def test_infer_suspend_next_action_skill_flow_crawl_done_branch():
  brief = TaskBrief(
      keyword="淋浴房",
      goals={"target_leads": 5, "execution_mode": "skill_flow"},
      constraints={"termination_resume_next_day": True},
      platform="douyin",
  )
  state = {"crawl_done": True, "crawl_search_exhausted": False}
  next_action = infer_suspend_next_action("计划步骤失败，挂起等待人工处理", state, brief)
  assert "继续执行" in next_action or "reply" in next_action


def test_source_exhausted_suspend_next_action_and_note():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    state = {
        "suspended": True,
        "completion_outcome": "source_exhausted",
        "crawl_search_exhausted": True,
        "leads_collected": 1,
        "wake_reason": "已扫完当前搜索列表仍无匹配评论",
    }
    next_action = infer_suspend_next_action(state["wake_reason"], state, brief)
    assert "评估标准" in next_action
    assert "降低目标数" in next_action

    note = build_execution_note(
        job_status="suspended",
        job_stage="track",
        job_result={
            "completion_outcome": "source_exhausted",
            "supervisor_state": state,
            "data_snapshot": {"progress": {"leads_collected": 1, "target_leads": 5}},
        },
    )
    assert note == "Supervisor 已挂起：搜索源已耗尽且未达成目标（1/5），请调整关键词或匹配条件。"


def test_round_mode_goal_uses_current_round_progress():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 999, "repeat_mode": "round", "round_target_count": 2, "max_rounds": 3},
        constraints={"repeat_mode": "round", "round_target_count": 2, "max_rounds": 3},
        platform="douyin",
    )
    state = {"round_index": 1, "round_leads_collected": 2, "leads_collected": 2}
    assert supervisor_goal_reached(brief, state) is True
