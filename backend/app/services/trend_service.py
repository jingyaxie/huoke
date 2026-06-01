from datetime import date, timedelta

from sqlalchemy import desc, func, not_, select
from sqlalchemy.orm import Session, joinedload

from app.models.hot_rank_snapshot import HotRankSnapshot
from app.models.author import Author
from app.models.video import Video
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.video_repository import VideoRepository


class TrendService:
    def __init__(self, session: Session, tenant_id: str = "default", platform: str | None = None) -> None:
        from app.core.config import get_settings

        self.session = session
        self.tenant_id = tenant_id
        self.platform = platform or get_settings().default_platform
        self.snapshot_repo = SnapshotRepository(session, tenant_id, self.platform)
        self.video_repo = VideoRepository(session, tenant_id, self.platform)

    def list_hot_videos(self, snapshot_date: date | None = None, limit: int = 100):
        if snapshot_date is None:
            snapshot_date = self._latest_snapshot_date()
        stmt = (
            select(HotRankSnapshot)
            .options(joinedload(HotRankSnapshot.video).joinedload(Video.author))
            .where(HotRankSnapshot.tenant_id == self.tenant_id)
            .where(HotRankSnapshot.platform == self.platform)
            .where(HotRankSnapshot.snapshot_date == snapshot_date)
            .order_by(HotRankSnapshot.rank.asc())
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def list_hot_authors(self, snapshot_date: date | None = None, limit: int = 50):
        if snapshot_date is None:
            snapshot_date = self._latest_snapshot_date()
        invalid_author_pattern = r"^([0-9]{1,2}月[0-9]{1,2}日|[0-9]+[天周月年]前)$"
        stmt = (
            select(
                Author.id.label("author_id"),
                Author.name.label("author_name"),
                func.count(HotRankSnapshot.id).label("video_count"),
                func.sum(Video.like_count).label("like_count"),
                func.sum(Video.comment_count).label("comment_count"),
                func.sum(Video.share_count).label("share_count"),
            )
            .join(Video, Video.id == HotRankSnapshot.video_id)
            .join(Author, Author.id == Video.author_id)
            .where(HotRankSnapshot.tenant_id == self.tenant_id)
            .where(HotRankSnapshot.platform == self.platform)
            .where(Video.platform == self.platform)
            .where(Author.platform == self.platform)
            .where(HotRankSnapshot.snapshot_date == snapshot_date)
            .where(not_(Author.name.op("REGEXP")(invalid_author_pattern)))
            .group_by(Author.id, Author.name)
            .order_by(desc("video_count"))
            .limit(limit)
        )
        return self.session.execute(stmt).all()

    def video_trend(self, video_id: int, days: int = 30):
        if self.video_repo.get_by_id(video_id) is None:
            return []
        since = date.today() - timedelta(days=days)
        stmt = (
            select(HotRankSnapshot.snapshot_date, HotRankSnapshot.rank, HotRankSnapshot.rank_change)
            .where(HotRankSnapshot.tenant_id == self.tenant_id)
            .where(HotRankSnapshot.platform == self.platform)
            .where(HotRankSnapshot.video_id == video_id)
            .where(HotRankSnapshot.snapshot_date >= since)
            .order_by(HotRankSnapshot.snapshot_date.asc())
        )
        return self.session.execute(stmt).all()

    def overview(self, days: int = 7) -> dict:
        since = date.today() - timedelta(days=days)
        total_videos = self.session.scalar(
            select(func.count(Video.id)).where(
                Video.tenant_id == self.tenant_id,
                Video.platform == self.platform,
            )
        ) or 0
        total_snapshots = self.session.scalar(
            select(func.count(HotRankSnapshot.id))
            .where(HotRankSnapshot.tenant_id == self.tenant_id)
            .where(HotRankSnapshot.platform == self.platform)
            .where(HotRankSnapshot.snapshot_date >= since)
        ) or 0
        latest_date = self._latest_snapshot_date()
        top_videos = self.session.scalar(
            select(Video.title)
            .join(HotRankSnapshot, HotRankSnapshot.video_id == Video.id)
            .where(HotRankSnapshot.tenant_id == self.tenant_id)
            .where(HotRankSnapshot.platform == self.platform)
            .where(Video.tenant_id == self.tenant_id)
            .where(Video.platform == self.platform)
            .where(HotRankSnapshot.snapshot_date == latest_date)
            .order_by(HotRankSnapshot.rank.asc())
            .limit(1)
        )
        return {
            "platform": self.platform,
            "tenant_id": self.tenant_id,
            "total_videos": total_videos,
            "total_snapshots": total_snapshots,
            "latest_snapshot_date": latest_date.isoformat(),
            "top_video_title": top_videos,
        }

    def _latest_snapshot_date(self) -> date:
        latest = self.session.scalar(
            select(func.max(HotRankSnapshot.snapshot_date)).where(
                HotRankSnapshot.tenant_id == self.tenant_id,
                HotRankSnapshot.platform == self.platform,
            )
        )
        return latest or date.today()
