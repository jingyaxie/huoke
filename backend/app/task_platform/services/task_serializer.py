from __future__ import annotations

from datetime import datetime, timezone

from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.models.task_phase_run import TaskPhaseRun
from app.task_platform.schemas.instance import TaskInstanceOut, TaskPhaseRunOut, TaskProgress


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def serialize_task_instance(row: TaskInstance) -> TaskInstanceOut:
    progress_raw = row.progress if isinstance(row.progress, dict) else {}
    progress = TaskProgress(
        crawl=dict(progress_raw.get("crawl") or {}),
        outreach=dict(progress_raw.get("outreach") or {}),
        overall_percent=int(progress_raw.get("overall_percent") or 0),
    )
    return TaskInstanceOut(
        task_id=row.id,
        tenant_id=row.tenant_id,
        template_id=row.template_id,
        template_version=row.template_version,
        name=row.name,
        platform=row.platform,
        account_id=row.account_id,
        status=row.status,  # type: ignore[arg-type]
        current_phase=row.current_phase,
        progress=progress,
        spec=dict(row.spec or {}),
        result=row.result,
        error=row.error,
        external_ref=row.external_ref,
        adapter_id=row.adapter_id,
        source=row.source,
        retry_count=row.retry_count,
        max_retries=row.max_retries,
        auto_restart=row.auto_restart,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        scheduled_at=row.scheduled_at,
        raw_payload=dict(row.raw_payload) if isinstance(row.raw_payload, dict) else None,
        compile_plan=dict(row.compile_plan) if isinstance(row.compile_plan, dict) else None,
    )


def serialize_phase_run(row: TaskPhaseRun) -> TaskPhaseRunOut:
    return TaskPhaseRunOut(
        id=row.id,
        task_id=row.task_id,
        phase_id=row.phase_id,
        status=row.status,  # type: ignore[arg-type]
        attempt=row.attempt,
        input_snapshot=dict(row.input_snapshot or {}),
        output_snapshot=row.output_snapshot,
        error=row.error,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )
