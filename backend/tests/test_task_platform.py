from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.task_platform import bootstrap_task_platform
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


def test_executor_registry_has_pipeline_only():
    from app.task_platform.registry.executor_registry import TaskExecutorRegistry

    executor = TaskExecutorRegistry.get("pipeline_only")
    assert executor is not None
    assert "lead-crawl" in executor.supported_templates

    acquisition = TaskExecutorRegistry.get("lead_acquisition")
    assert acquisition is not None
    assert "lead-acquisition" in acquisition.supported_templates
