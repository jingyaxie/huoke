from datetime import date, datetime
from typing import Optional, Dict, Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class HotRankSnapshot(Base):
    __tablename__ = "hot_rank_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "rank", name="uq_snapshot_date_rank"),
        UniqueConstraint("snapshot_date", "video_id", name="uq_snapshot_date_video"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    rank_change: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    video: Mapped["Video"] = relationship(back_populates="snapshots")
