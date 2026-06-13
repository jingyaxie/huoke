from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.interaction_log import InteractionLog
from app.platforms.types import normalize_platform
from app.repositories.interaction_log_repository import InteractionLogRepository

ENGINE_AGENT_SKILL = "agent_skill"
ENGINE_SOCIAL_ROAM = "social_roam_human"
ENGINE_MANUAL_UI = "manual_ui"

DEFAULT_REPLY_LIMIT = 5
DEFAULT_FOLLOW_LIMIT = 3
DEFAULT_DM_LIMIT = 3


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _period_start(period: str) -> datetime:
    now = _utc_now_naive()
    normalized = (period or "today").strip().lower()
    if normalized in {"week", "this_week", "7d"}:
        return now - timedelta(days=now.weekday())
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _serialize_log(record: InteractionLog) -> dict[str, Any]:
    return {
        "id": record.id,
        "action": record.action,
        "status": record.status,
        "engine": record.engine,
        "comment_id": record.comment_id,
        "content_id": record.content_id,
        "content_url": record.content_url,
        "target_user_id": record.target_user_id,
        "target_sec_uid": record.target_sec_uid,
        "target_nickname": record.target_nickname,
        "keyword": record.keyword,
        "reply_text": record.reply_text,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat(timespec="seconds") if record.created_at else None,
    }


class InteractionLogService:
    """互动台账：记录 reply/follow/dm，供配额统计与去重。"""

    def __init__(self, session: Session, settings: Settings, *, tenant_id: str) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id

    def _repo(self, platform: str) -> InteractionLogRepository:
        return InteractionLogRepository(self.session, self.tenant_id, platform)

    def record(
        self,
        *,
        platform: str,
        action: str,
        status: str,
        account_id: str = "default",
        engine: str = ENGINE_AGENT_SKILL,
        comment_id: str | None = None,
        content_id: str | None = None,
        content_url: str | None = None,
        target_user_id: str | None = None,
        target_sec_uid: str | None = None,
        target_nickname: str | None = None,
        keyword: str | None = None,
        agent_profile_id: str | None = None,
        task_id: str | None = None,
        reply_text: str | None = None,
        error_message: str | None = None,
        raw_result: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        platform = normalize_platform(platform)
        action = action.strip().lower()
        status = status.strip().lower()
        record = InteractionLog(
            tenant_id=self.tenant_id,
            platform=platform,
            account_id=account_id or "default",
            action=action,
            status=status,
            engine=engine,
            comment_id=(comment_id or None),
            content_id=(content_id or None),
            content_url=(content_url or None),
            target_user_id=(target_user_id or None),
            target_sec_uid=(target_sec_uid or None),
            target_nickname=(target_nickname or None),
            keyword=(keyword or None),
            agent_profile_id=(agent_profile_id or None),
            task_id=(task_id or None),
            reply_text=(reply_text or None),
            error_message=(error_message or None),
            raw_result=raw_result,
            created_at=_utc_now_naive(),
        )
        self._repo(platform).add(record)
        if commit:
            self.session.commit()
        return {"status": "ok", "log_id": record.id}

    def is_comment_replied(
        self,
        *,
        platform: str,
        comment_id: str,
        account_id: str | None = None,
    ) -> bool:
        if not comment_id.strip():
            return False
        platform = normalize_platform(platform)
        return self._repo(platform).has_success(
            platform=platform,
            action="reply",
            comment_id=comment_id.strip(),
            account_id=account_id,
        )

    def is_user_followed(
        self,
        *,
        platform: str,
        target_user_id: str | None = None,
        target_sec_uid: str | None = None,
        account_id: str | None = None,
    ) -> bool:
        platform = normalize_platform(platform)
        user_id = (target_user_id or "").strip() or None
        sec_uid = (target_sec_uid or "").strip() or None
        if not user_id and not sec_uid:
            return False
        repo = self._repo(platform)
        if user_id and repo.has_success(
            platform=platform,
            action="follow",
            target_user_id=user_id,
            account_id=account_id,
        ):
            return True
        if sec_uid:
            return repo.has_success(
                platform=platform,
                action="follow",
                target_sec_uid=sec_uid,
                account_id=account_id,
            )
        return False

    def query_stats(
        self,
        *,
        platform: str,
        account_id: str | None = None,
        period: str = "today",
        reply_limit: int | None = None,
        follow_limit: int | None = None,
        dm_limit: int | None = None,
        comment_id: str | None = None,
        target_user_id: str | None = None,
        target_sec_uid: str | None = None,
    ) -> dict[str, Any]:
        platform = normalize_platform(platform)
        repo = self._repo(platform)
        since = _period_start(period)
        reply_cap = int(reply_limit if reply_limit is not None else DEFAULT_REPLY_LIMIT)
        follow_cap = int(follow_limit if follow_limit is not None else DEFAULT_FOLLOW_LIMIT)
        dm_cap = int(dm_limit if dm_limit is not None else DEFAULT_DM_LIMIT)

        reply_count = repo.count_success_since(
            platform=platform, action="reply", since=since, account_id=account_id
        )
        follow_count = repo.count_success_since(
            platform=platform, action="follow", since=since, account_id=account_id
        )
        dm_count = repo.count_success_since(
            platform=platform, action="dm", since=since, account_id=account_id
        )

        result: dict[str, Any] = {
            "source": "database",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "account_id": account_id,
            "period": period,
            "since": since.isoformat(timespec="seconds"),
            "reply": {
                "count": reply_count,
                "limit": reply_cap,
                "remaining": max(0, reply_cap - reply_count),
                "quota_ok": reply_count < reply_cap,
            },
            "follow": {
                "count": follow_count,
                "limit": follow_cap,
                "remaining": max(0, follow_cap - follow_count),
                "quota_ok": follow_count < follow_cap,
            },
            "dm": {
                "count": dm_count,
                "limit": dm_cap,
                "remaining": max(0, dm_cap - dm_count),
                "quota_ok": dm_count < dm_cap,
            },
        }

        cid = (comment_id or "").strip()
        if cid:
            result["comment_id"] = cid
            result["is_comment_replied"] = self.is_comment_replied(
                platform=platform,
                comment_id=cid,
                account_id=account_id,
            )

        uid = (target_user_id or "").strip() or None
        sec = (target_sec_uid or "").strip() or None
        if uid or sec:
            result["target_user_id"] = uid
            result["target_sec_uid"] = sec
            result["is_user_followed"] = self.is_user_followed(
                platform=platform,
                target_user_id=uid,
                target_sec_uid=sec,
                account_id=account_id,
            )

        return result

    def query_logs(
        self,
        *,
        platform: str,
        action: str | None = None,
        comment_id: str | None = None,
        target_user_id: str | None = None,
        period: str = "today",
        account_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        platform = normalize_platform(platform)
        since = _period_start(period)
        rows, total = self._repo(platform).list_logs(
            platform=platform,
            action=(action or None),
            comment_id=(comment_id or None),
            target_user_id=(target_user_id or None),
            since=since,
            account_id=account_id,
            offset=offset,
            limit=min(limit, 50),
        )
        return {
            "source": "database",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "period": period,
            "since": since.isoformat(timespec="seconds"),
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [_serialize_log(row) for row in rows],
        }
