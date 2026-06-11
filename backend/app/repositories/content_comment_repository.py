from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.models.content_comment import ContentComment
from app.repositories.base import BaseRepository


class ContentCommentRepository(BaseRepository):
    def list_by_content(self, *, platform: str, content_id: str) -> list[ContentComment]:
        return list(
            self.session.scalars(
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.content_id == content_id)
                .order_by(ContentComment.create_time.desc().nullslast(), ContentComment.id.desc())
            ).all()
        )

    def get_by_comment_id(self, *, platform: str, content_id: str, comment_id: str) -> ContentComment | None:
        return self.session.scalar(
            select(ContentComment)
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
            .where(ContentComment.content_id == content_id)
            .where(ContentComment.comment_id == comment_id)
            .limit(1)
        )

    def upsert_comment(
        self,
        *,
        platform: str,
        content_id: str,
        comment_id: str,
        parent_comment_id: str | None,
        nickname: str,
        comment_text: str,
        digg_count: int,
        create_time: int | None,
        content_url: str | None,
        raw_data: dict | None,
        now: datetime,
    ) -> tuple[ContentComment, bool, bool]:
        row = self.get_by_comment_id(platform=platform, content_id=content_id, comment_id=comment_id)
        if row is None:
            row = ContentComment(
                tenant_id=self.tenant_id,
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
                nickname=nickname,
                comment_text=comment_text,
                digg_count=digg_count,
                create_time=create_time,
                content_url=content_url,
                raw_data=raw_data,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(row)
            self.session.flush()
            return row, True, False

        changed = (
            row.nickname != nickname
            or row.comment_text != comment_text
            or int(row.digg_count or 0) != int(digg_count or 0)
            or row.parent_comment_id != parent_comment_id
        )
        row.nickname = nickname
        row.comment_text = comment_text
        row.digg_count = digg_count
        row.create_time = create_time or row.create_time
        row.parent_comment_id = parent_comment_id
        row.content_url = content_url or row.content_url
        row.raw_data = raw_data or row.raw_data
        row.last_seen_at = now
        self.session.flush()
        return row, False, changed
