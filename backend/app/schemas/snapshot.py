from datetime import date, datetime

from app.schemas.common import ORMBaseModel
from app.schemas.video import VideoOut


class SnapshotOut(ORMBaseModel):
    id: int
    snapshot_date: date
    rank: int
    video_id: int
    score: float | None
    rank_change: int | None
    raw_data: dict | None
    captured_at: datetime
    video: VideoOut | None = None

