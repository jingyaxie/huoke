from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TaskEventType = Literal[
    "task.created",
    "task.started",
    "task.phase.started",
    "task.phase.completed",
    "task.progress",
    "task.completed",
    "task.failed",
    "task.paused",
    "task.cancelled",
]


class TaskWebhookPayload(BaseModel):
    event: TaskEventType
    task_id: str
    template_id: str
    status: str
    current_phase: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    external_ref: str | None = None
