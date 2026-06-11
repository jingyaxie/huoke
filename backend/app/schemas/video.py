from datetime import datetime

from app.schemas.author import AuthorOut
from app.schemas.common import ORMBaseModel


class VideoOut(ORMBaseModel):
    id: int
    platform: str
    external_id: str | None
    title: str
    author_id: int | None
    video_url: str | None
    cover_url: str | None
    like_count: int
    comment_count: int
    share_count: int
    publish_time: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    raw_data: dict | None
    author: AuthorOut | None = None
