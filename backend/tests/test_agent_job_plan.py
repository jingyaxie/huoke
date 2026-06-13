import json

from app.services.agent_job_plan_service import build_orchestration_plan


def test_yingxiaoyi_json_builds_lead_acquisition_steps():
    raw = {
        "task_name": "深圳餐饮老板线索",
        "keyword": "团餐配送",
        "platform": "douyin",
        "region": "深圳",
        "video_publish_days": 7,
        "comment_days": 3,
        "target_count": 500,
        "comment_ratio": 50,
        "dm_ratio": 50,
    }
    plan = build_orchestration_plan(json.dumps(raw, ensure_ascii=False))
    assert plan["source"] == "yingxiaoyi"
    assert plan["template_id"] == "lead-acquisition"
    assert len(plan["steps"]) == 5
    assert plan["steps"][0]["id"] == "crawl"
    assert plan["input_summary"]["keyword"] == "团餐配送"


def test_plain_text_falls_back_to_agent_pipeline():
    plan = build_orchestration_plan("帮我总结今日热门")
    assert plan["source"] == "agent"
    assert len(plan["steps"]) == 4


def test_compile_and_create_wrapper_selects_lead_acquisition():
    wrapper = {
        "adapter_id": "yingxiaoyi-lead-v1",
        "intent": "lead_acquisition",
        "raw_payload": {
            "task_name": "深圳餐饮老板线索",
            "keyword": "团餐配送",
            "platform": "douyin",
            "comment_days": 3,
            "target_count": 500,
            "comment_ratio": 50,
            "dm_ratio": 50,
            "daily_follow_limit": 30,
            "daily_dm_limit": 30,
        },
    }
    plan = build_orchestration_plan(json.dumps(wrapper, ensure_ascii=False))
    assert plan["source"] == "yingxiaoyi"
    assert plan["template_id"] == "lead-acquisition"
    assert len(plan["steps"]) == 5
    assert plan["steps"][-1]["id"] == "finalize"


def test_yingxiaoyi_plan_includes_outreach_policy():
    raw = {
        "keyword": "团餐配送",
        "comment_ratio": 50,
        "dm_ratio": 50,
        "interval_min": 10,
        "interval_max": 30,
        "daily_follow_limit": 30,
        "daily_dm_limit": 30,
    }
    plan = build_orchestration_plan(json.dumps(raw, ensure_ascii=False))
    policy = plan.get("outreach_policy")
    assert policy is not None
    assert policy["comment_ratio"] == 50
    assert policy["dm_prob_pct"] == 50.0
    outreach = next(s for s in plan["steps"] if s["id"] == "outreach")
    assert len(outreach.get("sub_steps") or []) == 2
    assert outreach["sub_steps"][0]["action"] == "reply"
