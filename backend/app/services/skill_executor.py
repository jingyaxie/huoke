from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.antibot import LoginRequiredError
from app.platforms.registry import get_session_store
from app.schemas.skill import SkillOut
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.crawl_service import CrawlService
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.agent_browser_session import AgentBrowserSession

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _coerce_param(value: Any, param_type: str) -> Any:
    if value is None:
        return None
    if param_type == "integer":
        return int(value)
    if param_type == "number":
        return float(value)
    if param_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
    return str(value)


def _resolve_params(skill: SkillOut, raw_args: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for param in skill.parameters:
        if param.name in raw_args:
            resolved[param.name] = _coerce_param(raw_args[param.name], param.type)
        elif param.default is not None:
            resolved[param.name] = param.default
        elif param.required:
            raise ValueError(f"缺少必填参数: {param.name}")
    for key, value in raw_args.items():
        if key not in resolved:
            resolved[key] = value
    return resolved


def _interpolate(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in params:
                return match.group(0)
            return str(params[key])

        return _TEMPLATE_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, params) for item in value]
    return value


class SkillExecutor:
    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        session: AgentBrowserSession,
        pw_executor: PlaywrightToolExecutor,
        db_session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.session = session
        self.pw_executor = pw_executor
        self.db_session = db_session

    async def execute(self, skill: SkillOut, raw_args: dict[str, Any]) -> dict[str, Any]:
        try:
            params = _resolve_params(skill, raw_args)
            if skill.type == "instruction":
                return await self._execute_instruction(skill, params)
            if skill.type == "actions":
                return await self._execute_actions(skill, params)
            if skill.type == "builtin":
                return await self._execute_builtin(skill, params)
            return {"error": f"未知技能类型: {skill.type}"}
        except LoginRequiredError as exc:
            store = get_session_store(self.settings, self.platform)
            status = store.login_status(self.tenant_id, self.session.account_id)
            return {
                "error": str(exc),
                "code": "binding_required",
                "tenant_id": self.tenant_id,
                "account_id": self.session.account_id,
                "platform": self.platform,
                "binding_status": status.get("status", "missing"),
                "bind_api": (
                    f"/api/accounts/{self.session.account_id}/platforms/{self.platform}/server-login"
                ),
                "bindings_api": f"/api/accounts/{self.session.account_id}/bindings",
            }

    async def _execute_instruction(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        instructions = _interpolate(skill.content, params)
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "type": "instruction",
            "status": "activated",
            "instructions": instructions,
            "parameters": params,
            "message": f"技能「{skill.name}」已激活，请严格按 instructions 继续执行浏览器操作",
        }

    async def _execute_actions(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        if not skill.actions:
            return {"error": "该技能未配置 actions 步骤"}
        step_results: list[dict[str, Any]] = []
        last_result: dict[str, Any] = {}
        for idx, action in enumerate(skill.actions, start=1):
            tool = action.tool
            args = _interpolate(dict(action.args), params)
            result, _ = await self.pw_executor.execute(tool, args)
            entry = {"step": idx, "tool": tool, "args": args, "result": result}
            step_results.append(entry)
            last_result = result
            if result.get("error"):
                return {
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "type": "actions",
                    "status": "failed",
                    "failed_step": idx,
                    "steps": step_results,
                    "error": result["error"],
                }
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "type": "actions",
            "status": "completed",
            "steps": step_results,
            "result": last_result,
        }

    async def _execute_builtin(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        handler = skill.builtin_handler
        if handler == "login_status":
            store = get_session_store(self.settings, self.platform)
            status = store.login_status(self.tenant_id, self.session.account_id)
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": status.get("status"),
                "message": status.get("message"),
            }
        if handler == "crawl_hot":
            if self.db_session is None:
                return {"error": "数据库会话不可用，无法执行 crawl_hot"}
            limit = int(params.get("limit", 50))
            result = await CrawlService(
                self.db_session,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
            ).crawl_hot(limit=limit)
            self.db_session.commit()
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "videos_crawled": result.total,
                "snapshot_date": result.snapshot_date,
            }
        if handler == "crawl_video_comments":
            video_url = params.get("video_url") or params.get("url")
            if not video_url:
                return {"error": "缺少参数 video_url"}
            show_browser = bool(params.get("show_browser", False))
            payload, output = await CommentCrawlerService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
            ).crawl_video_comments(str(video_url), show_browser=show_browser)
            captured = payload.get("total_comments_captured", 0)
            api_total = payload.get("api_total_top_comments")
            summary = f"已抓取 {captured} 条评论"
            if api_total is not None:
                summary += f"（接口总数 {api_total}）"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "summary": summary,
                "video_url": payload.get("video_url") or payload.get("note_url") or video_url,
                "total_comments_captured": captured,
                "api_total_top_comments": api_total,
                "output_file": str(output),
                "result": payload,
            }
        if handler == "crawl_keyword_comments":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = bool(params.get("show_browser", False))
            results, outputs, error = await CommentCrawlerService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
            ).crawl_keyword_comments(
                keyword=str(keyword),
                limit=int(params.get("limit", 3)),
                days=int(params.get("days", 3)),
                region=params.get("region"),
                show_browser=show_browser,
            )
            if error:
                return {"error": error}
            total_captured = sum(r.get("total_comments_captured", 0) for r in results)
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "summary": f"关键词「{keyword}」共处理 {len(results)} 个视频，抓取 {total_captured} 条评论",
                "keyword": keyword,
                "videos_processed": len(results),
                "total_comments_captured": total_captured,
                "output_files": [str(p) for p in outputs],
                "results": results,
            }
        if handler == "search_videos":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = bool(params.get("show_browser", False))
            try:
                payload, output = await CommentCrawlerService(
                    self.settings,
                    tenant_id=self.tenant_id,
                    platform=self.platform,
                    account_id=self.session.account_id,
                ).search_videos(
                    keyword=str(keyword),
                    limit=int(params.get("limit", 20)),
                    show_browser=show_browser,
                )
            except NotImplementedError as exc:
                return {"error": str(exc)}
            videos = payload.get("videos") or []
            if not videos:
                return {
                    "error": payload.get("diagnostic") or f"关键词「{keyword}」未搜索到视频",
                    "keyword": keyword,
                    "capture_method": payload.get("capture_method"),
                    "output_file": str(output),
                }
            with_title = sum(1 for v in videos if v.get("title"))
            summary = f"关键词「{keyword}」搜索到 {payload.get('video_count', len(videos))} 个视频"
            if with_title:
                summary += f"（{with_title} 条含标题/作者/点赞）"
            if payload.get("diagnostic"):
                summary += f"；{payload['diagnostic']}"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "summary": summary,
                "keyword": keyword,
                "video_count": payload.get("video_count", len(videos)),
                "capture_method": payload.get("capture_method"),
                "output_file": str(output),
                "videos_preview": videos[:10],
                "result": payload,
            }
        return {"error": f"未实现的内置处理器: {handler}"}


