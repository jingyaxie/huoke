from __future__ import annotations

import httpx

from app.task_platform.models.task_instance import TaskInstance
from app.task_platform.schemas.events import TaskEventType, TaskWebhookPayload


class TaskEventBus:
    async def emit(
        self,
        event: TaskEventType,
        instance: TaskInstance,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        if not instance.webhook_url:
            return
        payload = TaskWebhookPayload(
            event=event,
            task_id=instance.id,
            template_id=instance.template_id,
            status=instance.status,
            current_phase=instance.current_phase,
            progress=dict(instance.progress or {}),
            result=result if result is not None else instance.result,
            error=error or instance.error,
            external_ref=instance.external_ref,
        )
        headers = dict(instance.webhook_headers or {})
        headers.setdefault("Content-Type", "application/json")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(instance.webhook_url, json=payload.model_dump(mode="json"), headers=headers)
        except Exception:
            # Webhook 失败不阻断主流程
            return
