from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.schemas.template import TaskTemplateOut


@dataclass
class TaskContext:
    settings: Settings
    tenant_id: str
    db_session: Session | None
    template: TaskTemplateOut
    instance: TaskInstance
    cancel_requested: bool = False
    phase_outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    ok: bool
    spec: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class PhaseResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class TaskResult:
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class TaskExecutor(Protocol):
    executor_id: str
    supported_templates: tuple[str, ...]

    async def validate_spec(self, spec: dict[str, Any], template: TaskTemplateOut) -> ValidationResult: ...

    async def execute(self, ctx: TaskContext) -> TaskResult: ...
