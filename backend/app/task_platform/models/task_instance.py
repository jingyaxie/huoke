from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskInstance(Base):
    """结构化任务运行时实例。"""

    __tablename__ = "task_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    executor_id: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    current_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    adapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    compile_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
