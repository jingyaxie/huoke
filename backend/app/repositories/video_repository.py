from datetime import datetime

from sqlalchemy import select

from app.models.video import Video
from app.repositories.base import BaseRepository


class VideoRepository(BaseRepository):
    def get_by_douyin_video_id(self, douyin_video_id: str | None) -> Video | None:
        if not douyin_video_id:
            return None
        return self.session.scalar(select(Video).where(Video.douyin_video_id == douyin_video_id))

    def get_by_title_and_author(self, title: str, author_id: int | None) -> Video | None:
        stmt = select(Video).where(Video.title == title)
        if author_id is None:
            stmt = stmt.where(Video.author_id.is_(None))
        else:
            stmt = stmt.where(Video.author_id == author_id)
        return self.session.scalar(stmt)

    def upsert(
        self,
        *,
        title: str,
        author_id: int | None,
        douyin_video_id: str | None = None,
        video_url: str | None = None,
        cover_url: str | None = None,
        like_count: int = 0,
        comment_count: int = 0,
        share_count: int = 0,
        publish_time: datetime | None = None,
        raw_data: dict | None = None,
    ) -> Video:
        video = self.get_by_douyin_video_id(douyin_video_id) or self.get_by_title_and_author(title, author_id)
        if video is None:
            video = Video(
                douyin_video_id=douyin_video_id,
                title=title,
                author_id=author_id,
                video_url=video_url,
                cover_url=cover_url,
                like_count=like_count,
                comment_count=comment_count,
                share_count=share_count,
                publish_time=publish_time,
                first_seen_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow(),
                raw_data=raw_data,
            )
            self.session.add(video)
        else:
            video.douyin_video_id = video.douyin_video_id or douyin_video_id
            video.title = title or video.title
            video.author_id = author_id if author_id is not None else video.author_id
            video.video_url = video_url or video.video_url
            video.cover_url = cover_url or video.cover_url
            video.like_count = like_count
            video.comment_count = comment_count
            video.share_count = share_count
            video.publish_time = publish_time or video.publish_time
            video.raw_data = raw_data or video.raw_data
            video.last_seen_at = datetime.utcnow()
        self.session.flush()
        return video

    def list_hot(self, limit: int = 100):
        return self.session.scalars(
            select(Video).order_by(Video.like_count.desc(), Video.comment_count.desc()).limit(limit)
        ).all()

