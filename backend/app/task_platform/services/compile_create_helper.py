from __future__ import annotations

from app.task_platform.schemas.compile import TaskCompileRequest, TaskCompileResponse
from app.task_platform.schemas.instance import TaskCreateRequest


def build_create_request_from_compile(
    compile_req: TaskCompileRequest,
    compiled: TaskCompileResponse,
    *,
    overrides: dict | None = None,
) -> TaskCreateRequest | None:
    """将编译结果转为可落库的 TaskCreateRequest（含 raw_payload / compile_plan 快照）。"""
    if not compiled.ok or compiled.create_request is None:
        return None
    extra = dict(overrides or {})
    plan_snapshot = compiled.plan.model_dump(mode="json")
    return compiled.create_request.model_copy(
        update={
            "name": extra.pop("name", None) or compiled.create_request.name,
            "external_ref": extra.pop("external_ref", None) or compiled.create_request.external_ref,
            "webhook_url": extra.pop("webhook_url", None) or compiled.create_request.webhook_url,
            "webhook_headers": extra.pop("webhook_headers", None) or compiled.create_request.webhook_headers,
            "async_mode": extra.pop("async_mode", compiled.create_request.async_mode),
            "priority": extra.pop("priority", compiled.create_request.priority),
            "max_retries": extra.pop("max_retries", compiled.create_request.max_retries),
            "scheduled_at": extra.pop("scheduled_at", None) or compiled.create_request.scheduled_at,
            "raw_payload": dict(compile_req.raw_payload or {}),
            "compile_plan": plan_snapshot,
            **extra,
        }
    )
