from datetime import datetime

from app.schemas.common import ORMBaseModel


class AuthorOut(ORMBaseModel):
    id: int
    platform: str
    platform_user_id: str | None
    name: str
    avatar_url: str | None
    profile_url: str | None
    created_at: datetime
    updated_at: datetime
