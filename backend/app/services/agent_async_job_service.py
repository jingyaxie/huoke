from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agent_job_plan_service import build_orchestration_plan, sync_orchestration_status
from app.services.agent_service import AgentService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentAsyncJob(BaseModel):
    job_id: str
    tenant_id: str
    platform: str
    account_id: str
    message: str
    provider: str = "openai"
    mode: str = "agent"
    run_mode: str = "auto"
    auto_execute: bool = True
    auto_restart: bool = True
    timeout_seconds: int = 600
    max_retries: int = 1
    priority: int = 5
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)
    status: str = "queued"
    stage: str = "plan"
    retry_count: int = 0
    run_id: str | None = None
    session_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    dead_letter_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class _JobKey:
    tenant_id: str
    job_id: str


class AgentAsyncJobService:
    _instance: "AgentAsyncJobService | None" = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "tenants"
        self.root.mkdir(parents=True, exist_ok=True)
        self._running_jobs: dict[str, asyncio.Task[None]] = {}
        self._queue: asyncio.PriorityQueue[tuple[int, float, str, str]] = asyncio.PriorityQueue()
        self._workers_started = False
        self._workers: list[asyncio.Task[None]] = []
        self._concurrency = max(1, int(getattr(settings, "agent_job_concurrency", 2)))

    @classmethod
    def get(cls, settings: Settings) -> "AgentAsyncJobService":
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        for idx in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(idx)))

    def _path(self, tenant_id: str, job_id: str) -> Path:
        p = self.root / tenant_id / "agent_jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{job_id}.json"

    def save(self, job: AgentAsyncJob) -> None:
        job.updated_at = _utc_now()
        if job.created_at is None:
            job.created_at = job.updated_at
        self._path(job.tenant_id, job.job_id).write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_job(self, tenant_id: str, job_id: str) -> AgentAsyncJob | None:
        path = self._path(tenant_id, job_id)
        if not path.exists():
            return None
        job = AgentAsyncJob.model_validate(json.loads(path.read_text(encoding="utf-8")))
        self._ensure_orchestration(job)
        return job

    def _ensure_orchestration(self, job: AgentAsyncJob) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        old_orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else None
        orch = build_orchestration_plan(job.message, settings=self.settings)
        if job.stage or job.status not in ("pending",):
            orch = sync_orchestration_status(orch, job_stage=job.stage, job_status=job.status)
        stale = (
            old_orch is None
            or old_orch.get("source") == "inferred"
            or old_orch.get("template_id") != orch.get("template_id")
            or (orch.get("outreach_policy") and not old_orch.get("outreach_policy"))
        )
        if stale:
            job.result = {**result, "orchestration": orch, "pipeline": orch.get("steps", [])}
            self.save(job)

    def list_jobs(self, tenant_id: str, limit: int = 50) -> list[AgentAsyncJob]:
        d = self.root / tenant_id / "agent_jobs"
        if not d.exists():
            return []
        items: list[AgentAsyncJob] = []
        for p in d.glob("*.json"):
            try:
                items.append(AgentAsyncJob.model_validate(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        items.sort(key=lambda x: x.updated_at or x.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return items[: max(1, limit)]

    async def _post_webhook(self, job: AgentAsyncJob) -> None:
        if not job.webhook_url:
            return
        payload = {
            "job_id": job.job_id,
            "status": job.status,
            "stage": job.stage,
            "retry_count": job.retry_count,
            "run_id": job.run_id,
            "session_id": job.session_id,
            "result": job.result,
            "error": job.error,
            "dead_letter_reason": job.dead_letter_reason,
            "updated_at": (job.updated_at or _utc_now()).isoformat(),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(job.webhook_url, json=payload, headers=job.webhook_headers)

    @staticmethod
    def _append_progress(job: AgentAsyncJob, event_type: str, data: dict[str, Any]) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        events = result.get("progress_events")
        if not isinstance(events, list):
            events = []
        label = AgentAsyncJobService._progress_label(event_type, data)
        events.append(
            {
                "at": _utc_now().isoformat(),
                "type": event_type,
                "label": label,
                "data": data,
            }
        )
        result["progress_events"] = events[-120:]
        job.result = result

    @staticmethod
    def _progress_label(event_type: str, data: dict[str, Any]) -> str:
        if event_type == "session":
            return "Agent 会话已建立"
        if event_type == "step":
            return f"Agent 步骤 {data.get('step', '?')}/{data.get('max_steps', '?')}"
        if event_type == "tool_start":
            return f"调用工具 · {data.get('tool') or data.get('name') or 'unknown'}"
        if event_type == "tool_result":
            tool = data.get("tool") or data.get("name") or "tool"
            ok = data.get("ok", True)
            return f"工具完成 · {tool} ({'成功' if ok else '失败'})"
        if event_type == "status":
            return str(data.get("message") or data.get("status") or "状态更新")
        if event_type == "plan":
            return "生成执行计划"
        if event_type == "done":
            return f"执行结束 · {data.get('status') or 'done'}"
        if event_type == "error":
            return f"错误 · {data.get('message') or 'unknown'}"
        return event_type

    @staticmethod
    def _apply_orchestration(job: AgentAsyncJob, settings: Settings) -> None:
        orch = job.result.get("orchestration") if isinstance(job.result, dict) else None
        if not isinstance(orch, dict):
            orch = build_orchestration_plan(job.message, settings=settings)
        orch = dict(orch)
        orch["is_preview"] = job.status in {"pending", "queued"}
        orch["execution_mode"] = "agent_async"
        if job.status in {"pending", "queued"}:
            orch["execution_note"] = (
                "当前为编排预览，尚未执行。"
                "5 步模板在任务中心才会逐步运行；"
                "本页 Agent 任务仅后台对话执行，不会逐步跑 lead-acquisition executor。"
            )
        elif job.status == "running":
            orch["execution_note"] = "Agent 正在后台执行，下方「处理过程」实时更新。"
        job.result = {
            **(job.result if isinstance(job.result, dict) else {}),
            "orchestration": sync_orchestration_status(
                orch,
                job_stage=job.stage,
                job_status=job.status,
            ),
            "pipeline": sync_orchestration_status(
                orch,
                job_stage=job.stage,
                job_status=job.status,
            ).get("steps", []),
        }

    async def _run_job(self, job_key: _JobKey, settings: Settings) -> None:
        job = self.get_job(job_key.tenant_id, job_key.job_id)
        if job is None:
            return
        while True:
            try:
                job.status = "running"
                job.stage = "plan"
                self._apply_orchestration(job, settings)
                self.save(job)

                job.stage = "execute"
                self._apply_orchestration(job, settings)
                self.save(job)
                agent = AgentService(
                    settings,
                    job.tenant_id,
                    job.platform,
                    account_id=job.account_id,
                )
                done_data: dict[str, Any] | None = None
                last_message = ""
                async for event in agent.run_chat(
                    job.message,
                    run_id=job.run_id,
                    session_id=job.session_id,
                    provider=job.provider,  # type: ignore[arg-type]
                    mode=job.mode,  # type: ignore[arg-type]
                    run_mode=job.run_mode,  # type: ignore[arg-type]
                ):
                    if event.type == "session":
                        job.run_id = event.data.get("run_id") or job.run_id
                        job.session_id = event.data.get("session_id") or job.session_id
                        self._append_progress(job, event.type, dict(event.data))
                        self._apply_orchestration(job, settings)
                        self.save(job)
                    elif event.type in {"step", "tool_start", "tool_result", "status", "plan"}:
                        self._append_progress(job, event.type, dict(event.data))
                        self._apply_orchestration(job, settings)
                        self.save(job)
                    elif event.type == "message":
                        content = str(event.data.get("content") or "").strip()
                        if content:
                            last_message = content
                    elif event.type == "done":
                        done_data = event.data
                        self._append_progress(job, event.type, dict(event.data))
                        self.save(job)
                    elif event.type == "error":
                        self._append_progress(job, event.type, dict(event.data))
                        self.save(job)

                job.stage = "validate"
                self._apply_orchestration(job, settings)
                run = agent.get_run(job.run_id or "")
                validation_report = run.validation_report if run else {}
                status = str((done_data or {}).get("status") or "failed")
                summary = str((done_data or {}).get("summary") or last_message or "")
                job.result = {
                    **(job.result if isinstance(job.result, dict) else {}),
                    "status": status,
                    "summary": summary,
                    "done": done_data or {},
                    "validation_report": validation_report,
                    "review_report": (run.review_report if run else {}),
                }
                job.stage = "finalize"
                self._apply_orchestration(job, settings)
                if status == "completed":
                    job.status = "completed"
                    job.error = ""
                    self.save(job)
                    await self._post_webhook(job)
                    return
                job.error = summary or status
                if job.auto_restart and job.retry_count < job.max_retries:
                    job.retry_count += 1
                    job.status = "retrying"
                    job.run_id = None
                    self.save(job)
                    await asyncio.sleep(2)
                    continue
                job.status = "failed" if not job.auto_restart else "dead_letter"
                if job.status == "dead_letter":
                    job.dead_letter_reason = job.error
                self.save(job)
                await self._post_webhook(job)
                return
            except asyncio.CancelledError:
                job.status = "cancelled"
                self._apply_orchestration(job, settings)
                self.save(job)
                return
            except Exception as exc:
                job.retry_count += 1
                job.error = str(exc)
                if job.auto_restart and job.retry_count <= job.max_retries:
                    job.status = "retrying"
                    job.run_id = None
                    self.save(job)
                    await asyncio.sleep(2)
                    continue
                job.status = "failed" if not job.auto_restart else "dead_letter"
                if job.status == "dead_letter":
                    job.dead_letter_reason = str(exc)
                self.save(job)
                await self._post_webhook(job)
                return

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            priority, _, tenant_id, job_id = await self._queue.get()
            _ = priority, worker_id
            key = _JobKey(tenant_id=tenant_id, job_id=job_id)
            task = asyncio.create_task(self._run_job(key, self.settings))
            self._running_jobs[job_id] = task
            try:
                await task
            finally:
                self._running_jobs.pop(job_id, None)
                self._queue.task_done()

    def submit(
        self,
        *,
        tenant_id: str,
        platform: str,
        account_id: str,
        message: str,
        provider: str = "openai",
        mode: str = "agent",
        run_mode: str = "auto",
        auto_execute: bool = True,
        auto_restart: bool = True,
        timeout_seconds: int = 600,
        max_retries: int = 1,
        priority: int = 5,
        webhook_url: str | None = None,
        webhook_headers: dict[str, str] | None = None,
    ) -> AgentAsyncJob:
        self._ensure_workers()
        orch = build_orchestration_plan(message, settings=self.settings)
        job = AgentAsyncJob(
            job_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            message=message,
            provider=provider,
            mode=mode,
            run_mode=run_mode,
            auto_execute=bool(auto_execute),
            auto_restart=bool(auto_restart),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            priority=max(1, min(10, int(priority))),
            webhook_url=webhook_url,
            webhook_headers=webhook_headers or {},
            status="queued" if auto_execute else "pending",
            created_at=_utc_now(),
            updated_at=_utc_now(),
            result={
                "orchestration": orch,
                "pipeline": orch.get("steps", []),
            },
        )
        self.save(job)
        if auto_execute:
            self._queue.put_nowait((job.priority, time.time(), tenant_id, job.job_id))
        return job

    def execute(self, tenant_id: str, job_id: str) -> AgentAsyncJob | None:
        """将 pending 任务入队执行。"""
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return None
        if job.status != "pending":
            raise ValueError("仅待执行状态的任务可启动")
        self._ensure_workers()
        job.status = "queued"
        job.auto_execute = True
        self.save(job)
        self._queue.put_nowait((job.priority, time.time(), tenant_id, job.job_id))
        return job

    def cancel(self, tenant_id: str, job_id: str) -> bool:
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return False
        t = self._running_jobs.get(job_id)
        if t and not t.done():
            t.cancel()
        job.status = "cancelled"
        self.save(job)
        return True
