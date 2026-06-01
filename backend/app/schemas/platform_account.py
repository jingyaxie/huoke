from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PlatformAccountCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    label: str = Field(..., min_length=1, max_length=120)


class PlatformAccountOut(BaseModel):
    id: str
    label: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlatformAccountListResponse(BaseModel):
    items: list[PlatformAccountOut]
    total: int
    active_account_id: str = "default"


class PlatformBindingStatus(BaseModel):
    platform: str
    platform_label: str
    status: str
    message: str = ""
    cookie_count: int = 0
    vnc_url: str | None = None


class PlatformAccountBindingsOut(BaseModel):
    account_id: str
    label: str
    platforms: list[PlatformBindingStatus]


class UploadAccountStorageStateRequest(BaseModel):
    storage_state: dict[str, Any]
