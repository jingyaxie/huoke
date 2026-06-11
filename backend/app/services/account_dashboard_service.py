from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.platforms.registry import get_account_dashboard_tool
from app.platforms.types import normalize_platform


class AccountDashboardService:
    """已登录账号主页监控服务（跨平台统一入口）。"""

    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.account_id = account_id

    async def fetch_dashboard(
        self,
        platform: str,
        *,
        show_browser: bool = False,
        works_limit: int = 10,
    ) -> tuple[dict, Path]:
        platform = normalize_platform(platform)
        tool = get_account_dashboard_tool(self.settings, platform, self.tenant_id, account_id=self.account_id)
        return await tool.fetch_dashboard(show_browser=show_browser, works_limit=works_limit)
