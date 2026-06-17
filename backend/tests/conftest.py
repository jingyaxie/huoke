"""共享 API 测试 fixtures。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from tests.helpers import API_HEADERS

__all__ = ["API_HEADERS", "api_client", "capture_submit"]


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    from app.core import config as config_module

    config_module.get_settings.cache_clear()

    storage = tmp_path / "storage"
    settings = Settings(
        storage_root=storage,
        deepseek_api_key="test-deepseek-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )

    def _get_settings():
        return settings

    monkeypatch.setattr("app.core.config.get_settings", _get_settings)
    monkeypatch.setattr("app.api.deps.get_settings", _get_settings)
    monkeypatch.setattr("app.api.settings_routes.get_settings", _get_settings)
    monkeypatch.setattr("app.api.agent_routes.get_settings", _get_settings)
    app.dependency_overrides[get_settings] = _get_settings

    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return {"status": "ready", "nickname": "测试号", "cookie_ready": True}

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def capture_submit(monkeypatch):
    captured: dict = {}

    async def fake_submit_async(self, **kwargs):
        captured.update(kwargs)
        from datetime import datetime, timezone

        from app.services.agent_async_job_service import AgentAsyncJob

        now = datetime.now(timezone.utc)
        return AgentAsyncJob(
            job_id="job-test-e2e",
            tenant_id=kwargs.get("tenant_id", "default"),
            platform=kwargs.get("platform", "douyin"),
            account_id=kwargs.get("account_id", "default"),
            message=kwargs.get("message", ""),
            provider=kwargs.get("provider", "deepseek"),
            mode=kwargs.get("mode", "agent"),
            run_mode=kwargs.get("run_mode", "auto"),
            auto_execute=kwargs.get("auto_execute", True),
            auto_restart=kwargs.get("auto_restart", True),
            agent_strategy=kwargs.get("agent_strategy"),
            status="queued",
            created_at=now,
            updated_at=now,
            correlation=kwargs.get("correlation") or {},
            result={"config": kwargs.get("config") or {}},
        )

    monkeypatch.setattr(
        "app.api.agent_routes.AgentAsyncJobService.submit_async",
        fake_submit_async,
    )
    return captured
