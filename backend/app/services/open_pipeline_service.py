from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.open_pipeline import (
    KeywordVideoCommentsRequest,
    KeywordVideoCommentsResponse,
    PlatformPipelineResult,
)
from app.services.agent_async_job_service import AgentAsyncJobService
from app.services.agent_service import AgentService
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator

_PLATFORM_SKILL: dict[str, str] = {
    "douyin": "open-douyin-keyword-video-comments",
    "xiaohongshu": "open-xhs-keyword-video-comments",
}


def _build_agent_message(req: KeywordVideoCommentsRequest, platform: str) -> str:
    skill_id = _PLATFORM_SKILL[platform]
    return (
        f"/{skill_id} keyword={req.keyword} video_limit={req.video_limit}\n"
        f"请严格执行技能指南，最终在 task_complete.result 返回结构化 JSON。"
    )


class OpenPipelineService:
    def __init__(self, settings: Settings, tenant_id: str, db_session: Session | None = None) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.db_session = db_session

    async def run_keyword_video_comments(
        self,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str = "default",
    ) -> KeywordVideoCommentsResponse:
        if req.async_job:
            return self._submit_async(req, account_id=account_id)

        if self.db_session is not None and not req.force_refresh:
            coordinator = CachedCrawlCoordinator(
                self.db_session,
                self.settings,
                tenant_id=self.tenant_id,
                platform="pipeline",
                account_id=account_id,
            )
            cached = coordinator.cached_pipeline_lookup(
                keyword=req.keyword,
                platforms=list(req.platforms),
                video_limit=req.video_limit,
                force_refresh=req.force_refresh,
                cache_ttl_hours=req.cache_ttl_hours,
            )
            if cached is not None:
                payload = cached.payload
                return KeywordVideoCommentsResponse(
                    keyword=req.keyword,
                    status=str(payload.get("status") or "completed"),
                    platforms=[
                        PlatformPipelineResult(**item)
                        for item in (payload.get("platforms") or [])
                        if isinstance(item, dict)
                    ],
                    completed_at=datetime.now(timezone.utc),
                )

        platform_results: list[PlatformPipelineResult] = []
        overall_ok = True
        for platform in req.platforms:
            item = await self._run_single_platform(req, platform, account_id=account_id)
            platform_results.append(item)
            if item.status != "completed":
                overall_ok = False

        response = KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status="completed" if overall_ok else "partial",
            platforms=platform_results,
            completed_at=datetime.now(timezone.utc),
        )
        if self.db_session is not None:
            coordinator = CachedCrawlCoordinator(
                self.db_session,
                self.settings,
                tenant_id=self.tenant_id,
                platform="pipeline",
                account_id=account_id,
            )
            if overall_ok:
                coordinator.store_pipeline_result(
                    keyword=req.keyword,
                    platforms=list(req.platforms),
                    video_limit=req.video_limit,
                    payload=response.model_dump(mode="json"),
                    cache_ttl_hours=req.cache_ttl_hours,
                )
            elif req.force_refresh:
                fallback = self._pipeline_stale_fallback(coordinator, req, account_id=account_id)
                if fallback is not None:
                    return fallback
        return response

    def _pipeline_stale_fallback(
        self,
        coordinator: CachedCrawlCoordinator,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str,
    ) -> KeywordVideoCommentsResponse | None:
        params = {
            "keyword": req.keyword,
            "platforms": list(req.platforms),
            "video_limit": req.video_limit,
        }
        stale = coordinator.cache.lookup_stale("pipeline_keyword_comments", params)
        if stale is None:
            return None
        payload = stale.payload
        meta = stale.meta.model_copy(
            update={"stale_fallback": True, "refresh_error": "强制拉取未成功，已回退缓存"},
        )
        return KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status=str(payload.get("status") or "completed"),
            platforms=[
                PlatformPipelineResult(**item)
                for item in (payload.get("platforms") or [])
                if isinstance(item, dict)
            ],
            completed_at=datetime.now(timezone.utc),
            cache=meta,
        )

    async def _run_single_platform(
        self,
        req: KeywordVideoCommentsRequest,
        platform: str,
        *,
        account_id: str,
    ) -> PlatformPipelineResult:
        skill_id = _PLATFORM_SKILL.get(platform)
        if not skill_id:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                error=f"不支持的平台: {platform}",
            )

        agent = AgentService(
            self.settings,
            self.tenant_id,
            platform,
            db_session=self.db_session,
            account_id=account_id,
        )
        message = _build_agent_message(req, platform)
        done_payload: dict[str, Any] | None = None
        run_id: str | None = None

        async def consume() -> None:
            nonlocal done_payload, run_id
            async for event in agent.run_chat(
                message,
                provider=req.provider,
                headless=req.headless,
                explicit_skill_ids=[skill_id],
                mode="agent",
                run_mode="auto",
            ):
                if event.type == "session":
                    run_id = event.data.get("run_id") or run_id
                elif event.type == "done":
                    done_payload = event.data

        try:
            await asyncio.wait_for(consume(), timeout=req.timeout_seconds)
        except asyncio.TimeoutError:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                run_id=run_id,
                error=f"执行超时（>{req.timeout_seconds}s）",
            )
        except Exception as exc:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                run_id=run_id,
                error=str(exc),
            )

        status = str((done_payload or {}).get("status") or "failed")
        summary = str((done_payload or {}).get("summary") or "")
        result = (done_payload or {}).get("result")
        if not isinstance(result, dict):
            result = {}

        return PlatformPipelineResult(
            platform=platform,
            status=status,
            run_id=run_id,
            summary=summary,
            result=result,
            error="" if status == "completed" else summary or "任务未完成",
        )

    def _submit_async(
        self,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str,
    ) -> KeywordVideoCommentsResponse:
        # 异步任务按单平台提交；多平台请调用方循环或后续扩展 batch job
        platform = req.platforms[0] if req.platforms else "douyin"
        skill_id = _PLATFORM_SKILL[platform]
        message = (
            f"/{skill_id} keyword={req.keyword} video_limit={req.video_limit}\n"
            "请严格执行技能指南，最终在 task_complete.result 返回结构化 JSON。"
        )
        job = AgentAsyncJobService.get(self.settings).submit(
            tenant_id=self.tenant_id,
            platform=platform,
            account_id=account_id,
            message=message,
            provider=req.provider,
            timeout_seconds=req.timeout_seconds,
            priority=3,
        )
        return KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status="queued",
            job_id=job.job_id,
            platforms=[
                PlatformPipelineResult(platform=platform, status="queued", summary="已提交异步任务")
            ],
        )
