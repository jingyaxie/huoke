from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.task_platform.executors.base import TaskExecutor


class TaskExecutorRegistry:
    _executors: dict[str, TaskExecutor] = {}

    @classmethod
    def register(cls, executor: TaskExecutor) -> None:
        cls._executors[executor.executor_id] = executor

    @classmethod
    def get(cls, executor_id: str) -> TaskExecutor | None:
        return cls._executors.get(executor_id)

    @classmethod
    def all(cls) -> list[TaskExecutor]:
        return list(cls._executors.values())
