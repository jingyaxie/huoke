from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AgentMode = Literal["agent", "plan", "ask"]
RunMode = Literal["auto", "confirm"]


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    run_id: str | None = None
    account_id: str | None = None
    agent_profile_id: str | None = Field(
        default=None,
        description="Agent 档案 ID，默认 default",
    )
    provider: Literal["openai", "deepseek"] = "openai"
    headless: bool | None = None
    explicit_skill_ids: list[str] = Field(default_factory=list)
    mode: AgentMode = "agent"
    run_mode: RunMode = "auto"


class AgentChatSyncRequest(AgentChatRequest):
    timeout_seconds: int = Field(default=600, ge=10, le=3600)


class AgentChatSyncResponse(BaseModel):
    run_id: str | None = None
    session_id: str | None = None
    status: str
    summary: str = ""
    final_message: str = ""
    task_snapshot: dict[str, Any] = Field(default_factory=dict)
    phase: str = ""
    message_count: int = 0
    updated_at: datetime | None = None


class AgentAsyncSubmitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    agent_profile_id: str | None = None
    provider: Literal["openai", "deepseek"] = "openai"
    mode: AgentMode = "agent"
    run_mode: RunMode = "auto"
    auto_execute: bool = Field(default=True, description="创建后是否立即入队执行")
    auto_restart: bool = Field(default=True, description="失败时是否自动重试（最多 max_retries 次）")
    timeout_seconds: int = Field(default=600, ge=10, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)


class AgentAsyncJobOut(BaseModel):
    job_id: str
    status: str
    stage: str = "plan"
    retry_count: int = 0
    run_id: str | None = None
    session_id: str | None = None
    message: str = ""
    provider: str = "openai"
    mode: str = "agent"
    run_mode: str = "auto"
    auto_execute: bool = True
    auto_restart: bool = True
    platform: str = ""
    account_id: str = ""
    timeout_seconds: int = 600
    max_retries: int = 1
    priority: int = 5
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    dead_letter_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentResumeRunRequest(BaseModel):
    run_id: str


class AgentResumeRequest(BaseModel):
    run_id: str
    approved: bool


class AgentRunSummaryOut(BaseModel):
    run_id: str
    title: str
    status: str
    message_count: int
    platform: str
    updated_at: datetime | None = None
    created_at: datetime | None = None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunSummaryOut]
    total: int


class AgentRunOut(BaseModel):
    run_id: str
    browser_session_id: str
    tenant_id: str
    platform: str
    provider: str
    status: str
    mode: str = "agent"
    run_mode: str = "auto"
    agent_profile_id: str = "default"
    message_count: int
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_plan: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    review_report: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    resumable: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentSessionCreateRequest(BaseModel):
    headless: bool | None = None


class AgentSessionOut(BaseModel):
    session_id: str
    platform: str
    tenant_id: str
    url: str | None = None
    title: str | None = None


class AgentMessageOut(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


class AgentEvent(BaseModel):
    type: Literal[
        "session",
        "status",
        "message",
        "message_delta",
        "tool_start",
        "tool_result",
        "step",
        "screenshot",
        "plan",
        "approval_request",
        "checkpoint",
        "context_compressed",
        "skill_installed",
        "skill_install_failed",
        "cancelled",
        "done",
        "error",
    ]
    data: dict[str, Any] = Field(default_factory=dict)


class CheckpointOut(BaseModel):
    checkpoint_id: str
    run_id: str
    step: int
    tool: str
    url: str | None = None
    title: str | None = None
    created_at: datetime | None = None


class CheckpointListResponse(BaseModel):
    items: list[CheckpointOut] = Field(default_factory=list)
    total: int = 0


class RestoreCheckpointRequest(BaseModel):
    checkpoint_id: str


class AgentProviderInfo(BaseModel):
    configured: bool
    vision: bool = False
    model: str
    note: str | None = None


class AgentBindingStatusOut(BaseModel):
    ready: bool
    tenant_id: str
    account_id: str
    platform: str
    platform_label: str
    status: str
    message: str
    cookie_count: int = 0
    storage_state_path: str | None = None
    code: str | None = None
    bind_api: str | None = None
    bindings_api: str | None = None


class AgentConfigOut(BaseModel):
    default_provider: Literal["openai", "deepseek"]
    default_run_mode: RunMode = "auto"
    dream_enabled: bool = True
    dream_auto: bool = True
    providers: dict[str, AgentProviderInfo]
