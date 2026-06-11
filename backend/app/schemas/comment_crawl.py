from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class VideoCommentCrawlRequest(BaseModel):
    video_url: str
    show_browser: bool = False
    tenant_id: Optional[str] = None
    platform: Optional[str] = None


class DouyinLoginRequest(BaseModel):
    show_browser: bool = True
    tenant_id: Optional[str] = None
    platform: Optional[str] = None


class KeywordCommentCrawlRequest(BaseModel):
    keyword: str
    limit: int = Field(default=3, ge=1, le=20)
    show_browser: bool = False
    guest_mode: bool = Field(
        default=False,
        description="游客态：跳过登录检查，使用抖音自动下发的会话 Cookie（仅抖音）",
    )
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = None
    tenant_id: Optional[str] = None
    platform: Optional[str] = None


class UploadStorageStateRequest(BaseModel):
    storage_state: dict[str, Any]


class CommentCrawlResult(BaseModel):
    video_url: str
    output_file: str
    total_comments_captured: int
    api_total_top_comments: int


class KeywordCommentCrawlResponse(BaseModel):
    keyword: str
    videos_found: int
    crawled: int
    diagnostic: str | None = None
    guest_mode: bool = False
    session_mode: Literal["guest", "logged_in", "anonymous"] = "logged_in"
    items: list[CommentCrawlResult]
