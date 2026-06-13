from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.task_platform.models.task_instance import TaskInstance


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskInstanceRepository:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def add(self, row: TaskInstance) -> TaskInstance:
        self.session.add(row)
        return row

    def get(self, task_id: str) -> TaskInstance | None:
        return (
            self.session.query(TaskInstance)
            .filter(TaskInstance.id == task_id, TaskInstance.tenant_id == self.tenant_id)
            .one_or_none()
        )

    def list(
        self,
        *,
        status: str | None = None,
        template_id: str | None = None,
        platform: str | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TaskInstance], int]:
        q = self.session.query(TaskInstance).filter(TaskInstance.tenant_id == self.tenant_id)
        if status:
            q = q.filter(TaskInstance.status == status)
        if template_id:
            q = q.filter(TaskInstance.template_id == template_id)
        if platform:
            q = q.filter(TaskInstance.platform == platform)
        if source:
            q = q.filter(TaskInstance.source == source)
        total = q.count()
        rows = (
            q.order_by(TaskInstance.created_at.desc())
            .offset(max(0, offset))
            .limit(min(max(1, limit), 200))
            .all()
        )
        return rows, total

    def save(self, row: TaskInstance) -> TaskInstance:
        row.updated_at = _utc_now_naive()
        self.session.add(row)
        return row

    def delete(self, task_id: str) -> bool:
        row = self.get(task_id)
        if row is None:
            return False
        self.session.delete(row)
        return True

    @staticmethod
    def list_due_scheduled(session: Session, *, limit: int = 50) -> list[TaskInstance]:
        now = _utc_now_naive()
        return (
            session.query(TaskInstance)
            .filter(TaskInstance.status == "scheduled")
            .filter(TaskInstance.scheduled_at.isnot(None))
            .filter(TaskInstance.scheduled_at <= now)
            .order_by(TaskInstance.scheduled_at.asc())
            .limit(max(1, min(limit, 200)))
            .all()
        )

    @staticmethod
    def list_pending_execution(session: Session, *, limit: int = 200) -> list[TaskInstance]:
        return (
            session.query(TaskInstance)
            .filter(TaskInstance.status.in_(["queued", "retrying"]))
            .order_by(TaskInstance.updated_at.asc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
