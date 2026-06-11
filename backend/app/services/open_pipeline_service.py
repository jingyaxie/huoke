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
from app.services.comment_crawler_service import CommentCrawlerService

_PLATFORM_SKILL: dict[str, str] = {
    "douyin": "open-douyin-keyword-video-comments",
    "xiaohongshu": "open-xhs-keyword-video-comments",
}

_BUILTIN_PIPELINE_PLATFORMS = frozenset({"xiaohongshu"})


def _pipeline_skill_args(req: KeywordVideoCommentsRequest) -> str:
    parts = [f"keyword={req.keyword}", f"video_limit={req.video_limit}", f"days={req.days}"]
    if req.region:
        parts.append(f"region={req.region}")
    return " ".join(parts)


def _build_agent_message(req: KeywordVideoCommentsRequest, platform: str) -> str:
    skill_id = _PLATFORM_SKILL[platform]
    return (
        f"/{skill_id} {_pipeline_skill_args(req)}\n"
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
                days=req.days,
                region=req.region,
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
                    days=req.days,
                    region=req.region,
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
            "days": req.days,
            "region": req.region,
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

    @staticmethod
    def _pipeline_result_from_crawl(
        *,
        platform: str,
        keyword: str,
        region: str | None,
        results: list[dict],
        outputs: list,
        diagnostic: str | None,
    ) -> PlatformPipelineResult:
        videos: list[dict] = []
        comments_by_video: list[dict] = []
        for row in results:
            note_url = row.get("note_url") or row.get("video_url") or ""
            note_id = row.get("content_id") or row.get("note_id") or row.get("aweme_id") or ""
            videos.append(
                {
                    "note_id": note_id,
                    "note_url": note_url,
                    "title": row.get("title") or "",
                    "author": row.get("author") or row.get("author_name") or "",
                }
            )
            comments_by_video.append(
                {
                    "note_url": note_url,
                    "note_id": note_id,
                    "comments": [
                        {
                            "comment_id": c.get("comment_id"),
                            "text": c.get("comment") or c.get("text"),
                            "username": c.get("nickname") or c.get("username"),
                            "like_count": c.get("digg_count"),
                        }
                        for c in (row.get("comments") or [])[:50]
                        if isinstance(c, dict)
                    ],
                    "total_comments_captured": row.get("total_comments_captured", 0),
                    "report_file": None,
                }
            )
        if outputs:
            for idx, path in enumerate(outputs):
                if idx < len(comments_by_video):
                    comments_by_video[idx]["report_file"] = str(path)

        total_comments = sum(int(r.get("total_comments_captured") or 0) for r in results)
        ok = bool(results)
        return PlatformPipelineResult(
            platform=platform,
            status="completed" if ok else "failed",
            summary=(
                f"关键词「{keyword}」共处理 {len(results)} 条内容，抓取 {total_comments} 条评论"
                if ok
                else (diagnostic or "未抓取到数据")
            ),
            result={
                "platform": platform,
                "keyword": keyword,
                "region": region,
                "videos": videos,
                "comments_by_video": comments_by_video,
                "output_files": [str(p) for p in outputs],
                "diagnostic": diagnostic,
            },
            error="" if ok else (diagnostic or "未抓取到数据"),
        )

    async def _run_builtin_platform(
        self,
        req: KeywordVideoCommentsRequest,
        platform: str,
        *,
        account_id: str,
    ) -> PlatformPipelineResult:
        if self.db_session is None:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                error="内置抓取需要数据库会话",
            )
        service = CommentCrawlerService(
            self.settings,
            tenant_id=self.tenant_id,
            platform=platform,
            account_id=account_id,
            session=self.db_session,
        )
        try:
            results, outputs, diagnostic, _session_meta, _meta = await service.crawl_keyword_comments(
                keyword=req.keyword,
                limit=req.video_limit,
                show_browser=req.headless is False,
                days=req.days,
                region=req.region,
                force_refresh=req.force_refresh,
                cache_ttl_hours=req.cache_ttl_hours,
            )
        except Exception as exc:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                error=str(exc),
            )
        return self._pipeline_result_from_crawl(
            platform=platform,
            keyword=req.keyword,
            region=req.region,
            results=results,
            outputs=outputs,
            diagnostic=diagnostic,
        )

    async def _run_single_platform(
        self,
        req: KeywordVideoCommentsRequest,
        platform: str,
        *,
        account_id: str,
    ) -> PlatformPipelineResult:
        if platform in _BUILTIN_PIPELINE_PLATFORMS:
            return await self._run_builtin_platform(req, platform, account_id=account_id)

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
            f"/{skill_id} {_pipeline_skill_args(req)}\n"
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
