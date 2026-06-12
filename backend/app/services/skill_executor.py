from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.antibot import LoginRequiredError
from app.platforms.registry import get_dm_tool, get_follow_tool, get_session_store
from app.platforms.douyin.profile import build_profile_url as douyin_profile_url
from app.platforms.xiaohongshu.profile import build_profile_url as xhs_profile_url
from app.platforms.kuaishou.utils import build_profile_url as ks_profile_url
from app.schemas.skill import SkillOut
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.agent_browser_session import AgentBrowserSession

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

_LOCAL_COMMENT_HINT = (
    "完整评论已写入 output_file；后续汇总/筛选意向请用 analyze_local_comments 或 read_local_comments，"
    "勿对同一视频重复 invoke content-comments。"
)


def _nickname_from_row(row: dict[str, Any]) -> str | None:
    for key in ("nickname", "user_name", "username"):
        if row.get(key):
            return str(row[key])[:40]
    user = row.get("user")
    if isinstance(user, dict) and user.get("nickname"):
        return str(user["nickname"])[:40]
    return None


def _slim_comment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    comments = payload.get("comments") or []
    preview = []
    for row in comments[:8]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("comment") or row.get("text") or "")[:120]
        preview.append(
            {
                "nickname": _nickname_from_row(row),
                "comment": text,
                "digg_count": row.get("digg_count"),
            }
        )
    slim = {k: v for k, v in payload.items() if k != "comments"}
    slim["comments_count"] = len(comments)
    slim["comments_preview"] = preview
    return slim


