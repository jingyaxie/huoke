from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.open_pipeline import KeywordVideoCommentsRequest, PlatformPipelineResult
from app.schemas.skill import SkillOut
from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager
from app.services.agent_service import AgentService
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.skill_executor import SkillExecutor
from app.services.skill_failure import (
    classify_skill_failure,
    is_recoverable_failure,
    is_terminal_failure,
)
from app.services.skill_store import SkillStore

PLATFORM_KEYWORD_SKILL: dict[str, str] = {
    "douyin": "douyin-keyword-comments",
    "xiaohongshu": "xhs-keyword-comments",
    "kuaishou": "kuaishou-keyword-comments",
}

RECOVERY_SKILL_CHAIN: dict[str, list[str]] = {
    "douyin": ["check-login", "douyin-search-keyword", "douyin-comments-api"],
    "xiaohongshu": ["check-login", "xhs-search-api", "xhs-comments-api"],
    "kuaishou": ["check-login"],
}


def _keyword_skill_for_platform(platform: str) -> str:
    skill_id = PLATFORM_KEYWORD_SKILL.get(platform)
    if not skill_id:
        raise ValueError(f"平台 {platform} 未配置关键词评论 Skill")
    return skill_id


def _is_success(result: dict[str, Any]) -> bool:
    if result.get("error"):
        return False
    status = str(result.get("status") or "").lower()
    if status in {"failed", "error"}:
        return False
    if status == "completed":
        return True
    if result.get("handler") and not result.get("error"):
        return True
    return bool(result.get("results") or result.get("videos_processed"))


def _normalize_execute_result(result: dict[str, Any], *, skill_id: str) -> dict[str, Any]:
    if result.get("error") and not result.get("status"):
        result = {**result, "status": "failed"}
    if _is_success(result) and not result.get("status"):
        result = {**result, "status": "completed"}
    result.setdefault("skill_id", skill_id)
    return result


def _pipeline_result_from_keyword_builtin(
    *,
    platform: str,
    keyword: str,
    region: str | None,
    builtin_result: dict[str, Any],
    recovery_stage: str,
) -> dict[str, Any]:
    results = builtin_result.get("results") or []
    output_files = builtin_result.get("output_files") or []
    videos: list[dict] = []
    comments_by_video: list[dict] = []
    for row in results:
        if not isinstance(row, dict):
            continue
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
    for idx, path in enumerate(output_files):
        if idx < len(comments_by_video):
            comments_by_video[idx]["report_file"] = str(path)

    total_comments = sum(int(r.get("total_comments_captured") or 0) for r in results if isinstance(r, dict))
    return {
        "platform": platform,
        "keyword": keyword,
        "region": region,
        "videos": videos,
        "comments_by_video": comments_by_video,
        "output_files": [str(p) for p in output_files],
        "total_comments": total_comments,
        "recovery_stage": recovery_stage,
        "summary": builtin_result.get("summary")
        or f"关键词「{keyword}」共处理 {len(results)} 条内容，抓取 {total_comments} 条评论",
    }


