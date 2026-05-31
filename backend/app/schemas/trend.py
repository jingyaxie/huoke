from datetime import date

from pydantic import BaseModel


class TrendPoint(BaseModel):
    day: date
    rank: int | None = None
    rank_change: int | None = None


class TrendSeriesResponse(BaseModel):
    video_id: int
    title: str
    points: list[TrendPoint]

