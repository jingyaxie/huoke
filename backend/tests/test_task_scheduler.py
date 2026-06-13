from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.task_platform import bootstrap_task_platform
from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.repositories.task_instance_repository import TaskInstanceRepository
from app.task_platform.schemas.instance import TaskCreateRequest
from app.task_platform.services.task_runtime_service import TaskRuntimeService, TaskWorkerPool
from app.task_platform.services.task_schedule_utils import parse_scheduled_at, resolve_initial_task_status
from app.task_platform.services.task_scheduler_service import TaskSchedulerService
from app.task_platform.stores.task_template_store import TaskTemplateStore


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


@pytest.fixture(autouse=True)
def _bootstrap():
    bootstrap_task_platform()


def test_parse_scheduled_at_iso():
    dt = parse_scheduled_at("2026-06-14T09:00:00+08:00")
    assert dt is not None
    assert dt.hour == 1  # UTC


def test_resolve_initial_task_status_future():
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
    assert resolve_initial_task_status(future) == "scheduled"


def test_resolve_initial_task_status_past():
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    assert resolve_initial_task_status(past) == "queued"


@pytest.mark.asyncio
async def test_create_task_with_future_scheduled_at(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    row = await runtime.create_async(
        "default",
        TaskCreateRequest(
            template_id="lead-crawl",
            spec={"keyword": "团餐", "platform": "douyin"},
            scheduled_at=future,
            async_mode=True,
        ),
    )
    assert row.status == "scheduled"
    assert row.scheduled_at == future


@pytest.mark.asyncio
async def test_enqueue_if_ready_skips_scheduled(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    row = await runtime.create_async(
        "default",
        TaskCreateRequest(
            template_id="lead-crawl",
            spec={"keyword": "团餐", "platform": "douyin"},
            scheduled_at=future,
        ),
    )
    runtime.enqueue_if_ready("default", row, auto_submit=True)
    db_session.refresh(row)
    assert row.status == "scheduled"


def test_submit_scheduled_task(db_session, monkeypatch):
    import app.task_platform.services.task_runtime_service as trs

    class _PoolStub:
        def enqueue(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: _PoolStub())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    past = now - timedelta(minutes=5)
    row = TaskInstance(
        id="tsk_submit_scheduled",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="定时任务",
        platform="douyin",
        account_id="default",
        status="scheduled",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin", "crawl": {"target_leads": 10, "comment_days": 3}},
        scheduled_at=past,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.submit("default", "tsk_submit_scheduled")
    assert updated.status == "queued"


def test_scheduler_dispatches_due_task(db_session, monkeypatch):
    import app.task_platform.services.task_scheduler_service as tss
    import app.task_platform.services.task_runtime_service as trs

    class _PoolStub:
        def enqueue(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: _PoolStub())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    past = now - timedelta(minutes=5)
    row = TaskInstance(
        id="tsk_dispatch_due",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="定时任务",
        platform="douyin",
        account_id="default",
        status="scheduled",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin", "crawl": {"target_leads": 10, "comment_days": 3}},
        scheduled_at=past,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    original = SessionLocal
    engine = db_session.get_bind()
    TestSession = sessionmaker(bind=engine)

    def _session_local():
        return TestSession()

    monkeypatch.setattr(tss, "SessionLocal", _session_local)
    dispatched = TaskSchedulerService(Settings())._dispatch_due_tasks_sync(10)
    assert dispatched == 1
    db_session.refresh(row)
    assert row.status == "queued"


def test_list_due_scheduled(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = TaskInstance(
        id="tsk_due",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="到期",
        platform="douyin",
        account_id="default",
        status="scheduled",
        progress={},
        spec={},
        scheduled_at=now - timedelta(minutes=1),
        created_at=now,
        updated_at=now,
    )
    future = TaskInstance(
        id="tsk_future",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="未到期",
        platform="douyin",
        account_id="default",
        status="scheduled",
        progress={},
        spec={},
        scheduled_at=now + timedelta(hours=2),
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([due, future])
    db_session.commit()
    rows = TaskInstanceRepository.list_due_scheduled(db_session, limit=10)
    assert [r.id for r in rows] == ["tsk_due"]
