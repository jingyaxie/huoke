from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.task_platform import bootstrap_task_platform
from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.schemas.instance import TaskCreateRequest
from app.task_platform.services.task_runtime_service import TaskRuntimeService
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


def test_template_store_lists_builtin_templates():
    store = TaskTemplateStore()
    items = store.list_templates()
    ids = {item.template_id for item in items}
    assert "lead-crawl" in ids
    assert "lead-acquisition" in ids


def test_template_merge_spec():
    store = TaskTemplateStore()
    template = store.get("lead-crawl")
    assert template is not None
    merged = store.merge_spec(template, {"keyword": "团餐", "platform": "douyin"})
    assert merged["keyword"] == "团餐"
    assert merged["crawl"]["comment_days"] == 3


@pytest.mark.asyncio
async def test_create_task_validates_keyword(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    with pytest.raises(ValueError, match="keyword"):
        await runtime.create_async(
            "default",
            TaskCreateRequest(template_id="lead-crawl", spec={"platform": "douyin"}),
        )


@pytest.mark.asyncio
async def test_create_task_persists_instance(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    row = await runtime.create_async(
        "default",
        TaskCreateRequest(
            template_id="lead-crawl",
            spec={"keyword": "团餐配送", "platform": "douyin", "task_name": "测试任务"},
            async_mode=False,
        ),
    )
    db_session.commit()
    loaded = runtime.get("default", row.id)
    assert loaded is not None
    assert loaded.name == "测试任务"
    assert loaded.status == "queued"
    assert loaded.spec["keyword"] == "团餐配送"
    assert loaded.progress["crawl"]["total"] == 100


@pytest.mark.asyncio
async def test_create_task_persists_headless(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    row = await runtime.create_async(
        "default",
        TaskCreateRequest(
            template_id="lead-crawl",
            spec={"keyword": "团餐", "platform": "douyin", "headless": False},
            async_mode=False,
        ),
    )
    db_session.commit()
    assert row.spec.get("headless") is False


def test_patch_task_headless(db_session):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_patch_headless",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="测试",
        platform="douyin",
        account_id="default",
        status="queued",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin", "headless": True},
        auto_restart=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.patch_settings("default", "tsk_patch_headless", headless=False)
    assert updated.spec["headless"] is False


def test_patch_task_auto_restart(db_session):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_patch_restart",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="测试",
        platform="douyin",
        account_id="default",
        status="queued",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin"},
        auto_restart=True,
        max_retries=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.patch_settings(
        "default",
        "tsk_patch_restart",
        auto_restart=False,
        max_retries=3,
    )
    assert updated.auto_restart is False
    assert updated.max_retries == 3


@pytest.mark.asyncio
async def test_create_task_persists_auto_restart(db_session):
    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    row = await runtime.create_async(
        "default",
        TaskCreateRequest(
            template_id="lead-crawl",
            spec={"keyword": "团餐", "platform": "douyin"},
            async_mode=False,
            auto_restart=False,
            max_retries=2,
        ),
    )
    db_session.commit()
    assert row.auto_restart is False
    assert row.max_retries == 2


def test_recover_pending_tasks(db_session, monkeypatch):
    import app.task_platform.services.task_runtime_service as trs
    from datetime import datetime, timezone

    class _PoolStub:
        enqueued: list[tuple[str, str]] = []

        def enqueue(self, *, tenant_id: str, task_id: str, priority: int = 5) -> None:
            self.enqueued.append((tenant_id, task_id))

    stub = _PoolStub()
    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: stub)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_recover",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="待恢复",
        platform="douyin",
        account_id="default",
        status="queued",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin"},
        auto_restart=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    from sqlalchemy.orm import sessionmaker
    from app.db.session import SessionLocal

    engine = db_session.get_bind()
    TestSession = sessionmaker(bind=engine)

    def _session_local():
        return TestSession()

    monkeypatch.setattr("app.db.session.SessionLocal", _session_local)
    count = TaskRuntimeService.recover_pending_tasks(Settings())
    assert count == 1
    assert stub.enqueued == [("default", "tsk_recover")]


def test_executor_registry_has_pipeline_only():
    from app.task_platform.registry.executor_registry import TaskExecutorRegistry

    executor = TaskExecutorRegistry.get("pipeline_only")
    assert executor is not None
    assert "lead-crawl" in executor.supported_templates

    acquisition = TaskExecutorRegistry.get("lead_acquisition")
    assert acquisition is not None
    assert "lead-acquisition" in acquisition.supported_templates


def test_restart_resume_sets_flag(db_session, monkeypatch):
    import app.task_platform.services.task_runtime_service as trs
    from datetime import datetime, timezone

    class _PoolStub:
        enqueued: list[tuple[str, str]] = []

        def enqueue(self, *, tenant_id: str, task_id: str, priority: int = 5) -> None:
            self.enqueued.append((tenant_id, task_id))

    stub = _PoolStub()
    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: stub)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_resume",
        tenant_id="default",
        template_id="lead-acquisition",
        template_version="1.0.0",
        executor_id="lead_acquisition",
        name="续跑",
        platform="douyin",
        account_id="default",
        status="failed",
        progress={"crawl": {"done": 5, "total": 10, "batches": 1}, "overall_percent": 50},
        result={"checkpoint": {"phase": "match_done", "matched_leads": [{"id": "l1"}]}},
        spec={"keyword": "团餐", "platform": "douyin", "crawl": {"target_leads": 10}},
        auto_restart=True,
        retry_count=2,
        error="boom",
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.restart("default", "tsk_resume", fresh=False)
    assert updated.status == "queued"
    assert updated.spec.get("_resume") is True
    assert updated.retry_count == 0
    assert updated.error is None
    assert updated.result == row.result
    assert stub.enqueued == [("default", "tsk_resume")]


def test_restart_fresh_clears_progress(db_session, monkeypatch):
    import app.task_platform.services.task_runtime_service as trs
    from datetime import datetime, timezone

    class _PoolStub:
        enqueued: list[tuple[str, str]] = []

        def enqueue(self, *, tenant_id: str, task_id: str, priority: int = 5) -> None:
            self.enqueued.append((tenant_id, task_id))

    stub = _PoolStub()
    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: stub)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_fresh",
        tenant_id="default",
        template_id="lead-acquisition",
        template_version="1.0.0",
        executor_id="lead_acquisition",
        name="重跑",
        platform="douyin",
        account_id="default",
        status="completed",
        progress={"crawl": {"done": 10, "total": 10, "batches": 2}, "overall_percent": 100},
        result={"matched_leads": 10},
        spec={"keyword": "团餐", "platform": "douyin", "crawl": {"target_leads": 10}, "_resume": True},
        auto_restart=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.restart("default", "tsk_fresh", fresh=True)
    assert updated.status == "queued"
    assert "_resume" not in updated.spec
    assert updated.result is None
    assert updated.progress["crawl"]["done"] == 0
    assert updated.progress["overall_percent"] == 0


