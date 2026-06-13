from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import Settings
from app.db.session import SessionLocal
from app.task_platform.repositories.task_instance_repository import TaskInstanceRepository
from app.task_platform.services.task_runtime_service import TaskRuntimeService
from app.task_platform.stores.task_template_store import get_task_template_store

logger = logging.getLogger(__name__)


class TaskSchedulerService:
    """扫描 scheduled_at 到期任务并 submit 入队。"""

    _instance: TaskSchedulerService | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._poll_seconds = max(5, int(getattr(settings, "task_scheduler_poll_seconds", 30)))
        self._loop_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @classmethod
    def get(cls, settings: Settings) -> TaskSchedulerService:
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stopped.clear()
        self._loop_task = asyncio.create_task(self._run_loop(), name="task-scheduler")

    async def stop(self) -> None:
        self._stopped.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        logger.info("TaskScheduler 已启动，轮询间隔 %ss", self._poll_seconds)
        while not self._stopped.is_set():
            try:
                dispatched = await self.dispatch_due_tasks()
                if dispatched:
                    logger.info("TaskScheduler 已调度 %s 个到期任务", dispatched)
            except Exception:
                logger.exception("TaskScheduler tick 失败")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_seconds)
                break
            except asyncio.TimeoutError:
                continue

    async def dispatch_due_tasks(self, *, limit: int = 50) -> int:
        return await asyncio.to_thread(self._dispatch_due_tasks_sync, limit)

    def _dispatch_due_tasks_sync(self, limit: int) -> int:
        session = SessionLocal()
        dispatched = 0
        try:
            rows = TaskInstanceRepository.list_due_scheduled(session, limit=limit)
            if not rows:
                return 0
            runtime = TaskRuntimeService(session=session, settings=self.settings, template_store=get_task_template_store())
            for row in rows:
                try:
                    runtime.submit(row.tenant_id, row.id)
                    dispatched += 1
                except ValueError as exc:
                    logger.warning("调度任务 %s 失败: %s", row.id, exc)
            session.commit()
            return dispatched
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
