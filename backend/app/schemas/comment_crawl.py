from pydantic import BaseModel, Field
from typing import Optional


class VideoCommentCrawlRequest(BaseModel):
    video_url: str
    show_browser: bool = False


class DouyinLoginRequest(BaseModel):
    show_browser: bool = True


class KeywordCommentCrawlRequest(BaseModel):
    keyword: str
    limit: int = Field(default=3, ge=1, le=20)
    show_browser: bool = False
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = None


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
    items: list[CommentCrawlResult]
