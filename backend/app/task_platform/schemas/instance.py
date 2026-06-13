from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.platforms.search_filters import normalize_region
from app.platforms.types import normalize_platform

TaskStatus = Literal[
    "scheduled",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "dead_letter",
]

PhaseStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]


class TaskCrawlSpec(BaseModel):
    video_publish_days: int | None = Field(default=None, ge=1, le=365)
    comment_days: int | None = Field(default=3, ge=1, le=30)
    target_leads: int = Field(default=100, ge=1, le=5000)
    video_limit_per_batch: int = Field(default=20, ge=1, le=20)
    max_batches: int = Field(default=50, ge=1, le=200)
    force_refresh: bool = False


class LeadCrawlTaskSpec(BaseModel):
    """lead-crawl 模板 canonical spec。"""

    task_name: str = Field(default="", max_length=200)
    keyword: str = Field(..., min_length=1, max_length=200)
    platform: str = Field(default="douyin")
    account_id: str = Field(default="default", max_length=64)
    region: str | None = None
    crawl: TaskCrawlSpec = Field(default_factory=TaskCrawlSpec)
    provider: Literal["openai", "deepseek"] = "deepseek"
    timeout_seconds: int = Field(default=1200, ge=60, le=3600)

    @field_validator("platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return normalize_platform(value)

    @field_validator("region", mode="before")
    @classmethod
    def _region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class TaskActionPolicy(BaseModel):
    comment_ratio: int = Field(default=50, ge=0, le=100)
    dm_ratio: int = Field(default=50, ge=0, le=100)
    interval_min_sec: int = Field(default=10, ge=1, le=600)
    interval_max_sec: int = Field(default=30, ge=1, le=600)
    reply_template: str = Field(default="您好，可以私信发您案例和报价～", max_length=500)
    dm_template: str = Field(default="您好，看到您的留言，方便聊聊需求吗？", max_length=500)


class TaskDailyLimits(BaseModel):
    max_comment_replies: int = Field(default=30, ge=0, le=500)
    max_follows: int = Field(default=30, ge=0, le=500)
    max_dms: int = Field(default=30, ge=0, le=500)


class LeadAcquisitionTaskSpec(LeadCrawlTaskSpec):
    """lead-acquisition：抓取 + 触达策略。"""

    action_policy: TaskActionPolicy = Field(default_factory=TaskActionPolicy)
    daily_limits: TaskDailyLimits = Field(default_factory=TaskDailyLimits)
    comment_match: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class TaskCreateRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=64)
    template_version: str | None = Field(default=None, max_length=32)
    spec: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=128)
    adapter_id: str | None = Field(default=None, max_length=64)
    source: Literal["local", "external"] = "local"
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)
    async_mode: bool = Field(default=True, alias="async")
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=1, ge=0, le=5)
    scheduled_at: datetime | None = None
    raw_payload: dict[str, Any] | None = None
    compile_plan: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class TaskProgress(BaseModel):
    crawl: dict[str, Any] = Field(default_factory=dict)
    outreach: dict[str, Any] = Field(default_factory=dict)
    overall_percent: int = Field(default=0, ge=0, le=100)


class TaskInstanceOut(BaseModel):
    task_id: str
    tenant_id: str
    template_id: str
    template_version: str
    name: str
    platform: str
    account_id: str
    status: TaskStatus
    current_phase: str | None = None
    progress: TaskProgress
    spec: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    external_ref: str | None = None
    adapter_id: str | None = None
    source: str = "local"
    retry_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scheduled_at: datetime | None = None
    raw_payload: dict[str, Any] | None = None
    compile_plan: dict[str, Any] | None = None


class TaskInstanceListResponse(BaseModel):
    items: list[TaskInstanceOut]
    total: int


class TaskPhaseRunOut(BaseModel):
    id: int
    task_id: str
    phase_id: str
    status: PhaseStatus
    attempt: int
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskPhaseListResponse(BaseModel):
    items: list[TaskPhaseRunOut]
    total: int
