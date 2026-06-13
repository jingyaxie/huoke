from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.task_platform.schemas.compile import (
    TaskCompileAndCreateRequest,
    TaskCompileAndCreateResponse,
    TaskCompileRequest,
    TaskCompileResponse,
)
from app.task_platform.schemas.instance import (
    TaskCreateRequest,
    TaskInstanceListResponse,
    TaskInstanceOut,
    TaskPhaseListResponse,
)
from app.task_platform.schemas.template import TaskTemplateListResponse, TaskTemplateOut
from app.task_platform.services.compile_create_helper import build_create_request_from_compile
from app.task_platform.services.task_compiler_service import TaskCompilerService
from app.task_platform.services.task_runtime_service import TaskRuntimeService
from app.task_platform.services.task_serializer import serialize_phase_run, serialize_task_instance
from app.task_platform.stores.task_template_store import get_task_template_store

router = APIRouter(prefix="/api/open", tags=["open-tasks"])


def _runtime(session: Session, settings: Settings) -> TaskRuntimeService:
    return TaskRuntimeService(settings, session, get_task_template_store())


@router.get("/task-templates", response_model=TaskTemplateListResponse)
def list_task_templates(
    tenant_id: str = Depends(get_authenticated_tenant_id),
) -> TaskTemplateListResponse:
    store = get_task_template_store()
    items = store.list_templates(tenant_id=tenant_id)
    return TaskTemplateListResponse(items=items, total=len(items))


@router.get("/task-templates/{template_id}", response_model=TaskTemplateOut)
def get_task_template(
    template_id: str,
    version: str | None = Query(default=None),
    tenant_id: str = Depends(get_authenticated_tenant_id),
) -> TaskTemplateOut:
    store = get_task_template_store()
    item = store.get(template_id, tenant_id=tenant_id, version=version)
    if item is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return item


def _compiler(settings: Settings, tenant_id: str) -> TaskCompilerService:
    return TaskCompilerService(settings, tenant_id=tenant_id)


@router.post("/tasks/compile", response_model=TaskCompileResponse)
async def compile_task(
    payload: TaskCompileRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> TaskCompileResponse:
    compiler = _compiler(settings, tenant_id)
    return await compiler.compile(payload)


@router.post("/tasks/compile-and-create", response_model=TaskCompileAndCreateResponse)
async def compile_and_create_task(
    payload: TaskCompileAndCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskCompileAndCreateResponse:
    compiler = _compiler(settings, tenant_id)
    compile_req = TaskCompileRequest(
        raw_payload=payload.raw_payload,
        source=payload.source,
        adapter_id=payload.adapter_id,
        intent=payload.intent,
        hints=payload.hints,
        provider=payload.provider,
        force_llm=payload.force_llm,
        account_id=payload.account_id,
    )
    compiled = await compiler.compile(compile_req)
    if not compiled.ok or compiled.create_request is None:
        return TaskCompileAndCreateResponse(compile=compiled, task=None)

    create_payload = build_create_request_from_compile(
        compile_req,
        compiled,
        overrides={
            "name": payload.name,
            "external_ref": payload.external_ref,
            "webhook_url": payload.webhook_url,
            "webhook_headers": payload.webhook_headers,
            "async_mode": payload.async_mode,
            "priority": payload.priority,
            "max_retries": payload.max_retries,
            "scheduled_at": payload.scheduled_at,
        },
    )
    if create_payload is None:
        return TaskCompileAndCreateResponse(compile=compiled, task=None)
    runtime = _runtime(session, settings)
    try:
        row = await runtime.create_async(tenant_id, create_payload)
        runtime.enqueue_if_ready(tenant_id, row, auto_submit=payload.auto_submit)
        session.commit()
        session.refresh(row)
        return TaskCompileAndCreateResponse(
            compile=compiled,
            task=serialize_task_instance(row),
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/adapters/{adapter_id}/tasks", response_model=TaskCompileAndCreateResponse)
async def create_task_via_adapter(
    adapter_id: str,
    payload: TaskCompileAndCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskCompileAndCreateResponse:
    body = payload.model_copy(update={"adapter_id": adapter_id})
    return await compile_and_create_task(body, tenant_id=tenant_id, session=session, settings=settings)


@router.post("/tasks", response_model=TaskInstanceOut)
async def create_task(
    payload: TaskCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    try:
        row = await runtime.create_async(tenant_id, payload)
        runtime.enqueue_if_ready(tenant_id, row, auto_submit=payload.async_mode)
        session.commit()
        session.refresh(row)
        return serialize_task_instance(row)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks", response_model=TaskInstanceListResponse)
def list_tasks(
    status: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceListResponse:
    runtime = _runtime(session, settings)
    rows, total = runtime.list(
        tenant_id,
        status=status,
        template_id=template_id,
        platform=platform,
        source=source,
        offset=offset,
        limit=limit,
    )
    return TaskInstanceListResponse(
        items=[serialize_task_instance(row) for row in rows],
        total=total,
    )


@router.get("/tasks/{task_id}", response_model=TaskInstanceOut)
def get_task(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    row = runtime.get(tenant_id, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return serialize_task_instance(row)


@router.get("/tasks/{task_id}/phases", response_model=TaskPhaseListResponse)
def list_task_phases(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskPhaseListResponse:
    runtime = _runtime(session, settings)
    if runtime.get(tenant_id, task_id) is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    rows = runtime.list_phases(tenant_id, task_id)
    items = [serialize_phase_run(row) for row in rows]
    return TaskPhaseListResponse(items=items, total=len(items))


@router.post("/tasks/{task_id}/pause", response_model=TaskInstanceOut)
def pause_task(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    try:
        row = runtime.pause(tenant_id, task_id)
        session.commit()
        session.refresh(row)
        return serialize_task_instance(row)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/resume", response_model=TaskInstanceOut)
def resume_task(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    try:
        row = runtime.resume(tenant_id, task_id)
        session.commit()
        session.refresh(row)
        return serialize_task_instance(row)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/cancel", response_model=TaskInstanceOut)
def cancel_task(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    try:
        row = runtime.cancel(tenant_id, task_id)
        session.commit()
        session.refresh(row)
        return serialize_task_instance(row)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/submit", response_model=TaskInstanceOut)
def submit_task(
    task_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TaskInstanceOut:
    runtime = _runtime(session, settings)
    try:
        row = runtime.submit(tenant_id, task_id)
        session.commit()
        session.refresh(row)
        return serialize_task_instance(row)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
