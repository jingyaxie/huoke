from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Browser, BrowserContext, Page

from app.schemas.antibot import (
    AntibotDelayProfileOut,
    AntibotGlobalConfigOut,
    TenantAntibotConfigOut,
    TenantAntibotOverrideOut,
)
from app.services.tenant_antibot_store import TenantAntibotStore

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.platforms.session_store import PlatformSessionStore

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

STEALTH_VERSION = "v2"
_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]

_DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "default": (1.0, 1.0),
    "page_load": (1.4, 2.0),
    "scroll": (0.7, 1.2),
    "action": (0.4, 0.9),
    "poll": (0.9, 1.1),
    "between_items": (1.0, 1.6),
}


class LoginRequiredError(RuntimeError):
    """Raised when a crawl is attempted without a valid platform login session."""


@lru_cache
def _stealth_init_script() -> str:
    path = Path(__file__).with_name("stealth_init.js")
    return path.read_text(encoding="utf-8")


@dataclass
class AntibotContext:
    settings: Settings
    tenant_id: str | None = None
    override: TenantAntibotOverrideOut | None = None

    @classmethod
    def for_tenant(cls, settings: Settings, tenant_id: str | None) -> AntibotContext:
        override = None
        if tenant_id:
            override = TenantAntibotStore(settings).load_safe(tenant_id)
        return cls(settings=settings, tenant_id=tenant_id, override=override)

    @property
    def enabled(self) -> bool:
        if self.override and self.override.enabled is not None:
            return self.override.enabled
        return self.settings.antibot_enabled

    @property
    def stealth_enabled(self) -> bool:
        if self.override and self.override.stealth_enabled is not None:
            return self.override.stealth_enabled
        return self.settings.antibot_stealth_enabled

    @property
    def require_login(self) -> bool:
        if self.override and self.override.require_login is not None:
            return self.override.require_login
        return self.settings.antibot_require_login

    @property
    def delay_min_ms(self) -> float:
        if self.override and self.override.delay_min_ms is not None:
            return float(self.override.delay_min_ms)
        return float(self.settings.antibot_delay_min_ms)

    @property
    def delay_max_ms(self) -> float:
        if self.override and self.override.delay_max_ms is not None:
            return float(self.override.delay_max_ms)
        return float(self.settings.antibot_delay_max_ms)

    @property
    def delay_multiplier(self) -> float:
        if self.override and self.override.delay_multiplier is not None:
            return float(self.override.delay_multiplier)
        return 1.0

    def delay_bounds(self, profile: str) -> tuple[float, float]:
        lo_mul, hi_mul = _DELAY_PROFILES.get(profile, _DELAY_PROFILES["default"])
        base_lo = self.delay_min_ms
        base_hi = self.delay_max_ms
        if base_hi < base_lo:
            base_lo, base_hi = base_hi, base_lo
        multiplier = self.delay_multiplier
        return base_lo * lo_mul * multiplier, base_hi * hi_mul * multiplier

    def delay_profiles(self) -> list[AntibotDelayProfileOut]:
        profiles: list[AntibotDelayProfileOut] = []
        for profile in _DELAY_PROFILES:
            lo, hi = self.delay_bounds(profile)
            profiles.append(AntibotDelayProfileOut(name=profile, min_ms=lo, max_ms=hi))
        return profiles

    def to_effective_config(self) -> AntibotGlobalConfigOut:
        return AntibotGlobalConfigOut(
            scope="effective",
            enabled=self.enabled,
            stealth_enabled=self.stealth_enabled,
            require_login=self.require_login,
            delay_min_ms=self.delay_min_ms,
            delay_max_ms=self.delay_max_ms,
            user_agent=user_agent(self.settings),
            viewport_width=self.settings.antibot_viewport_width,
            viewport_height=self.settings.antibot_viewport_height,
            locale=self.settings.antibot_locale,
            timezone=self.settings.timezone,
            stealth_version=STEALTH_VERSION,
            delay_profiles=self.delay_profiles(),
        )


