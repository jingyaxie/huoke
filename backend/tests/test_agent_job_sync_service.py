from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models.content_comment import ContentComment
from app.services.agent_async_job_service import AgentAsyncJob
from app.services.agent_job_sync_service import AgentJobSyncService, verify_sync_signature


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_sync_payload_includes_correlation(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    job = AgentAsyncJob(
        job_id="sync-corr",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="completed",
        correlation={"external_system": "aisales", "external_task_id": "task-1"},
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.finished")

    assert payload["correlation"]["external_task_id"] == "task-1"


def test_sync_payload_has_stable_contract(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    job = AgentAsyncJob(
        job_id="sync-job",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="深圳团餐",
        status="completed",
        stage="dream",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        result={
            "summary": "done",
            "data_snapshot": {"progress": {"target_leads": 3, "leads_collected": 2}},
            "supervisor_state": {"comments_captured": 9, "completion_outcome": "source_exhausted"},
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.finished")

    assert payload["schema"] == "huoke.agent_job_sync.v1"
    assert payload["event"] == "job.finished"
    assert payload["job"]["job_id"] == "sync-job"
    assert payload["progress"]["target_leads"] == 3
    assert payload["progress"]["leads_collected"] == 2
    assert payload["progress"]["comments_captured"] == 9
    assert isinstance(payload["leads"], list)


def test_sync_payload_includes_lead_evaluation(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "source": "auto_generated",
        "criteria": {"accept_description": "询价"},
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-eval",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="深圳团餐",
        status="running",
        result={
            "orchestration": {
                "task_brief": {"constraints": {"lead_evaluation": spec}},
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.progress")

    assert payload["lead_evaluation"] == spec


def test_sync_payload_includes_captured_comments(tmp_path, db_session):
    from app.models.content_comment import ContentComment
    from datetime import datetime, timezone

    settings = Settings(storage_root=tmp_path / "storage")
    now = datetime.now(timezone.utc)
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-1",
            comment_id="cmt-1",
            nickname="测试用户",
            comment_text="想了解 ai获客 方案",
            digg_count=0,
            create_time=1_700_000_000,
            content_url="https://example.test/video/1",
            raw_data={"avatar": "https://example.test/avatar.jpg"},
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-captured",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-1"],
                "evaluation_cache": {
                    "cmt-1": {
                        "is_lead": True,
                        "score": 0.8,
                        "worth_outreach": True,
                        "reason": "有购买意向",
                    }
                }
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    row = payload["captured_comments"][0]
    assert row["nickname"] == "测试用户"
    assert row["avatar_url"] == "https://example.test/avatar.jpg"
    assert "ai获客" in row["comment_content"]
    assert row["is_precise"] is True


def test_captured_comments_scoped_to_job_content_ids(tmp_path, db_session):
    from datetime import datetime, timezone

    settings = Settings(storage_root=tmp_path / "storage")
    now = datetime.now(timezone.utc)
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-job",
            comment_id="cmt-job",
            nickname="任务用户",
            comment_text="本任务评论",
            digg_count=0,
            create_time=1_700_000_000,
            content_url="https://example.test/video/job",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-other",
            comment_id="cmt-other",
            nickname="其他用户",
            comment_text="其他任务评论",
            digg_count=0,
            create_time=1_700_000_001,
            content_url="https://example.test/video/other",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-scope",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-job"],
                "evaluation_cache": {
                    "cmt-job": {"score": 0.8, "worth_outreach": True, "reason": "有意向"},
                    "cmt-other": {"score": 0.9, "worth_outreach": True, "reason": "应被过滤"},
                },
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    assert payload["captured_comments"][0]["comment_id"] == "cmt-job"


def test_captured_comments_exclude_unevaluated_video_comments(tmp_path, db_session):
    from datetime import datetime, timezone

    settings = Settings(storage_root=tmp_path / "storage")
    now = datetime.now(timezone.utc)
    for idx in range(3):
        db_session.add(
            ContentComment(
                tenant_id="default",
                platform="douyin",
                content_id="vid-job",
                comment_id=f"cmt-{idx}",
                nickname=f"用户{idx}",
                comment_text=f"评论{idx}",
                digg_count=0,
                create_time=1_700_000_000 + idx,
                content_url="https://example.test/video/job",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-evaluated-only",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-job"],
                "job_evaluation_comment_ids": ["cmt-0", "cmt-1"],
                "evaluation_cache": {
                    "cmt-0": {"score": 0.8, "worth_outreach": True, "reason": "有意向"},
                    "cmt-1": {"score": 0.4, "worth_outreach": False, "reason": "无关"},
                    "cmt-2": {"score": 0.9, "worth_outreach": True, "reason": "未纳入任务"},
                },
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 2
    assert {row["comment_id"] for row in payload["captured_comments"]} == {"cmt-0", "cmt-1"}


def test_sync_payload_includes_suspend_brief(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    job = AgentAsyncJob(
        job_id="sync-suspend",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "summary": "今日配额已用尽",
            "supervisor_state": {
                "suspended": True,
                "wake_reason": "今日配额已用尽，按策略挂起等待下次唤醒",
                "resume_at": "2026-06-18T00:00:00+00:00",
                "next_action": "自动恢复后：同步今日 reply/follow/dm 配额 → 从已入库评论继续独立触达",
                "completion_outcome": "quota_exhausted",
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot")

    assert isinstance(payload.get("suspend_brief"), dict)
    assert "配额" in payload["suspend_brief"]["reason"]
    assert payload["suspend_brief"]["next_action"]
    assert payload["suspend_brief"]["resume_at_display"]


def test_sync_signature_roundtrip(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    payload = {"schema": "huoke.agent_job_sync.v1", "job": {"job_id": "j1"}}
    headers = AgentJobSyncService(settings).headers_for(payload)

    assert verify_sync_signature(
        payload,
        settings.huoke_bridge_secret,
        headers["X-Huoke-Sync-Timestamp"],
        headers["X-Huoke-Sync-Signature"],
    )


def test_webhook_posts_sync_contract(tmp_path, monkeypatch):
    from app.services.agent_async_job_service import AgentAsyncJobService

    settings = Settings(storage_root=tmp_path / "storage", huoke_bridge_secret="sync-secret")
    svc = AgentAsyncJobService(settings)
    job = AgentAsyncJob(
        job_id="webhook-sync",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="completed",
        webhook_url="https://example.test/hook",
    )
    seen: dict = {}

    async def capture_post(self, url, *, json=None, headers=None, **kwargs):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers or {}

        class Resp:
            status_code = 200

        return Resp()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", capture_post)
    asyncio.run(svc._post_webhook(job))

    assert seen["url"] == "https://example.test/hook"
    assert seen["json"]["schema"] == "huoke.agent_job_sync.v1"
    assert seen["json"]["event"] == "job.finished"
    assert seen["headers"]["X-Huoke-Sync-Signature"].startswith("sha256=")