def test_delete_task(db_session):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_delete",
        tenant_id="default",
        template_id="lead-crawl",
        template_version="1.0.0",
        executor_id="pipeline_only",
        name="删除",
        platform="douyin",
        account_id="default",
        status="failed",
        progress={},
        spec={"keyword": "团餐", "platform": "douyin"},
        auto_restart=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    runtime.delete("default", "tsk_delete")
    db_session.commit()
    assert runtime.get("default", "tsk_delete") is None


def test_submit_terminal_calls_resume(db_session, monkeypatch):
    import app.task_platform.services.task_runtime_service as trs
    from datetime import datetime, timezone

    class _PoolStub:
        enqueued: list[tuple[str, str]] = []

        def enqueue(self, *, tenant_id: str, task_id: str, priority: int = 5) -> None:
            self.enqueued.append((tenant_id, task_id))

    stub = _PoolStub()
    monkeypatch.setattr(trs.TaskWorkerPool, "get", lambda _settings: stub)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = TaskInstance(
        id="tsk_submit_dl",
        tenant_id="default",
        template_id="lead-acquisition",
        template_version="1.0.0",
        executor_id="lead_acquisition",
        name="死信",
        platform="douyin",
        account_id="default",
        status="dead_letter",
        progress={"crawl": {"done": 3, "total": 10, "batches": 1}, "overall_percent": 30},
        result={"checkpoint": {"phase": "crawl_partial", "collected": 3}},
        spec={"keyword": "团餐", "platform": "douyin", "crawl": {"target_leads": 10}},
        auto_restart=True,
        retry_count=2,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    updated = runtime.submit("default", "tsk_submit_dl")
    assert updated.status == "queued"
    assert updated.spec.get("_resume") is True
    assert updated.retry_count == 0
    assert stub.enqueued == [("default", "tsk_submit_dl")]
