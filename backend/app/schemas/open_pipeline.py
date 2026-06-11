from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


PipelinePlatform = Literal["douyin", "xiaohongshu"]


class KeywordVideoCommentsRequest(CrawlCacheOptions):
    keyword: str = Field(..., min_length=1, max_length=200)
    platforms: list[PipelinePlatform] = Field(
        default_factory=lambda: ["douyin", "xiaohongshu"]
    )
    video_limit: int = Field(default=5, ge=1, le=20)
    account_id: str | None = None
    provider: Literal["openai", "deepseek"] = "deepseek"
    headless: bool | None = None
    timeout_seconds: int = Field(default=1200, ge=60, le=3600)
    async_job: bool = Field(default=False, description="为 true 时提交异步任务并返回 job_id")


class PlatformPipelineResult(BaseModel):
    platform: str
    status: str
    run_id: str | None = None
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class KeywordVideoCommentsResponse(BaseModel):
    keyword: str
    status: str
    platforms: list[PlatformPipelineResult] = Field(default_factory=list)
    job_id: str | None = None
    completed_at: datetime | None = None
    cache: CacheMeta | None = None
