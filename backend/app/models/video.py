from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    douyin_video_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authors.id"), nullable=True, index=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    share_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    publish_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    author: Mapped["Author"] = relationship(back_populates="videos")
    snapshots: Mapped[List["HotRankSnapshot"]] = relationship(back_populates="video")
