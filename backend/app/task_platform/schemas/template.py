from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskPhaseDefinition(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    capability: str = Field(..., min_length=1, max_length=128)
    retry: int = Field(default=0, ge=0, le=10)
    depends_on: list[str] = Field(default_factory=list)


class TaskTemplateOut(BaseModel):
    template_id: str
    version: str
    name: str
    description: str = ""
    executor_id: str
    platforms: list[str] = Field(default_factory=list)
    phases: list[TaskPhaseDefinition] = Field(default_factory=list)
    default_spec: dict[str, Any] = Field(default_factory=dict)
    scope: Literal["global", "tenant"] = "global"


class TaskTemplateListResponse(BaseModel):
    items: list[TaskTemplateOut]
    total: int
