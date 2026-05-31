from datetime import datetime

from pydantic import BaseModel


class CrawlItem(BaseModel):
    rank: int
    title: str
    author_name: str | None = None
    douyin_video_id: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    publish_time: datetime | None = None
    author_avatar_url: str | None = None
    author_profile_url: str | None = None
    raw_data: dict | None = None


class CrawlResult(BaseModel):
    snapshot_date: str
    total: int
    items: list[CrawlItem]