def _slim_keyword_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slimmed: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        slimmed.append(
            {
                "aweme_id": item.get("aweme_id"),
                "video_url": item.get("video_url") or item.get("note_url"),
                "total_comments_captured": item.get("total_comments_captured"),
                "api_total_top_comments": item.get("api_total_top_comments"),
            }
        )
    return slimmed


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
        if handler == "pipeline_keyword_comments":
            from app.services.skill_runner_service import SkillRunnerService

            runner = SkillRunnerService(
                self.settings,
                self.tenant_id,
                self.platform,
                account_id=self.session.account_id,
                db_session=self.db_session,
            )
            return await runner.execute_keyword_pipeline(
                keyword=str(params.get("keyword") or ""),
                video_limit=int(params.get("video_limit") or params.get("limit") or 5),
                days=int(params.get("days") or 3),
                region=params.get("region"),
                headless=self.session.headless,
                agent_fallback=bool(params.get("agent_fallback", True)),
                provider=str(params.get("provider") or "deepseek"),
                timeout_seconds=int(params.get("timeout_seconds") or 600),
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                guest_mode=bool(params.get("guest_mode", False)),
            )
        if handler == "follow_user":
            return await self._execute_follow(params, action="follow")
        if handler == "unfollow_user":
            return await self._execute_follow(params, action="unfollow")
        if handler == "send_dm":
            return await self._execute_send_dm(params)
        if handler == "crawl_video_comments":
            video_url = params.get("video_url") or params.get("url") or params.get("note_url")
            if not video_url:
                return {"error": "缺少参数 video_url / note_url"}
            show_browser = bool(params.get("show_browser", False))
            service = CommentCrawlerService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
                session=self.db_session,
            )
            payload, output, _cache = await service.crawl_video_comments(
                str(video_url),
                show_browser=show_browser,
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
            )
            captured = payload.get("total_comments_captured", 0)
            api_total = payload.get("api_total_top_comments")
            summary = f"已抓取 {captured} 条评论"
            if api_total is not None:
                summary += f"（接口总数 {api_total}）"
            status = "completed" if captured > 0 else "partial"
            if captured == 0 and payload.get("warning"):
                summary += f"；{payload['warning']}"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": status,
                "summary": summary,
                "video_url": payload.get("video_url") or payload.get("note_url") or video_url,
                "total_comments_captured": captured,
                "api_total_top_comments": api_total,
                "output_file": str(output),
                "result": _slim_comment_payload(payload),
                "hint": _LOCAL_COMMENT_HINT,
            }
        if handler == "crawl_keyword_comments":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = bool(params.get("show_browser", False))
            guest_mode = bool(params.get("guest_mode", False))
            include_full = bool(params.get("include_full_results", False))
            service = CommentCrawlerService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
                session=self.db_session,
            )
            results, outputs, error, session_meta, _cache = await service.crawl_keyword_comments(
                keyword=str(keyword),
                limit=int(params.get("limit", 3)),
                days=int(params.get("days", 3)),
                region=params.get("region"),
                show_browser=show_browser,
                guest_mode=guest_mode,
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
            )
            if error and not results:
                return {"error": error, "diagnostic": error}
            total_captured = sum(r.get("total_comments_captured", 0) for r in results)
            result_rows = results if include_full else _slim_keyword_results(results)
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
                "guest_mode": session_meta.get("guest_mode", guest_mode),
                "session_mode": session_meta.get("session_mode", "logged_in"),
                "output_files": [str(p) for p in outputs],
                "results": result_rows,
                "diagnostic": error,
                "hint": _LOCAL_COMMENT_HINT,
            }
        if handler == "search_videos":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = bool(params.get("show_browser", False))
            service = CommentCrawlerService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.session.account_id,
                session=self.db_session,
            )
            try:
                payload, output, _cache = await service.search_videos(
                    keyword=str(keyword),
                    limit=int(params.get("limit", 20)),
                    show_browser=show_browser,
                    days=params.get("days"),
                    region=params.get("region"),
                    force_refresh=bool(params.get("force_refresh", False)),
                    cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
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

    @staticmethod
    def _profile_url(platform: str, user_id: str, sec_uid: str | None = None) -> str:
        if platform == "douyin" and sec_uid:
            return douyin_profile_url(sec_uid)
        if platform == "xiaohongshu" and user_id:
            return xhs_profile_url(user_id)
        if platform == "kuaishou" and user_id:
            return ks_profile_url(user_id)
        return ""

    async def _execute_follow(self, params: dict[str, Any], *, action: str) -> dict[str, Any]:
        tool = get_follow_tool(
            self.settings,
            self.platform,
            self.tenant_id,
            account_id=self.session.account_id,
        )
        show_browser = bool(params.get("show_browser", False))
        username = str(params.get("username") or "")
        user_id = str(params.get("user_id") or "")
        sec_uid = str(params.get("sec_uid") or "")

        if self.platform == "douyin":
            if not sec_uid or not user_id:
                return {"error": "抖音关注需要 sec_uid 与 user_id", "status": "failed"}
            if action == "follow":
                result = await tool.follow_user(
                    sec_uid=sec_uid,
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )
            else:
                result = await tool.unfollow_user(
                    sec_uid=sec_uid,
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )
        else:
            if not user_id:
                return {"error": "缺少 user_id", "status": "failed"}
            if action == "follow":
                result = await tool.follow_user(
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )
            else:
                result = await tool.unfollow_user(
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )

        relation = result.get(action) or {}
        ok = bool(relation.get("ok"))
        return {
            "type": "builtin",
            "handler": f"{action}_user",
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid"),
            "profile_url": result.get("profile_url")
            or self._profile_url(self.platform, user_id, sec_uid or None),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            action: relation,
            "output_file": result.get("output_file"),
            "error": None if ok else relation.get("error") or relation.get("reason"),
        }

    async def _execute_send_dm(self, params: dict[str, Any]) -> dict[str, Any]:
        message = str(params.get("message") or "").strip()
        if not message:
            return {"error": "缺少 message", "status": "failed"}
        tool = get_dm_tool(
            self.settings,
            self.platform,
            self.tenant_id,
            account_id=self.session.account_id,
        )
        show_browser = bool(params.get("show_browser", False))
        username = str(params.get("username") or "")

        if self.platform == "douyin":
            sec_uid = str(params.get("sec_uid") or "")
            if not sec_uid:
                return {"error": "抖音私信需要 sec_uid", "status": "failed"}
            result = await tool.send_message(
                sec_uid=sec_uid,
                message=message,
                username=username,
                show_browser=show_browser,
            )
            user_id = result.get("user_id")
            sec_uid_val = sec_uid
        else:
            user_id = str(params.get("user_id") or "")
            if not user_id:
                return {"error": "缺少 user_id", "status": "failed"}
            result = await tool.send_message(
                user_id=user_id,
                message=message,
                username=username,
                show_browser=show_browser,
            )
            sec_uid_val = result.get("sec_uid")

        dm = result.get("message") or {}
        ok = bool(dm.get("ok"))
        return {
            "type": "builtin",
            "handler": "send_dm",
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "username": result.get("username"),
            "user_id": result.get("user_id") or user_id,
            "sec_uid": result.get("sec_uid") or sec_uid_val,
            "profile_url": result.get("profile_url")
            or self._profile_url(self.platform, str(user_id or ""), sec_uid_val),
            "message": dm,
            "output_file": result.get("output_file"),
            "error": None if ok else dm.get("error") or dm.get("hint"),
        }


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
                        "skill_id": {"type": "string", "description": "技能 ID，如 search-content"},
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
