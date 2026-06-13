from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.task_platform.schemas.instance import TaskCreateRequest, TaskInstanceOut


CompileMethod = Literal["rule", "llm", "hybrid"]


class TaskCompileRequest(BaseModel):
    """外部原始 JSON → 内部 TaskSpec 编译请求。"""

    raw_payload: dict[str, Any] = Field(default_factory=dict)
    source: Literal["local", "external"] = "external"
    adapter_id: str | None = Field(default=None, max_length=64)
    intent: str | None = Field(default=None, max_length=64, description="lead_crawl / lead_acquisition 等")
    hints: dict[str, Any] = Field(default_factory=dict)
    provider: Literal["openai", "deepseek"] = "deepseek"
    force_llm: bool = False
    account_id: str | None = None


class TaskCompilePlan(BaseModel):
    template_id: str
    template_version: str
    spec: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    unmapped_fields: list[str] = Field(default_factory=list)
    reasoning: str = ""
    method: CompileMethod = "rule"
    validation_ok: bool = False
    validation_error: str | None = None


class TaskCompileResponse(BaseModel):
    ok: bool
    plan: TaskCompilePlan
    create_request: TaskCreateRequest | None = None


class TaskCompileAndCreateRequest(TaskCompileRequest):
    name: str | None = None
    external_ref: str | None = None
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)
    async_mode: bool = Field(default=True, alias="async")
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=2, ge=0, le=5)
    auto_submit: bool = True
    auto_restart: bool = True
    scheduled_at: datetime | None = None
    headless: bool | None = Field(
        default=None,
        description="浏览器模式：true=无头，false=可见；创建时写入 spec",
    )

    model_config = {"populate_by_name": True}


class TaskCompileAndCreateResponse(BaseModel):
    compile: TaskCompileResponse
    task: TaskInstanceOut | None = None
