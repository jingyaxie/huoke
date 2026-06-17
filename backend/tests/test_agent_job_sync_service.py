from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob
from app.services.agent_job_sync_service import AgentJobSyncService, verify_sync_signature


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
