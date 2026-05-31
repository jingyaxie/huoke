from sqlalchemy import select

from app.models.author import Author
from app.repositories.base import BaseRepository


class AuthorRepository(BaseRepository):
    def get_by_douyin_user_id(self, douyin_user_id: str | None) -> Author | None:
        if not douyin_user_id:
            return None
        return self.session.scalar(select(Author).where(Author.douyin_user_id == douyin_user_id))

    def get_by_name(self, name: str) -> Author | None:
        return self.session.scalar(select(Author).where(Author.name == name))

    def upsert(
        self,
        *,
        douyin_user_id: str | None,
        name: str,
        avatar_url: str | None = None,
        profile_url: str | None = None,
    ) -> Author:
        author = self.get_by_douyin_user_id(douyin_user_id) or (self.get_by_name(name) if name else None)
        if author is None:
            author = Author(
                douyin_user_id=douyin_user_id,
                name=name,
                avatar_url=avatar_url,
                profile_url=profile_url,
            )
            self.session.add(author)
        else:
            author.douyin_user_id = author.douyin_user_id or douyin_user_id
            author.name = name or author.name
            author.avatar_url = avatar_url or author.avatar_url
            author.profile_url = profile_url or author.profile_url
        self.session.flush()
        return author

