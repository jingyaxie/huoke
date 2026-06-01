from datetime import date, datetime
from typing import Optional, Dict, Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class HotRankSnapshot(Base):
    __tablename__ = "hot_rank_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "snapshot_date", "rank", name="uq_tenant_platform_snapshot_rank"),
        UniqueConstraint(
            "tenant_id", "platform", "snapshot_date", "video_id", name="uq_tenant_platform_snapshot_video"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="default")
    platform: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="douyin")
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    rank_change: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    video: Mapped["Video"] = relationship(back_populates="snapshots")
