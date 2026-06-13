from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.task_platform import bootstrap_task_platform
from app.task_platform.schemas.compile import TaskCompileRequest
from app.task_platform.services.compile_create_helper import build_create_request_from_compile
from app.task_platform.services.task_compiler_service import TaskCompilerService
from app.task_platform.services.task_runtime_service import TaskRuntimeService
from app.task_platform.stores.task_template_store import TaskTemplateStore

YINGXIAOYI_RAW = {
    "task_name": "编排测试任务",
    "keyword": "团餐配送",
    "platform": "douyin",
    "target_count": 80,
    "comment_days": 5,
    "region": "深圳",
}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
async def test_orchestration_compile_create_persists_snapshot(db_session):
    compiler = TaskCompilerService(Settings(), tenant_id="default")
    compile_req = TaskCompileRequest(
        raw_payload=YINGXIAOYI_RAW,
        adapter_id="yingxiaoyi-lead-v1",
        source="external",
    )
    compiled = await compiler.compile(compile_req)
    assert compiled.ok is True

    create_payload = build_create_request_from_compile(compile_req, compiled, overrides={"async_mode": False})
    assert create_payload is not None
    assert create_payload.raw_payload == YINGXIAOYI_RAW
    assert create_payload.compile_plan is not None
    assert create_payload.compile_plan["template_id"] == "lead-crawl"
    assert create_payload.compile_plan["spec"]["keyword"] == "团餐配送"

    runtime = TaskRuntimeService(Settings(), db_session, TaskTemplateStore())
    row = await runtime.create_async("default", create_payload)
    db_session.commit()

    loaded = runtime.get("default", row.id)
    assert loaded is not None
    assert loaded.raw_payload == YINGXIAOYI_RAW
    assert loaded.compile_plan["method"] == "rule"
    assert loaded.spec["keyword"] == "团餐配送"
    assert loaded.source == "external"
    assert loaded.adapter_id == "yingxiaoyi-lead-v1"


@pytest.mark.asyncio
async def test_orchestration_full_flow_via_api(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        compile_resp = client.post(
            "/api/open/tasks/compile",
            headers={"X-Tenant-Id": "default"},
            json={
                "raw_payload": YINGXIAOYI_RAW,
                "adapter_id": "yingxiaoyi-lead-v1",
                "source": "external",
            },
        )
        assert compile_resp.status_code == 200
        compile_body = compile_resp.json()
        assert compile_body["ok"] is True
        assert compile_body["plan"]["spec"]["keyword"] == "团餐配送"

        create_resp = client.post(
            "/api/open/tasks/compile-and-create",
            headers={"X-Tenant-Id": "default"},
            json={
                "raw_payload": YINGXIAOYI_RAW,
                "adapter_id": "yingxiaoyi-lead-v1",
                "source": "external",
                "auto_submit": False,
            },
        )
        assert create_resp.status_code == 200
        create_body = create_resp.json()
        assert create_body["task"] is not None
        task_id = create_body["task"]["task_id"]

        get_resp = client.get(
            f"/api/open/tasks/{task_id}",
            headers={"X-Tenant-Id": "default"},
        )
        assert get_resp.status_code == 200
        task_body = get_resp.json()
        assert task_body["raw_payload"]["keyword"] == "团餐配送"
        assert task_body["compile_plan"]["method"] == "rule"
        assert task_body["spec"]["crawl"]["target_leads"] == 80
    finally:
        app.dependency_overrides.clear()


def test_build_create_request_from_compile_returns_none_on_failure():
    from app.task_platform.schemas.compile import TaskCompilePlan, TaskCompileResponse

    compile_req = TaskCompileRequest(raw_payload={"task_name": "无关键词"}, adapter_id="yingxiaoyi-lead-v1")
    compiled = TaskCompileResponse(
        ok=False,
        plan=TaskCompilePlan(
            template_id="lead-crawl",
            template_version="1.0.0",
            validation_ok=False,
        ),
        create_request=None,
    )
    assert build_create_request_from_compile(compile_req, compiled) is None