def build_skill_tool_definitions(
    skills: list[SkillOut],
    *,
    explicit_skill_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    explicit = explicit_skill_ids or set()
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "list_skills",
                "description": "列出当前可用技能（仅含名称与描述）。需要执行某技能时调用 invoke_skill",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "invoke_skill",
                "description": "按 skill_id 调用技能；instruction 技能会注入完整操作指南，actions/builtin 会直接执行",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "description": "技能 ID，如 douyin-hot-list"},
                        "params": {
                            "type": "object",
                            "description": "技能参数键值对",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["skill_id"],
                },
            },
        },
    ]
    skills_by_id = {s.id: s for s in skills}
    for skill in skills:
        if not skill.enabled:
            continue
        if skill.disable_model_invocation and skill.id not in explicit:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in skill.parameters:
            schema: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.default is not None:
                schema["default"] = param.default
            properties[param.name] = schema
            if param.required:
                required.append(param.name)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": skill.tool_name,
                    "description": f"[技能·自动] {skill.description}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return tools


def skills_description_summary(skills: list[SkillOut], explicit_skill_ids: set[str] | None = None) -> str:
    explicit = explicit_skill_ids or set()
    lines = []
    for skill in skills:
        if not skill.enabled:
            continue
        manual = skill.disable_model_invocation or skill.id in explicit
        tag = "手动" if manual else "自动"
        lines.append(f"- {skill.id} ({tag}): {skill.description}")
    return "\n".join(lines)
