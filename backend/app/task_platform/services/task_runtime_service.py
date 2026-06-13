from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.task_platform.executors.base import TaskContext
from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.models.task_phase_run import TaskPhaseRun
from app.task_platform.registry.executor_registry import TaskExecutorRegistry
from app.task_platform.repositories.task_instance_repository import TaskInstanceRepository
from app.task_platform.repositories.task_phase_run_repository import TaskPhaseRunRepository
from app.task_platform.schemas.instance import TaskCreateRequest
from app.task_platform.services.task_event_bus import TaskEventBus
from app.task_platform.services.task_schedule_utils import parse_scheduled_at, resolve_initial_task_status
from app.task_platform.stores.task_template_store import TaskTemplateStore, get_task_template_store


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_task_id() -> str:
    return f"tsk_{uuid.uuid4().hex[:16]}"


@dataclass
class _QueueItem:
    tenant_id: str
    task_id: str
    priority: int


class TaskWorkerPool:
    """任务异步 worker 池；模式对齐 AgentAsyncJobService。"""

    _instance: TaskWorkerPool | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._queue: asyncio.PriorityQueue[tuple[int, float, _QueueItem]] = asyncio.PriorityQueue()
        self._workers_started = False
        self._workers: list[asyncio.Task[None]] = []
        self._running: dict[str, asyncio.Task[None]] = {}
        self._cancel_flags: set[str] = set()
        self._concurrency = max(1, int(getattr(settings, "task_job_concurrency", 2)))
        self._event_bus = TaskEventBus()

    @classmethod
    def get(cls, settings: Settings) -> TaskWorkerPool:
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        for idx in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(idx)))

    def request_cancel(self, task_id: str) -> None:
        self._cancel_flags.add(task_id)

    def clear_cancel(self, task_id: str) -> None:
        self._cancel_flags.discard(task_id)

    def is_cancel_requested(self, task_id: str) -> bool:
        return task_id in self._cancel_flags

    def start(self) -> None:
        """在 FastAPI lifespan（有 event loop）中调用一次。"""
        self._ensure_workers()

    def enqueue(self, *, tenant_id: str, task_id: str, priority: int = 5) -> None:
        if not self._workers_started:
            raise RuntimeError("TaskWorkerPool 未启动，请在应用 lifespan 中调用 start()")
        item = _QueueItem(tenant_id=tenant_id, task_id=task_id, priority=priority)
        self._queue.put_nowait((priority, time.monotonic(), item))

    async def _worker_loop(self, worker_id: int) -> None:
        _ = worker_id
        from app.db.session import SessionLocal

        while True:
            _, _, item = await self._queue.get()
            task = asyncio.create_task(self._run_one(item, SessionLocal))
            self._running[item.task_id] = task
            try:
                await task
            finally:
                self._running.pop(item.task_id, None)
                self._cancel_flags.discard(item.task_id)
                self._queue.task_done()

    async def _run_one(self, item: _QueueItem, session_factory: Any) -> None:
        session: Session = session_factory()
        runtime = TaskRuntimeService(self.settings, session, get_task_template_store())
        try:
            await runtime.execute_task(item.tenant_id, item.task_id, worker_pool=self)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class TaskRuntimeService:
    def __init__(
        self,
        settings: Settings,
        session: Session,
        template_store: TaskTemplateStore | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.template_store = template_store or get_task_template_store()
        self._event_bus = TaskEventBus()

    def _repo(self, tenant_id: str) -> TaskInstanceRepository:
        return TaskInstanceRepository(self.session, tenant_id)

    def _phase_repo(self, tenant_id: str) -> TaskPhaseRunRepository:
        return TaskPhaseRunRepository(self.session, tenant_id)

    async def create_async(self, tenant_id: str, payload: TaskCreateRequest) -> TaskInstance:
        template = self.template_store.get(
            payload.template_id,
            tenant_id=tenant_id,
            version=payload.template_version,
        )
        if template is None:
            raise ValueError(f"任务模板不存在: {payload.template_id}")

        executor = TaskExecutorRegistry.get(template.executor_id)
        if executor is None:
            raise ValueError(f"未注册的执行器: {template.executor_id}")

        merged_spec = self.template_store.merge_spec(template, payload.spec)
        validation = await executor.validate_spec(merged_spec, template)
        if not validation.ok:
            raise ValueError(validation.error or "任务 spec 校验失败")

        row = self._build_instance(tenant_id, payload, template, validation.spec or merged_spec)
        self._repo(tenant_id).add(row)
        self.session.flush()
        await self._event_bus.emit("task.created", row)
        return row

    def _build_instance(
        self,
        tenant_id: str,
        payload: TaskCreateRequest,
        template: Any,
        merged_spec: dict[str, Any],
    ) -> TaskInstance:
        now = _utc_now_naive()
        platform = str(merged_spec.get("platform") or self.settings.default_platform)
        account_id = str(merged_spec.get("account_id") or "default")
        name = (payload.name or merged_spec.get("task_name") or merged_spec.get("keyword") or template.name).strip()
        crawl = merged_spec.get("crawl") if isinstance(merged_spec.get("crawl"), dict) else {}
        target = int(crawl.get("target_leads") or 100)
        scheduled_at = parse_scheduled_at(payload.scheduled_at)
        initial_status = resolve_initial_task_status(scheduled_at, now=now)
        return TaskInstance(
            id=_new_task_id(),
            tenant_id=tenant_id,
            template_id=template.template_id,
            template_version=template.version,
            executor_id=template.executor_id,
            name=name[:200],
            platform=platform,
            account_id=account_id,
            status=initial_status,
            current_phase=None,
            progress={
                "crawl": {"done": 0, "total": target, "batches": 0},
                "outreach": {"done": 0, "total": 0},
                "overall_percent": 0,
            },
            spec=merged_spec,
            external_ref=payload.external_ref,
            adapter_id=payload.adapter_id,
            source=payload.source,
            priority=payload.priority,
            max_retries=payload.max_retries,
            webhook_url=payload.webhook_url,
            webhook_headers=payload.webhook_headers or None,
            raw_payload=payload.raw_payload,
            compile_plan=payload.compile_plan,
            scheduled_at=scheduled_at,
            created_at=now,
            updated_at=now,
        )

    def enqueue_if_ready(self, tenant_id: str, row: TaskInstance, *, auto_submit: bool) -> TaskInstance:
        """立即执行或 scheduled 未来任务：仅对 queued 且 auto_submit 时入队。"""
        if not auto_submit or row.status != "queued":
            return row
        return self.submit(tenant_id, row.id)

    def submit(self, tenant_id: str, task_id: str) -> TaskInstance:
        row = self._repo(tenant_id).get(task_id)
        if row is None:
            raise ValueError(f"任务不存在: {task_id}")
        if row.status not in {"queued", "failed", "paused", "scheduled"}:
            raise ValueError(f"任务状态 {row.status} 不可提交")
        row.status = "queued"
        row.updated_at = _utc_now_naive()
        self._repo(tenant_id).save(row)
        TaskWorkerPool.get(self.settings).enqueue(
            tenant_id=tenant_id,
            task_id=task_id,
            priority=row.priority,
        )
        return row

    async def execute_task(
        self,
        tenant_id: str,
        task_id: str,
        *,
        worker_pool: TaskWorkerPool | None = None,
    ) -> None:
        pool = worker_pool or TaskWorkerPool.get(self.settings)
        repo = self._repo(tenant_id)
        row = repo.get(task_id)
        if row is None:
            return

        template = self.template_store.get(row.template_id, tenant_id=tenant_id, version=row.template_version)
        if template is None:
            row.status = "failed"
            row.error = f"模板不存在: {row.template_id}"
            row.completed_at = _utc_now_naive()
            repo.save(row)
            await self._event_bus.emit("task.failed", row, error=row.error)
            return

        executor = TaskExecutorRegistry.get(row.executor_id)
        if executor is None:
            row.status = "failed"
            row.error = f"执行器未注册: {row.executor_id}"
            row.completed_at = _utc_now_naive()
            repo.save(row)
            await self._event_bus.emit("task.failed", row, error=row.error)
            return

        row.status = "running"
        row.started_at = row.started_at or _utc_now_naive()
        row.error = None
        repo.save(row)
        await self._event_bus.emit("task.started", row)

        phase_repo = self._phase_repo(tenant_id)
        phase_row = TaskPhaseRun(
            task_id=row.id,
            tenant_id=tenant_id,
            phase_id="execute",
            status="running",
            attempt=row.retry_count + 1,
            input_snapshot=dict(row.spec or {}),
            started_at=_utc_now_naive(),
        )
        phase_repo.add(phase_row)
        self.session.flush()

        ctx = TaskContext(
            settings=self.settings,
            tenant_id=tenant_id,
            db_session=self.session,
            template=template,
            instance=row,
            cancel_requested=pool.is_cancel_requested(row.id),
        )

        try:
            result = await executor.execute(ctx)
        except Exception as exc:
            row.retry_count += 1
            if row.retry_count <= row.max_retries:
                row.status = "queued"
                row.error = str(exc)
                repo.save(row)
                pool.enqueue(tenant_id=tenant_id, task_id=task_id, priority=row.priority)
                phase_row.status = "failed"
                phase_row.error = str(exc)
                phase_row.completed_at = _utc_now_naive()
                phase_repo.save(phase_row)
                return

            row.status = "dead_letter"
            row.error = str(exc)
            row.completed_at = _utc_now_naive()
            repo.save(row)
            phase_row.status = "failed"
            phase_row.error = str(exc)
            phase_row.completed_at = _utc_now_naive()
            phase_repo.save(phase_row)
            await self._event_bus.emit("task.failed", row, error=row.error)
            return

        row.progress = dict(ctx.instance.progress or row.progress or {})
        if result.status == "completed":
            row.status = "completed"
            row.result = result.result
            row.completed_at = _utc_now_naive()
            row.current_phase = None
            phase_row.status = "completed"
            phase_row.output_snapshot = result.result
            phase_row.completed_at = _utc_now_naive()
            repo.save(row)
            phase_repo.save(phase_row)
            await self._event_bus.emit("task.completed", row, result=result.result)
            return

        if result.status == "cancelled":
            row.status = "cancelled"
            row.completed_at = _utc_now_naive()
            row.result = result.result
            phase_row.status = "cancelled"
            phase_row.output_snapshot = result.result
            phase_row.completed_at = _utc_now_naive()
            repo.save(row)
            phase_repo.save(phase_row)
            await self._event_bus.emit("task.cancelled", row, result=result.result)
            return

        row.retry_count += 1
        row.error = result.error or "任务执行失败"
        if row.retry_count <= row.max_retries:
            row.status = "queued"
            repo.save(row)
            phase_row.status = "failed"
            phase_row.error = row.error
            phase_row.output_snapshot = result.result
            phase_row.completed_at = _utc_now_naive()
            phase_repo.save(phase_row)
            pool.enqueue(tenant_id=tenant_id, task_id=task_id, priority=row.priority)
            return

        row.status = "failed"
        row.result = result.result
        row.completed_at = _utc_now_naive()
        phase_row.status = "failed"
        phase_row.error = row.error
        phase_row.output_snapshot = result.result
        phase_row.completed_at = _utc_now_naive()
        repo.save(row)
        phase_repo.save(phase_row)
        await self._event_bus.emit("task.failed", row, error=row.error, result=result.result)

    def get(self, tenant_id: str, task_id: str) -> TaskInstance | None:
        return self._repo(tenant_id).get(task_id)

    def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        template_id: str | None = None,
        platform: str | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TaskInstance], int]:
        return self._repo(tenant_id).list(
            status=status,
            template_id=template_id,
            platform=platform,
            source=source,
            offset=offset,
            limit=limit,
        )

    def list_phases(self, tenant_id: str, task_id: str) -> list[TaskPhaseRun]:
        return self._phase_repo(tenant_id).list_for_task(task_id)

    def pause(self, tenant_id: str, task_id: str) -> TaskInstance:
        row = self._require_mutable(tenant_id, task_id)
        if row.status != "running":
            raise ValueError("仅运行中任务可暂停")
        TaskWorkerPool.get(self.settings).request_cancel(task_id)
        row.status = "paused"
        row.updated_at = _utc_now_naive()
        self._repo(tenant_id).save(row)
        return row

    def cancel(self, tenant_id: str, task_id: str) -> TaskInstance:
        row = self._repo(tenant_id).get(task_id)
        if row is None:
            raise ValueError(f"任务不存在: {task_id}")
        if row.status in {"completed", "cancelled", "dead_letter"}:
            raise ValueError(f"任务已结束: {row.status}")
        if row.status == "running":
            TaskWorkerPool.get(self.settings).request_cancel(task_id)
        row.status = "cancelled"
        row.completed_at = _utc_now_naive()
        row.updated_at = _utc_now_naive()
        self._repo(tenant_id).save(row)
        return row

    def resume(self, tenant_id: str, task_id: str) -> TaskInstance:
        row = self._repo(tenant_id).get(task_id)
        if row is None:
            raise ValueError(f"任务不存在: {task_id}")
        if row.status != "paused":
            raise ValueError("仅已暂停任务可恢复")
        TaskWorkerPool.get(self.settings).clear_cancel(task_id)
        row.status = "queued"
        row.updated_at = _utc_now_naive()
        self._repo(tenant_id).save(row)
        TaskWorkerPool.get(self.settings).enqueue(
            tenant_id=tenant_id,
            task_id=task_id,
            priority=row.priority,
        )
        return row

    def _require_mutable(self, tenant_id: str, task_id: str) -> TaskInstance:
        row = self._repo(tenant_id).get(task_id)
        if row is None:
            raise ValueError(f"任务不存在: {task_id}")
        if row.status in {"completed", "cancelled", "dead_letter"}:
            raise ValueError(f"任务已结束: {row.status}")
        return row
