from __future__ import annotations

import pytest

from app.task_platform.services.lead_normalize_service import match_leads, pipeline_batch_to_leads
from app.services.outreach_policy import choose_outreach_action, random_interval_sec


def test_pipeline_batch_to_leads_from_comments_by_video():
    batch = {
        "platforms": [
            {
                "platform": "douyin",
                "status": "completed",
                "result": {
                    "comments_by_video": [
                        {
                            "note_id": "7123456789",
                            "note_url": "https://www.douyin.com/video/7123456789",
                            "comments": [
                                {
                                    "comment_id": "c1",
                                    "text": "多少钱",
                                    "username": "用户A",
                                    "user_id": "u1",
                                    "sec_uid": "sec1",
                                }
                            ],
                        }
                    ]
                },
            }
        ]
    }
    leads = pipeline_batch_to_leads(
        batch,
        task_id="t1",
        keyword="团餐",
        platform="douyin",
        comment_days=None,
    )
    assert len(leads) == 1
    assert leads[0]["comment"]["comment_id"] == "c1"


def test_match_leads_keyword():
    leads = [
        {
            "comment": {"text": "这个多少钱"},
            "comment_user": {"nickname": "A"},
        },
        {
            "comment": {"text": "好看"},
            "comment_user": {"nickname": "B"},
        },
    ]
    matched = match_leads(
        leads,
        comment_match={"mode": "keyword", "keywords": ["多少钱"], "min_comment_length": 2},
    )
    assert len(matched) == 1
    assert matched[0]["matched"] is True


def test_choose_outreach_action_only_comment():
    actions = {choose_outreach_action(comment_ratio=100, dm_ratio=0) for _ in range(20)}
    assert actions == {"reply"}


def test_random_interval_sec_order():
    value = random_interval_sec(10, 30)
    assert 10 <= value <= 30


@pytest.mark.asyncio
async def test_lead_acquisition_executor_validate_spec():
    from app.task_platform.executors.lead_acquisition import LeadAcquisitionExecutor
    from app.task_platform.schemas.template import TaskTemplateOut

    executor = LeadAcquisitionExecutor()
    template = TaskTemplateOut(
        template_id="lead-acquisition",
        version="1.0.0",
        name="线索采集与触达",
        description="",
        executor_id="lead_acquisition",
        platforms=["douyin", "xiaohongshu"],
        phases=[],
        default_spec={},
    )
    ok = await executor.validate_spec(
        {
            "keyword": "团餐",
            "platform": "douyin",
            "action_policy": {"interval_min_sec": 10, "interval_max_sec": 30},
        },
        template,
    )
    assert ok.ok is True

    bad = await executor.validate_spec(
        {
            "keyword": "团餐",
            "action_policy": {"interval_min_sec": 40, "interval_max_sec": 10},
        },
        template,
    )
    assert bad.ok is False
