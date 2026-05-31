from datetime import date

from sqlalchemy import func, select

from app.models.hot_rank_snapshot import HotRankSnapshot
from app.repositories.base import BaseRepository


class SnapshotRepository(BaseRepository):
    def _find_by_date_rank(self, snapshot_date: date, rank: int) -> HotRankSnapshot | None:
        return self.session.scalar(
            select(HotRankSnapshot)
            .where(HotRankSnapshot.snapshot_date == snapshot_date)
            .where(HotRankSnapshot.rank == rank)
            .limit(1)
        )

    def _find_by_date_video(self, snapshot_date: date, video_id: int) -> HotRankSnapshot | None:
        return self.session.scalar(
            select(HotRankSnapshot)
            .where(HotRankSnapshot.snapshot_date == snapshot_date)
            .where(HotRankSnapshot.video_id == video_id)
            .limit(1)
        )

    def add_snapshot(
        self,
        *,
        snapshot_date: date,
        rank: int,
        video_id: int,
        score: float | None = None,
        rank_change: int | None = None,
        raw_data: dict | None = None,
    ) -> HotRankSnapshot:
        snapshot = self._find_by_date_video(snapshot_date, video_id) or self._find_by_date_rank(snapshot_date, rank)
        if snapshot is None:
            snapshot = HotRankSnapshot(
                snapshot_date=snapshot_date,
                rank=rank,
                video_id=video_id,
                score=score,
                rank_change=rank_change,
                raw_data=raw_data,
            )
            self.session.add(snapshot)
        else:
            snapshot.rank = rank
            snapshot.video_id = video_id
            snapshot.score = score
            snapshot.rank_change = rank_change
            snapshot.raw_data = raw_data
        self.session.flush()
        return snapshot

    def get_previous_rank(self, *, video_id: int, snapshot_date: date) -> int | None:
        stmt = (
            select(HotRankSnapshot.rank)
            .where(HotRankSnapshot.video_id == video_id)
            .where(HotRankSnapshot.snapshot_date < snapshot_date)
            .order_by(HotRankSnapshot.snapshot_date.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def list_by_date(self, snapshot_date: date, limit: int = 100):
        return self.session.scalars(
            select(HotRankSnapshot)
            .where(HotRankSnapshot.snapshot_date == snapshot_date)
            .order_by(HotRankSnapshot.rank.asc())
            .limit(limit)
        ).all()

    def rank_change_series(self, video_id: int, days: int = 30):
        stmt = (
            select(
                HotRankSnapshot.snapshot_date,
                HotRankSnapshot.rank,
                HotRankSnapshot.rank_change,
            )
            .where(HotRankSnapshot.video_id == video_id)
            .order_by(HotRankSnapshot.snapshot_date.asc())
        )
        return self.session.execute(stmt).all()

    def author_daily_counts(self, limit: int = 50):
        stmt = (
            select(
                func.date(HotRankSnapshot.snapshot_date).label("day"),
                func.count(HotRankSnapshot.id).label("count"),
            )
            .group_by("day")
            .order_by(func.date(HotRankSnapshot.snapshot_date).asc())
            .limit(limit)
        )
        return self.session.execute(stmt).all()