class SkillRunnerService:
    """统一 Skill 执行入口：REST / Pipeline / Agent 共用。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        *,
        account_id: str = "default",
        db_session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.db_session = db_session
        self._store = SkillStore(settings)

    def get_skill(self, skill_id: str) -> SkillOut | None:
        return self._store.get(self.tenant_id, skill_id)

    async def execute(
        self,
        skill_id: str,
        params: dict[str, Any] | None = None,
        *,
        headless: bool | None = None,
        agent_fallback: bool = False,
        provider: str = "deepseek",
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        params = dict(params or {})
        skill = self.get_skill(skill_id)
        if skill is None:
            return {"status": "failed", "error": f"技能不存在: {skill_id}", "skill_id": skill_id}

        if skill.builtin_handler == "pipeline_keyword_comments":
            return await self.execute_keyword_pipeline(
                keyword=str(params.get("keyword") or ""),
                video_limit=int(params.get("video_limit") or params.get("limit") or 5),
                days=int(params.get("days") or 3),
                region=params.get("region"),
                headless=headless,
                agent_fallback=agent_fallback or bool(params.get("agent_fallback", True)),
                provider=provider,
                timeout_seconds=timeout_seconds,
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                guest_mode=bool(params.get("guest_mode", False)),
            )

        if skill.type == "instruction" and not agent_fallback:
            return {
                "status": "failed",
                "error": "instruction 技能需在 Agent 对话中执行，或设置 agent_fallback=true",
                "skill_id": skill_id,
                "type": "instruction",
            }

        if skill.type == "instruction" and agent_fallback:
            return await self._run_recovery_agent(
                task=self._build_instruction_task(skill, params),
                provider=provider,
                timeout_seconds=timeout_seconds,
                explicit_skill_ids=[skill_id],
            )

        result = await self._execute_skill_direct(
            skill,
            params,
            headless=headless,
        )
        return _normalize_execute_result(result, skill_id=skill_id)

    async def _execute_skill_direct(
        self,
        skill: SkillOut,
        params: dict[str, Any],
        *,
        headless: bool | None,
    ) -> dict[str, Any]:
        session = await self._borrow_session(headless=headless)
        pw_executor = PlaywrightToolExecutor(session, self.settings)
        executor = SkillExecutor(
            self.settings,
            self.tenant_id,
            self.platform,
            session,
            pw_executor,
            db_session=self.db_session,
        )
        try:
            return await executor.execute(skill, params)
        finally:
            await self._release_session(session)

    async def execute_keyword_pipeline(
        self,
        *,
        keyword: str,
        video_limit: int = 5,
        days: int = 3,
        region: str | None = None,
        headless: bool | None = None,
        agent_fallback: bool = True,
        provider: str = "deepseek",
        timeout_seconds: int = 600,
        force_refresh: bool = False,
        cache_ttl_hours: float = 24,
        guest_mode: bool = False,
    ) -> dict[str, Any]:
        if not keyword.strip():
            return {"status": "failed", "error": "缺少 keyword", "skill_id": "pipeline-keyword-video-comments"}

        keyword_skill_id = _keyword_skill_for_platform(self.platform)
        base_params: dict[str, Any] = {
            "keyword": keyword,
            "limit": video_limit,
            "days": days,
            "region": region,
            "show_browser": False,
            "guest_mode": guest_mode,
            "force_refresh": force_refresh,
            "cache_ttl_hours": cache_ttl_hours,
            "include_full_results": True,
        }

        skill = self.get_skill(keyword_skill_id)
        if skill is None:
            return {"status": "failed", "error": f"技能不存在: {keyword_skill_id}"}

        # T0: builtin
        result = await self._execute_skill_direct(skill, base_params, headless=headless)
        if _is_success(result):
            payload = _pipeline_result_from_keyword_builtin(
                platform=self.platform,
                keyword=keyword,
                region=region,
                builtin_result=result,
                recovery_stage="builtin",
            )
            return {
                "status": "completed",
                "skill_id": "pipeline-keyword-video-comments",
                "summary": payload["summary"],
                "result": payload,
                "recovery_stage": "builtin",
            }

        failure_type = classify_skill_failure(result)
        if is_terminal_failure(failure_type):
            return {
                "status": "failed",
                "skill_id": "pipeline-keyword-video-comments",
                "error": result.get("error") or result.get("summary") or "抓取失败",
                "failure_type": failure_type,
                "recovery_stage": "builtin",
            }

        # T1: 规则重试（可见浏览器）
        if is_recoverable_failure(failure_type):
            retry_params = {**base_params, "show_browser": True}
            retry = await self._execute_skill_direct(skill, retry_params, headless=False)
            if _is_success(retry):
                payload = _pipeline_result_from_keyword_builtin(
                    platform=self.platform,
                    keyword=keyword,
                    region=region,
                    builtin_result=retry,
                    recovery_stage="retry_show_browser",
                )
                return {
                    "status": "completed",
                    "skill_id": "pipeline-keyword-video-comments",
                    "summary": payload["summary"],
                    "result": payload,
                    "recovery_stage": "retry_show_browser",
                }
            result = retry
            failure_type = classify_skill_failure(result)

        if not agent_fallback or is_terminal_failure(failure_type):
            return {
                "status": "failed",
                "skill_id": "pipeline-keyword-video-comments",
                "error": result.get("error") or result.get("summary") or "抓取失败",
                "failure_type": failure_type,
                "recovery_stage": "retry_show_browser",
            }

        # T2: 受限 Agent Recovery
        recovery_skills = RECOVERY_SKILL_CHAIN.get(self.platform, ["check-login"])
        task = (
            f"关键词评论 Pipeline 兜底：platform={self.platform} keyword={keyword} "
            f"limit={video_limit} days={days} region={region or ''}\n"
            f"builtin 已失败：{result.get('error') or result.get('summary') or failure_type}\n"
            f"禁止再 invoke {keyword_skill_id}。\n"
            f"按序尝试：{', '.join(recovery_skills)}，逐条抓评论。\n"
            f"最终在 task_complete.result 返回结构化 JSON："
            f'{{"platform":"{self.platform}","keyword":"...","videos":[],"comments_by_video":[]}}'
        )
        agent_result = await self._run_recovery_agent(
            task=task,
            provider=provider,
            timeout_seconds=timeout_seconds,
            explicit_skill_ids=recovery_skills + ["pipeline-keyword-video-comments"],
        )
        agent_result["skill_id"] = "pipeline-keyword-video-comments"
        agent_result["recovery_stage"] = "agent_recovery"
        return agent_result

    async def _run_recovery_agent(
        self,
        *,
        task: str,
        provider: str,
        timeout_seconds: int,
        explicit_skill_ids: list[str],
    ) -> dict[str, Any]:
        agent = AgentService(
            self.settings,
            self.tenant_id,
            self.platform,
            db_session=self.db_session,
            account_id=self.account_id,
        )
        done_payload: dict[str, Any] | None = None
        run_id: str | None = None

        async def consume() -> None:
            nonlocal done_payload, run_id
            async for event in agent.run_chat(
                task,
                provider=provider,
                explicit_skill_ids=explicit_skill_ids,
                mode="agent",
                run_mode="auto",
            ):
                if event.type == "session":
                    run_id = event.data.get("run_id") or run_id
                elif event.type == "done":
                    done_payload = event.data

        try:
            await asyncio.wait_for(consume(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return {
                "status": "failed",
                "error": f"Agent 兜底超时（>{timeout_seconds}s）",
                "run_id": run_id,
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "run_id": run_id}

        status = str((done_payload or {}).get("status") or "failed")
        summary = str((done_payload or {}).get("summary") or "")
        result = (done_payload or {}).get("result")
        if not isinstance(result, dict):
            result = {}
        return {
            "status": status,
            "summary": summary,
            "result": result,
            "run_id": run_id,
            "error": "" if status == "completed" else summary or "Agent 兜底未完成",
        }

    @staticmethod
    def _build_instruction_task(skill: SkillOut, params: dict[str, Any]) -> str:
        parts = [f"/{skill.id}"]
        for key, value in params.items():
            if value is not None and value != "":
                parts.append(f"{key}={value}")
        parts.append("请严格按技能指南执行，完成后 task_complete。")
        return " ".join(parts)

    async def _borrow_session(self, *, headless: bool | None) -> AgentBrowserSession:
        manager = AgentSessionManager.get_instance()
        return await manager.create(
            self.tenant_id,
            self.platform,
            self.settings,
            account_id=self.account_id,
            headless=headless,
            auto_start=False,
        )

    @staticmethod
    async def _release_session(session: AgentBrowserSession) -> None:
        await AgentSessionManager.get_instance().close(session.session_id)

    async def run_open_pipeline_platform(
        self,
        req: KeywordVideoCommentsRequest,
    ) -> PlatformPipelineResult:
        result = await self.execute_keyword_pipeline(
            keyword=req.keyword,
            video_limit=req.video_limit,
            days=req.days,
            region=req.region,
            headless=req.headless,
            agent_fallback=True,
            provider=req.provider,
            timeout_seconds=req.timeout_seconds,
            force_refresh=req.force_refresh,
            cache_ttl_hours=req.cache_ttl_hours,
        )
        status = str(result.get("status") or "failed")
        summary = str(result.get("summary") or "")
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        return PlatformPipelineResult(
            platform=self.platform,
            status=status,
            run_id=result.get("run_id"),
            summary=summary,
            result=payload,
            error="" if status == "completed" else result.get("error") or summary or "任务未完成",
        )
