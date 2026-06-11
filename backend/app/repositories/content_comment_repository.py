from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select

from app.models.content_comment import ContentComment
from app.repositories.base import BaseRepository


class ContentSummaryRow:
    def __init__(
        self,
        *,
        content_id: str,
        content_url: str | None,
        comment_count: int,
        top_comment_count: int,
        last_seen_at,
    ) -> None:
        self.content_id = content_id
        self.content_url = content_url
        self.comment_count = comment_count
        self.top_comment_count = top_comment_count
        self.last_seen_at = last_seen_at


class ContentCommentRepository(BaseRepository):
    def list_content_summaries(
        self,
        *,
        platform: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ContentSummaryRow], int]:
        total = int(
            self.session.scalar(
                select(func.count(func.distinct(ContentComment.content_id)))
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
            )
            or 0
        )
        rows = self.session.execute(
            select(
                ContentComment.content_id,
                func.max(ContentComment.content_url).label("content_url"),
                func.count(ContentComment.id).label("comment_count"),
                func.sum(
                    case((ContentComment.parent_comment_id.is_(None), 1), else_=0)
                ).label("top_comment_count"),
                func.max(ContentComment.last_seen_at).label("last_seen_at"),
            )
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
            .group_by(ContentComment.content_id)
            .order_by(func.max(ContentComment.last_seen_at).desc())
            .offset(offset)
            .limit(limit)
        ).all()
        items = [
            ContentSummaryRow(
                content_id=row.content_id,
                content_url=row.content_url,
                comment_count=int(row.comment_count or 0),
                top_comment_count=int(row.top_comment_count or 0),
                last_seen_at=row.last_seen_at,
            )
            for row in rows
        ]
        return items, total

    def list_all_content_summaries(self, *, platform: str) -> list[ContentSummaryRow]:
        items, _ = self.list_content_summaries(platform=platform, offset=0, limit=1_000_000)
        return items

    def list_by_content(self, *, platform: str, content_id: str) -> list[ContentComment]:
        return list(
            self.session.scalars(
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.content_id == content_id)
                .order_by(
                    ContentComment.create_time.is_(None),
                    ContentComment.create_time.desc(),
                    ContentComment.id.desc(),
                )
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
