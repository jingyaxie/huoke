from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob
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

    def build_payload(self, job: AgentAsyncJob, *, event: str) -> dict[str, Any]:
        result = job.result if isinstance(job.result, dict) else {}
        supervisor_state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        data_snapshot = result.get("data_snapshot") if isinstance(result.get("data_snapshot"), dict) else {}
        progress = data_snapshot.get("progress") if isinstance(data_snapshot.get("progress"), dict) else {}
        task_ledger = result.get("task_ledger") if isinstance(result.get("task_ledger"), dict) else {}
        sandbox = self._sandbox_payload(job)
        leads = sandbox.get("leads") or []
        outreach_events = sandbox.get("outreach_events") or []
        crawl_batches = sandbox.get("crawl_batches") or []

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
