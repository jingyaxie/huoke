from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from app.platforms.constants import BINDABLE_PLATFORMS
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.kuaishou.crawler import KuaishouCrawler
from app.platforms.xiaohongshu.crawler import XhsCrawler

_INTERACTIVE_CRAWLERS: dict[str, type] = {
    "douyin": DouyinCrawler,
    "xiaohongshu": XhsCrawler,
    "kuaishou": KuaishouCrawler,
}


async def _cleanup_session_payload(session: dict[str, Any]) -> None:
    context = session.get("context")
    browser = session.get("browser")
    playwright = session.get("playwright")
    with suppress(Exception):
        if context is not None:
            await context.close()
    with suppress(Exception):
        if browser is not None:
            await browser.close()
    with suppress(Exception):
        if playwright is not None:
            await playwright.stop()


async def stop_interactive_session(
    platform: str,
    tenant_id: str,
    account_id: str,
) -> bool:
    """停止指定平台的交互登录任务并释放 VNC 上的浏览器窗口。"""
    crawler_cls = _INTERACTIVE_CRAWLERS.get(platform.strip().lower())
    if crawler_cls is None:
        return False

    key = crawler_cls._session_key(tenant_id, account_id)
    session = crawler_cls._interactive_sessions.pop(key, None)
    task = crawler_cls._interactive_tasks.pop(key, None)

    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task

    if session is not None:
        await _cleanup_session_payload(session)
        return True
    return task is not None


async def stop_all_interactive_sessions(
    tenant_id: str,
    account_id: str,
    *,
    except_platform: str | None = None,
) -> list[str]:
    """关闭同租户账号下所有（或其它平台）交互登录，避免 VNC 仍显示上一平台页面。"""
    stopped: list[str] = []
    for platform in BINDABLE_PLATFORMS:
        if except_platform and platform == except_platform.strip().lower():
            continue
        if await stop_interactive_session(platform, tenant_id, account_id):
            stopped.append(platform)
    return stopped


async def restart_interactive_login_for_platform(
    tenant_id: str,
    account_id: str,
    platform: str,
) -> list[str]:
    """切换平台登录前：先关掉其它平台，再关掉本平台旧窗口以便重新打开。"""
    stopped = await stop_all_interactive_sessions(tenant_id, account_id)
    platform = platform.strip().lower()
    if await stop_interactive_session(platform, tenant_id, account_id):
        if platform not in stopped:
            stopped.append(platform)
    return stopped
