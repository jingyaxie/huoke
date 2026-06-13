from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.task_platform.models.task_phase_run import TaskPhaseRun


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskPhaseRunRepository:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def add(self, row: TaskPhaseRun) -> TaskPhaseRun:
        self.session.add(row)
        return row

    def list_for_task(self, task_id: str) -> list[TaskPhaseRun]:
        return (
            self.session.query(TaskPhaseRun)
            .filter(TaskPhaseRun.task_id == task_id, TaskPhaseRun.tenant_id == self.tenant_id)
            .order_by(TaskPhaseRun.id.asc())
            .all()
        )

    def latest_for_phase(self, task_id: str, phase_id: str) -> TaskPhaseRun | None:
        return (
            self.session.query(TaskPhaseRun)
            .filter(
                TaskPhaseRun.task_id == task_id,
                TaskPhaseRun.tenant_id == self.tenant_id,
                TaskPhaseRun.phase_id == phase_id,
            )
            .order_by(TaskPhaseRun.id.desc())
            .first()
        )

    def save(self, row: TaskPhaseRun) -> TaskPhaseRun:
        self.session.add(row)
        return row

    def delete_for_task(self, task_id: str) -> None:
        (
            self.session.query(TaskPhaseRun)
            .filter(TaskPhaseRun.task_id == task_id, TaskPhaseRun.tenant_id == self.tenant_id)
            .delete(synchronize_session=False)
        )
