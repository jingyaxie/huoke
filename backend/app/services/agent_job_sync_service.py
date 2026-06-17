from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob
from app.services.lead_evaluation_service import accept_evaluation_result
from app.services.task_sandbox_service import TaskSandboxService

SYNC_SCHEMA_VERSION = "huoke.agent_job_sync.v1"
LEAD_EVALUATION_SCHEMA = "huoke.lead_evaluation.v1"


def lead_evaluation_from_job_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
    brief = orch.get("task_brief") if isinstance(orch.get("task_brief"), dict) else {}
    constraints = brief.get("constraints") if isinstance(brief.get("constraints"), dict) else {}
    spec = constraints.get("lead_evaluation")
    if isinstance(spec, dict) and spec.get("schema") == LEAD_EVALUATION_SCHEMA:
        return spec
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sign_sync_payload(payload: dict[str, Any], secret: str, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    body = _json_dumps(payload)
    digest = hmac.new(str(secret or "").encode("utf-8"), f"{ts}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Huoke-Sync-Schema": SYNC_SCHEMA_VERSION,
        "X-Huoke-Sync-Timestamp": ts,
        "X-Huoke-Sync-Signature": f"sha256={digest}",
    }


def verify_sync_signature(payload: dict[str, Any], secret: str, timestamp: str, signature: str) -> bool:
    expected = sign_sync_payload(payload, secret, timestamp=timestamp)["X-Huoke-Sync-Signature"]
    return hmac.compare_digest(expected, signature)


class AgentJobSyncService:
    """Build the stable external synchronization contract for async jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_payload(
        self,
        job: AgentAsyncJob,
        *,
        event: str,
        db_session: Session | None = None,
    ) -> dict[str, Any]:
        result = job.result if isinstance(job.result, dict) else {}
        supervisor_state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        data_snapshot = result.get("data_snapshot") if isinstance(result.get("data_snapshot"), dict) else {}
        progress = data_snapshot.get("progress") if isinstance(data_snapshot.get("progress"), dict) else {}
        task_ledger = result.get("task_ledger") if isinstance(result.get("task_ledger"), dict) else {}
        sandbox = self._sandbox_payload(job)
        leads = sandbox.get("leads") or []
        outreach_events = sandbox.get("outreach_events") or []
        crawl_batches = sandbox.get("crawl_batches") or []
        captured_comments = self._captured_comments_payload(
            job,
            supervisor_state,
            outreach_events,
            db_session=db_session,
        )

        correlation = job.correlation if isinstance(job.correlation, dict) else {}
        payload: dict[str, Any] = {
            "schema": SYNC_SCHEMA_VERSION,
            "event": event,
            "emitted_at": _utc_now_iso(),
            "job": {
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "platform": job.platform,
                "account_id": job.account_id,
                "status": job.status,
                "stage": job.stage,
                "retry_count": int(job.retry_count or 0),
                "run_id": job.run_id,
                "session_id": job.session_id,
                "message": job.message,
                "error": job.error,
                "dead_letter_reason": job.dead_letter_reason,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            },
            "progress": {
                "target_leads": int(progress.get("target_leads") or supervisor_state.get("round_target_leads") or 0),
                "leads_collected": int(progress.get("leads_collected") or supervisor_state.get("leads_collected") or 0),
                "total_leads_collected": int(supervisor_state.get("total_leads_collected") or progress.get("leads_collected") or 0),
                "comments_captured": int(supervisor_state.get("comments_captured") or sandbox.get("summary", {}).get("crawl_comments_total") or 0),
                "comments_evaluated": int(supervisor_state.get("comments_evaluated") or 0),
                "leads_qualified": int(supervisor_state.get("leads_qualified") or 0),
                "completion_outcome": result.get("completion_outcome") or supervisor_state.get("completion_outcome"),
                "resume_at": supervisor_state.get("resume_at"),
                "wake_reason": supervisor_state.get("wake_reason"),
                "next_action": supervisor_state.get("next_action"),
            },
            "stats": {
                "leads_total": len(leads),
                "outreach_total": len(outreach_events),
                "crawl_batches_total": len(crawl_batches),
                "outreach_ok": int(task_ledger.get("total_outreach_ok") or sandbox.get("summary", {}).get("outreach_ok") or 0),
                "outreach_failed": int(sandbox.get("summary", {}).get("outreach_failed") or 0),
            },
            "leads": leads,
            "outreach_events": outreach_events,
            "crawl_batches": crawl_batches,
            "captured_comments": captured_comments,
            "summary": {
                "text": result.get("summary") or "",
                "orchestration": result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {},
                "progress_events": (result.get("progress_events") or [])[-20:] if isinstance(result.get("progress_events"), list) else [],
                "task_ledger": task_ledger,
            },
        }
        if correlation:
            payload["correlation"] = correlation
        lead_evaluation = lead_evaluation_from_job_result(result)
        if lead_evaluation:
            payload["lead_evaluation"] = lead_evaluation
        return payload

    def headers_for(self, payload: dict[str, Any]) -> dict[str, str]:
        return sign_sync_payload(payload, self.settings.huoke_bridge_secret)

    def _captured_comments_payload(
        self,
        job: AgentAsyncJob,
        supervisor_state: dict[str, Any],
        outreach_events: list[dict[str, Any]],
        *,
        db_session: Session | None,
    ) -> list[dict[str, Any]]:
        if db_session is None:
            return []

        from app.repositories.content_comment_repository import ContentCommentRepository

        evaluation_cache = supervisor_state.get("evaluation_cache")
        if not isinstance(evaluation_cache, dict):
            evaluation_cache = {}

        platform = str(job.platform or "douyin")
        repo = ContentCommentRepository(db_session, job.tenant_id)
        eval_spec = lead_evaluation_from_job_result(job.result if isinstance(job.result, dict) else {}) or {}
        outreach_by_comment = self._outreach_by_comment(outreach_events)
        scoped_comment_ids = self._job_scoped_comment_ids(
            job,
            supervisor_state,
            outreach_events,
            db_session=db_session,
        )
        if scoped_comment_ids is None or not scoped_comment_ids:
            return []

        records = repo.list_by_comment_ids(
            platform=platform,
            comment_ids=sorted(scoped_comment_ids),
            limit=500,
        )
        record_map = {str(row.comment_id): row for row in records}
        rows: list[dict[str, Any]] = []
        for comment_id in sorted(scoped_comment_ids):
            evaluation = evaluation_cache.get(comment_id)
            if not isinstance(evaluation, dict):
                evaluation = {}
            rows.append(
                self._serialize_captured_comment_row(
                    str(comment_id),
                    evaluation,
                    record=record_map.get(str(comment_id)),
                    outreach=outreach_by_comment.get(str(comment_id), {}),
                    eval_spec=eval_spec,
                )
            )

        rows.sort(key=lambda item: float(item.get("evaluation_score") or 0), reverse=True)
        return rows

    @staticmethod
    def _outreach_by_comment(outreach_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        outreach_by_comment: dict[str, dict[str, Any]] = {}
        for event in outreach_events:
            if not isinstance(event, dict):
                continue
            comment_id = str(event.get("comment_id") or "").strip()
            if not comment_id:
                continue
            bucket = outreach_by_comment.setdefault(comment_id, {})
            action = str(event.get("action") or "").strip().lower()
            if action == "reply" and event.get("reply_text"):
                bucket["reply_content"] = str(event.get("reply_text") or "")
            if action == "dm" and event.get("reply_text"):
                bucket["dm_content"] = str(event.get("reply_text") or "")
            if str(event.get("status") or "").lower() == "ok":
                bucket["executed_at"] = event.get("created_at") or bucket.get("executed_at")
        return outreach_by_comment

    @staticmethod
    def _serialize_captured_comment_row(
        comment_id: str,
        evaluation: dict[str, Any],
        *,
        record: Any | None,
        outreach: dict[str, Any],
        eval_spec: dict[str, Any],
    ) -> dict[str, Any]:
        create_time = record.create_time if record is not None else None
        comment_at = ""
        if create_time:
            try:
                comment_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                comment_at = ""
        elif record is not None and record.last_seen_at:
            comment_at = record.last_seen_at.isoformat()
        return {
            "id": str(comment_id),
            "comment_id": str(comment_id),
            "nickname": (record.nickname if record is not None else None) or "—",
            "comment_content": (record.comment_text if record is not None else None)
            or str(evaluation.get("reason") or ""),
            "comment_at": comment_at,
            "video_title": "",
            "video_url": (record.content_url if record is not None else None) or "",
            "content_id": (record.content_id if record is not None else None) or "",
            "is_precise": accept_evaluation_result(evaluation, eval_spec) if eval_spec else bool(
                evaluation.get("worth_outreach")
            ),
            "evaluation_score": float(evaluation.get("score") or 0),
            "evaluation_reason": str(evaluation.get("reason") or ""),
            "reply_content": outreach.get("reply_content") or "",
            "dm_content": outreach.get("dm_content") or "",
            "executed_at": outreach.get("executed_at") or "",
        }

    def _job_content_ids(self, job: AgentAsyncJob, supervisor_state: dict[str, Any]) -> set[str]:
        content_ids = {
            str(x).strip()
            for key in ("job_content_ids", "watched_content_ids")
            for x in (supervisor_state.get(key) or [])
            if str(x).strip()
        }
        result = job.result if isinstance(job.result, dict) else {}
        for cycle in result.get("supervisor_cycles") or []:
            if not isinstance(cycle, dict):
                continue
            params = cycle.get("params") if isinstance(cycle.get("params"), dict) else {}
            content_id = str(params.get("content_id") or "").strip()
            if content_id:
                content_ids.add(content_id)
        return content_ids

    def _job_scoped_comment_ids(
        self,
        job: AgentAsyncJob,
        supervisor_state: dict[str, Any],
        outreach_events: list[dict[str, Any]],
        *,
        db_session: Session,
    ) -> set[str] | None:
        explicit = supervisor_state.get("job_evaluation_comment_ids")
        if isinstance(explicit, list) and explicit:
            return {str(x).strip() for x in explicit if str(x).strip()}

        evaluation_cache = supervisor_state.get("evaluation_cache")
        if isinstance(evaluation_cache, dict) and evaluation_cache:
            evaluated_ids = {str(k).strip() for k in evaluation_cache if str(k).strip()}
            if evaluated_ids:
                content_ids = self._job_content_ids(job, supervisor_state)
                if content_ids:
                    from app.repositories.content_comment_repository import ContentCommentRepository

                    repo = ContentCommentRepository(db_session, job.tenant_id)
                    rows = repo.list_by_content_ids(
                        platform=str(job.platform or "douyin"),
                        content_ids=sorted(content_ids),
                    )
                    content_comment_ids = {str(row.comment_id) for row in rows}
                    scoped = evaluated_ids & content_comment_ids
                    if scoped:
                        return scoped
                return evaluated_ids

        content_ids = self._job_content_ids(job, supervisor_state)

        scoped: set[str] = set()

        for event in outreach_events:
            if not isinstance(event, dict):
                continue
            comment_id = str(event.get("comment_id") or "").strip()
            if comment_id:
                scoped.add(comment_id)

        if scoped:
            return scoped
        if content_ids:
            return set()
        return None

    def _sandbox_payload(self, job: AgentAsyncJob) -> dict[str, Any]:
        sandbox = TaskSandboxService(self.settings, job.tenant_id)
        manifest = sandbox.load_manifest(job.job_id)
        conn = sandbox.connect(job.job_id)
        if manifest is None or conn is None:
            return {"available": False, "summary": {}, "leads": [], "outreach_events": [], "crawl_batches": []}
        try:
            return {
                "available": True,
                "summary": self._summary(conn, manifest),
                "leads": self._rows(conn, "leads", limit=500),
                "outreach_events": self._rows(conn, "outreach_events", limit=500),
                "crawl_batches": self._rows(conn, "crawl_batches", limit=100),
            }
        finally:
            conn.close()

    def _summary(self, conn: sqlite3.Connection, manifest: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "job_id": manifest.get("job_id"),
            "tables": list(manifest.get("tables") or []),
            "leads_total": self._count(conn, "leads"),
            "outreach_ok": self._count(conn, "outreach_events", "status = 'ok'"),
            "outreach_failed": self._count(conn, "outreach_events", "status = 'failed'"),
            "crawl_batches": self._count(conn, "crawl_batches"),
            "crawl_comments_total": 0,
        }
        try:
            row = conn.execute("SELECT COALESCE(SUM(comments_captured), 0) FROM crawl_batches WHERE status = 'ok'").fetchone()
            summary["crawl_comments_total"] = int(row[0] if row else 0)
        except sqlite3.Error:
            pass
        return summary

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str, where: str | None = None) -> int:
        try:
            sql = f"SELECT COUNT(*) FROM {table}"
            if where:
                sql = f"{sql} WHERE {where}"
            return int(conn.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return 0

    @staticmethod
    def _rows(conn: sqlite3.Connection, table: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            cur = conn.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT ?", (limit,))
            names = [d[0] for d in cur.description or []]
            return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]
        except sqlite3.Error:
            return []
