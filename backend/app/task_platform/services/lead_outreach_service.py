from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import Settings
from app.platforms.registry import get_dm_tool
from app.services.agent_browser_session import AgentBrowserSession
from app.services.comment_reply_service import CommentReplyService
from app.services.interaction_log_service import ENGINE_SOCIAL_ROAM, InteractionLogService
from app.services.social_roam.human.douyin.actions import human_reply_comment
from app.services.social_roam.types import render_template
from app.task_platform.schemas.instance import LeadAcquisitionTaskSpec
from app.services.outreach_policy import (
    choose_outreach_action,
    daily_quota_ok,
    random_interval_sec,
    remaining_task_quota,
)


class LeadOutreachService:
    """对已匹配线索执行评论回复/私信，遵守 action_policy 与日配额。"""

    def __init__(
        self,
        settings: Settings,
        *,
        tenant_id: str,
        session: AgentBrowserSession,
        db_session,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.session = session
        self.db_session = db_session

    async def run(
        self,
        leads: list[dict[str, Any]],
        spec: LeadAcquisitionTaskSpec,
        *,
        task_id: str,
    ) -> dict[str, Any]:
        policy = spec.action_policy
        limits = spec.daily_limits
        log_service = (
            InteractionLogService(self.db_session, self.settings, tenant_id=self.tenant_id)
            if self.db_session is not None
            else None
        )
        stats: dict[str, Any] = {
            "comments_scanned": len(leads),
            "matched": len(leads),
            "replies": 0,
            "dms": 0,
            "follows": 0,
            "skipped": 0,
            "dry_run": spec.dry_run,
        }
        seen_users: set[str] = set()
        page = await self.session.ensure_started()

        for lead in leads:
            if ctx_cancel := self._task_quota_exhausted(stats, limits):
                stats["stop_reason"] = ctx_cancel
                break

            user_key = (
                lead.get("comment_user", {}).get("user_id")
                or lead.get("comment_user", {}).get("sec_uid")
                or ""
            )
            if user_key and user_key in seen_users:
                stats["skipped"] += 1
                continue

            action = choose_outreach_action(
                comment_ratio=policy.comment_ratio,
                dm_ratio=policy.dm_ratio,
            )
            if action == "skip":
                stats["skipped"] += 1
                continue

            if log_service is not None:
                quota = log_service.query_stats(
                    platform=spec.platform,
                    account_id=spec.account_id,
                    period="today",
                    reply_limit=limits.max_comment_replies,
                    follow_limit=limits.max_follows,
                    dm_limit=limits.max_dms,
                )
                if not daily_quota_ok(quota, action):
                    stats["stop_reason"] = f"daily_{action}_quota_exhausted"
                    break

            if action == "reply":
                remaining = remaining_task_quota(
                    stats,
                    max_replies=limits.max_comment_replies,
                    max_follows=limits.max_follows,
                    max_dms=limits.max_dms,
                )
                if remaining["replies"] <= 0:
                    stats["skipped"] += 1
                    continue
                ok = await self._do_reply(lead, spec, page, log_service, task_id=task_id)
                if ok:
                    stats["replies"] += 1
                    if user_key:
                        seen_users.add(str(user_key))
            elif action == "dm":
                remaining = remaining_task_quota(
                    stats,
                    max_replies=limits.max_comment_replies,
                    max_follows=limits.max_follows,
                    max_dms=limits.max_dms,
                )
                if remaining["dms"] <= 0:
                    stats["skipped"] += 1
                    continue
                ok = await self._do_dm(lead, spec, log_service, task_id=task_id)
                if ok:
                    stats["dms"] += 1
                    if user_key:
                        seen_users.add(str(user_key))

            await asyncio.sleep(random_interval_sec(policy.interval_min_sec, policy.interval_max_sec))

        return {"status": "completed", "stats": stats, "task_id": task_id}

    @staticmethod
    def _task_quota_exhausted(stats: dict[str, Any], limits) -> str | None:
        remaining = remaining_task_quota(
            stats,
            max_replies=limits.max_comment_replies,
            max_follows=limits.max_follows,
            max_dms=limits.max_dms,
        )
        if remaining["replies"] <= 0 and remaining["dms"] <= 0:
            return "task_quota_exhausted"
        return None

    async def _do_reply(
        self,
        lead: dict[str, Any],
        spec: LeadAcquisitionTaskSpec,
        page,
        log_service: InteractionLogService | None,
        *,
        task_id: str,
    ) -> bool:
        comment_id = str(lead.get("comment", {}).get("comment_id") or "")
        if not comment_id:
            return False
        if log_service and log_service.is_comment_replied(
            platform=spec.platform,
            comment_id=comment_id,
            account_id=spec.account_id,
        ):
            return False

        comment_text = str(lead.get("comment", {}).get("text") or "")
        reply_text = render_template(
            spec.action_policy.reply_template,
            nickname=str(lead.get("comment_user", {}).get("nickname") or "用户"),
            comment=comment_text,
        )
        if spec.dry_run:
            lead.setdefault("actions_taken", []).append({"type": "reply", "status": "dry_run"})
            return True

        if spec.platform == "douyin":
            result = await human_reply_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                content_url=str(lead.get("content", {}).get("content_url") or ""),
                comment_id=comment_id,
                reply_text=reply_text,
            )
            ok = bool(result.get("ok"))
        elif self.db_session is not None:
            service = CommentReplyService(
                self.settings,
                tenant_id=self.tenant_id,
                platform=spec.platform,
                session=self.db_session,
                account_id=spec.account_id,
            )
            result = await service.reply_comment(
                comment_id=comment_id,
                reply_text=reply_text,
                content_id=str(lead.get("content", {}).get("content_id") or "") or None,
                comment_text=comment_text,
            )
            ok = str(result.get("status") or "").lower() == "completed"
        else:
            return False

        if log_service:
            log_service.record(
                platform=spec.platform,
                action="reply",
                status="ok" if ok else "failed",
                engine=ENGINE_SOCIAL_ROAM,
                account_id=spec.account_id,
                comment_id=comment_id,
                content_id=lead.get("content", {}).get("content_id"),
                content_url=lead.get("content", {}).get("content_url"),
                target_user_id=lead.get("comment_user", {}).get("user_id"),
                target_sec_uid=lead.get("comment_user", {}).get("sec_uid"),
                target_nickname=lead.get("comment_user", {}).get("nickname"),
                keyword=spec.keyword,
                task_id=task_id,
                reply_text=reply_text,
                error_message=None if ok else str(result.get("error") or ""),
                raw_result=result if not ok else None,
            )
        lead.setdefault("actions_taken", []).append(
            {"type": "reply", "status": "ok" if ok else "failed", "error": result.get("error")}
        )
        return ok

    async def _do_dm(
        self,
        lead: dict[str, Any],
        spec: LeadAcquisitionTaskSpec,
        log_service: InteractionLogService | None,
        *,
        task_id: str,
    ) -> bool:
        if spec.platform != "douyin":
            lead.setdefault("actions_taken", []).append(
                {"type": "dm", "status": "skipped", "error": "platform_unsupported"}
            )
            return False

        sec_uid = str(lead.get("comment_user", {}).get("sec_uid") or "")
        user_id = str(lead.get("comment_user", {}).get("user_id") or "")
        if not sec_uid:
            return False

        if log_service and log_service.is_user_dmed(
            platform=spec.platform,
            target_user_id=user_id or None,
            target_sec_uid=sec_uid or None,
            account_id=spec.account_id,
        ):
            return False

        comment_text = str(lead.get("comment", {}).get("text") or "")
        message = render_template(
            spec.action_policy.dm_template,
            nickname=str(lead.get("comment_user", {}).get("nickname") or "用户"),
            comment=comment_text,
        )
        if spec.dry_run:
            lead.setdefault("actions_taken", []).append({"type": "dm", "status": "dry_run"})
            return True

        tool = get_dm_tool(
            self.settings,
            spec.platform,
            self.tenant_id,
            account_id=spec.account_id,
        )
        result = await tool.send_message(
            sec_uid=sec_uid,
            message=message,
            username=str(lead.get("comment_user", {}).get("nickname") or ""),
            show_browser=not self.session.headless,
        )
        dm = result.get("message") or {}
        ok = bool(dm.get("ok"))
        if log_service:
            log_service.record(
                platform=spec.platform,
                action="dm",
                status="ok" if ok else "failed",
                engine=ENGINE_SOCIAL_ROAM,
                account_id=spec.account_id,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                target_nickname=lead.get("comment_user", {}).get("nickname"),
                keyword=spec.keyword,
                task_id=task_id,
                reply_text=message,
                error_message=None if ok else str(dm.get("error") or dm.get("hint") or ""),
                raw_result=result if not ok else None,
            )
        lead.setdefault("actions_taken", []).append(
            {"type": "dm", "status": "ok" if ok else "failed", "error": dm.get("error")}
        )
        return ok