def launch_args(settings: Settings | None = None) -> list[str]:
    del settings
    return list(_LAUNCH_ARGS)


def visible_browser_launch_kwargs() -> dict:
    import os

    kwargs: dict = {"headless": False, "args": launch_args()}
    if os.environ.get("DISPLAY"):
        kwargs["env"] = os.environ.copy()
    return kwargs


def user_agent(settings: Settings) -> str:
    return (settings.antibot_user_agent or DEFAULT_USER_AGENT).strip()


def viewport(settings: Settings) -> dict[str, int]:
    return {"width": settings.antibot_viewport_width, "height": settings.antibot_viewport_height}


def headless_for_platform(settings: Settings, platform: str, headless: bool | None = None) -> bool:
    if headless is not None:
        return headless
    if platform == "xiaohongshu":
        return settings.xhs_headless
    if platform == "kuaishou":
        return settings.kuaishou_headless
    if platform == "huoshan":
        return settings.huoshan_headless
    return settings.douyin_headless


def context_kwargs(settings: Settings, state: dict | None = None) -> dict:
    kwargs: dict = {
        "viewport": viewport(settings),
        "user_agent": user_agent(settings),
        "locale": settings.antibot_locale,
        "timezone_id": settings.timezone,
    }
    if state:
        kwargs["storage_state"] = state
    return kwargs


def global_antibot_config(settings: Settings) -> AntibotGlobalConfigOut:
    return AntibotContext.for_tenant(settings, None).to_effective_config().model_copy(update={"scope": "global"})


def tenant_antibot_config(settings: Settings, tenant_id: str) -> TenantAntibotConfigOut:
    store = TenantAntibotStore(settings)
    override = store.load_safe(tenant_id)
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    path = store.path_for(tenant_id)
    return TenantAntibotConfigOut(
        tenant_id=tenant_id,
        override_path=str(path),
        has_override=override is not None and bool(override.model_dump(exclude_none=True)),
        override=override,
        effective=ctx.to_effective_config(),
    )


async def apply_stealth(
    context: BrowserContext,
    settings: Settings,
    *,
    tenant_id: str | None = None,
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if ctx.stealth_enabled:
        await context.add_init_script(_stealth_init_script())


async def new_browser_context(
    browser: Browser,
    settings: Settings,
    *,
    state: dict | None = None,
    tenant_id: str | None = None,
    **extra,
) -> BrowserContext:
    kwargs = context_kwargs(settings, state)
    kwargs.update(extra)
    context = await browser.new_context(**kwargs)
    await apply_stealth(context, settings, tenant_id=tenant_id)
    return context


async def human_delay(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    profile: str = "default",
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        return
    lo, hi = ctx.delay_bounds(profile)
    await page.wait_for_timeout(random.uniform(lo, hi))


async def human_pause(
    settings: Settings,
    *,
    tenant_id: str | None = None,
    profile: str = "default",
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        return
    lo, hi = ctx.delay_bounds(profile)
    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


async def human_scroll(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    delta_y: int | None = None,
    profile: str = "scroll",
) -> None:
    if delta_y is None:
        delta_y = random.randint(900, 2200)
    await page.mouse.wheel(0, delta_y)
    await human_delay(page, settings, tenant_id=tenant_id, profile=profile)


def require_login(
    store: PlatformSessionStore,
    tenant_id: str,
    settings: Settings,
    account_id: str = "default",
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.require_login:
        return
    store.migrate_legacy_if_needed(tenant_id)
    state = store.load(tenant_id, account_id)
    if store.is_ready(state):
        return
    status = store.login_status(tenant_id, account_id)
    raise LoginRequiredError(
        status.get("message")
        or f"{store.platform} 账号 {account_id} 缺少有效登录态，请先完成绑定。"
    )
