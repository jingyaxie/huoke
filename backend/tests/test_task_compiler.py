from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.task_platform import bootstrap_task_platform
from app.task_platform.registry.adapter_registry import TaskAdapterRegistry
from app.task_platform.schemas.compile import TaskCompileRequest
from app.task_platform.services.task_compiler_service import TaskCompilerService


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


@pytest.mark.asyncio
async def test_yingxiaoyi_adapter_maps_lead_crawl_fields():
    compiler = TaskCompilerService(Settings(), tenant_id="default")
    request = TaskCompileRequest(
        raw_payload={
            "task_name": "盈小蚁测试",
            "keyword": "团餐配送",
            "platform": "douyin",
            "target_count": 50,
            "comment_days": 7,
            "region": "北京",
        },
        adapter_id="yingxiaoyi-lead-v1",
        source="external",
    )
    response = await compiler.compile(request)
    assert response.ok is True
    assert response.plan.template_id == "lead-crawl"
    assert response.plan.method == "rule"
    assert response.plan.spec["keyword"] == "团餐配送"
    assert response.plan.spec["crawl"]["target_leads"] == 50
    assert response.plan.spec["crawl"]["comment_days"] == 7
    assert response.create_request is not None
    assert response.create_request.name == "盈小蚁测试"


@pytest.mark.asyncio
async def test_yingxiaoyi_adapter_selects_lead_acquisition_with_outreach():
    compiler = TaskCompilerService(Settings(), tenant_id="default")
    request = TaskCompileRequest(
        raw_payload={
            "keyword": "装修",
            "platform": "xiaohongshu",
            "comment_ratio": 60,
            "daily_dm_limit": 20,
        },
        adapter_id="yingxiaoyi-lead-v1",
        source="external",
    )
    response = await compiler.compile(request)
    assert response.ok is True
    assert response.plan.template_id == "lead-acquisition"
    assert response.plan.spec["platform"] == "xiaohongshu"
    assert response.plan.spec["action_policy"]["comment_ratio"] == 60
    assert response.plan.spec["daily_limits"]["max_dms"] == 20


@pytest.mark.asyncio
async def test_compile_fails_without_keyword():
    compiler = TaskCompilerService(Settings(), tenant_id="default")
    request = TaskCompileRequest(
        raw_payload={"task_name": "无关键词"},
        adapter_id="yingxiaoyi-lead-v1",
        source="external",
    )
    response = await compiler.compile(request)
    assert response.ok is False
    assert response.create_request is None


@pytest.mark.asyncio
async def test_compile_fails_when_no_adapter_and_no_llm(monkeypatch):
    async def _no_llm(self, *_args, **_kwargs):
        return None

    monkeypatch.setattr(TaskCompilerService, "_compile_with_llm", _no_llm)
    compiler = TaskCompilerService(Settings(), tenant_id="default")
    request = TaskCompileRequest(
        raw_payload={"task_name": "无关键词"},
        adapter_id=None,
        source="external",
        force_llm=False,
    )
    response = await compiler.compile(request)
    assert response.ok is False
    assert response.create_request is None


def test_adapter_registry_has_yingxiaoyi():
    assert TaskAdapterRegistry.get("yingxiaoyi-lead-v1") is not None
    assert "yingxiaoyi-lead-v1" in TaskAdapterRegistry.all_ids()
