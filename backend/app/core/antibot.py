from __future__ import annotations

import asyncio
import json
import math
import platform as py_platform
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

from app.schemas.antibot import (
    AntibotDelayProfileOut,
    AntibotGlobalConfigOut,
    TenantAntibotConfigOut,
    TenantAntibotOverrideOut,
)
if TYPE_CHECKING:
    from app.services.tenant_antibot_store import TenantAntibotStore
    from app.core.config import Settings
    from app.platforms.session_store import PlatformSessionStore

DEFAULT_MAC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_LINUX_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_USER_AGENT = DEFAULT_MAC_USER_AGENT

STEALTH_VERSION = "v4"

_last_mouse_pos: dict[int, tuple[float, float]] = {}
_BASE_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]
_LINUX_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"]

_ALLOWED_NAV_SCHEMES = frozenset(
    {"http", "https", "about", "data", "blob", "chrome", "chrome-extension", "file", "javascript", "ws", "wss"}
)
_BLOCKED_PROTOCOL_SCHEMES = (
    "snssdk1128",
    "snssdk",
    "aweme",
    "bytedance",
    "douyin",
    "tiktok",
)

_EXTERNAL_PROTOCOL_GUARD_JS = """
(() => {
  const allowed = new Set(['http','https','about','data','blob','file','javascript']);
  const isBlocked = (url) => {
    if (!url || typeof url !== 'string') return false;
    const m = url.match(/^([a-z][a-z0-9+.-]*):/i);
    if (!m) return false;
    return !allowed.has(m[1].toLowerCase());
  };
  const origOpen = window.open;
  window.open = function(url, ...rest) {
    if (isBlocked(url)) return null;
    return origOpen.call(window, url, ...rest);
  };
  document.addEventListener('click', (ev) => {
    const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (el && isBlocked(el.getAttribute('href') || '')) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
  }, true);
})();
"""


def _is_external_protocol_url(url: str) -> bool:
    if not url or "://" not in url:
        return False
    scheme = url.split("://", 1)[0].lower()
    return scheme not in _ALLOWED_NAV_SCHEMES


def seed_profile_protocol_prefs(profile_dir: Path) -> None:
    """在 persistent profile 中静默拒绝外部协议，避免 Linux xdg-open 弹窗。"""
    local_state_path = profile_dir / "Local State"
    data: dict = {}
    if local_state_path.exists():
        try:
            data = json.loads(local_state_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    handler = data.setdefault("protocol_handler", {})
    excluded = handler.setdefault("excluded_schemes", {})
    for scheme in _BLOCKED_PROTOCOL_SCHEMES:
        excluded[scheme] = True
    try:
        local_state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


async def install_external_protocol_guard(context: BrowserContext) -> None:
    async def _route_handler(route) -> None:
        if _is_external_protocol_url(route.request.url):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await context.route("**/*", _route_handler)
    await context.add_init_script(_EXTERNAL_PROTOCOL_GUARD_JS)

_DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "default": (1.0, 1.0),
    "page_load": (1.4, 2.0),
    "scroll": (0.7, 1.2),
    "action": (0.4, 0.9),
    "poll": (0.9, 1.1),
    "between_items": (1.0, 1.6),
    "warmup": (1.2, 1.8),
    "fast": (0.12, 0.28),
}

class LoginRequiredError(RuntimeError):
    """Raised when a crawl is attempted without a valid platform login session."""


@lru_cache
def _stealth_init_script_template() -> str:
    path = Path(__file__).with_name("stealth_init.js")
    return path.read_text(encoding="utf-8")


def launch_args(settings: Settings | None = None) -> list[str]:
    del settings
    args = list(_BASE_LAUNCH_ARGS)
    if sys.platform.startswith("linux"):
        args.extend(_LINUX_LAUNCH_ARGS)
    return args


def browser_channel(settings: Settings) -> str | None:
    channel = (settings.antibot_browser_channel or "").strip()
    return channel or None


def launch_kwargs(settings: Settings, *, headless: bool) -> dict:
    kwargs: dict = {"headless": headless, "args": launch_args(settings)}
    channel = browser_channel(settings)
    if channel:
        kwargs["channel"] = channel
    return kwargs


def fingerprint_platform(settings: Settings) -> str:
    mode = (settings.antibot_fingerprint_platform or "mac").strip().lower()
    if mode == "auto":
        return "mac" if py_platform.system() == "Darwin" else "linux"
    if mode in {"mac", "darwin", "macos"}:
        return "mac"
    return "linux"


def default_user_agent_for_settings(settings: Settings) -> str:
    if fingerprint_platform(settings) == "mac":
        return DEFAULT_MAC_USER_AGENT
    return DEFAULT_LINUX_USER_AGENT


def _chrome_version_binaries() -> list[list[str]]:
    commands = [
        ["google-chrome", "--version"],
        ["google-chrome-stable", "--version"],
        ["chromium", "--version"],
        ["chromium-browser", "--version"],
    ]
    if py_platform.system() == "Darwin":
        commands.insert(
            0,
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
        )
    cache_root = Path.home() / ".cache" / "ms-playwright"
    if cache_root.exists():
        for pattern in (
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
            "chrome-*/chrome-linux/chrome",
            "chrome-*/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ):
            for binary in sorted(cache_root.glob(pattern)):
                commands.append([str(binary), "--version"])
    return commands


@lru_cache
def detected_chrome_major_version() -> str | None:
    for cmd in _chrome_version_binaries():
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
        except Exception:
            continue
        match = re.search(r"(?:Chrome|Chromium)\s+(\d+)", output)
        if match:
            return match.group(1)
    return None


def _sync_chrome_version_in_ua(ua: str) -> str:
    major = detected_chrome_major_version()
    if not major:
        return ua
    return re.sub(r"Chrome/\d+(?:\.\d+)*", f"Chrome/{major}.0.0.0", ua)


def user_agent(settings: Settings) -> str:
    custom = (settings.antibot_user_agent or "").strip()
    if custom:
        return _sync_chrome_version_in_ua(custom)
    return _sync_chrome_version_in_ua(default_user_agent_for_settings(settings))


def chrome_major_from_ua(ua: str) -> str:
    match = re.search(r"Chrome/(\d+)", ua)
    if match:
        return match.group(1)
    return detected_chrome_major_version() or "131"


def client_hints_headers(settings: Settings) -> dict[str, str]:
    ua = user_agent(settings)
    major = chrome_major_from_ua(ua)
    is_mac = fingerprint_platform(settings) == "mac"
    platform_label = '"macOS"' if is_mac else '"Linux"'
    return {
        "sec-ch-ua": f'"Google Chrome";v="{major}", "Chromium";v="{major}", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform_label,
    }


def viewport(settings: Settings) -> dict[str, int]:
    return {"width": settings.antibot_viewport_width, "height": settings.antibot_viewport_height}


def stealth_fingerprint_meta(settings: Settings) -> dict:
    major = chrome_major_from_ua(user_agent(settings))
    is_mac = fingerprint_platform(settings) == "mac"
    if is_mac:
        return {
            "languages": ["zh-CN", "zh", "en-US", "en"],
            "platform": "MacIntel",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "max_touch_points": 0,
            "webgl_vendor": "Intel Inc.",
            "webgl_renderer": "Intel Iris OpenGL Engine",
            "outer_height_offset": 88,
            "chrome_major": major,
            "ua_data_platform": "macOS",
            "ua_data_platform_version": "13.0.0",
        }
    return {
        "languages": ["zh-CN", "zh", "en-US", "en"],
        "platform": "Linux x86_64",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 0,
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)",
        "outer_height_offset": 85,
        "chrome_major": major,
        "ua_data_platform": "Linux",
        "ua_data_platform_version": "",
    }


def stealth_init_script(settings: Settings) -> str:
    meta = stealth_fingerprint_meta(settings)
    return (
        f"window.__ANTIBOT_STEALTH_META__ = {json.dumps(meta, ensure_ascii=False)};\n"
        f"{_stealth_init_script_template()}"
    )


def profile_dir_for(
    settings: Settings,
    platform: str,
    tenant_id: str,
    account_id: str = "default",
) -> Path:
    if platform == "douyin":
        base = settings.douyin_profile_dir
    else:
        base = settings.storage_root / platform / "profile"
    return base / tenant_id / account_id


def persistent_profile_enabled(settings: Settings, platform: str) -> bool:
    del platform
    return settings.antibot_persistent_profile


def headless_for_platform(settings: Settings, platform: str, headless: bool | None = None) -> bool:
    if headless is not None:
        return headless
    if platform == "xiaohongshu":
        return settings.xhs_headless
    if platform == "kuaishou":
        return settings.kuaishou_headless
    if platform == "douyin":
        return settings.douyin_headless
    return settings.agent_headless


def context_kwargs(settings: Settings, state: dict | None = None) -> dict:
    kwargs: dict = {
        "viewport": viewport(settings),
        "user_agent": user_agent(settings),
        "locale": settings.antibot_locale,
        "timezone_id": settings.timezone,
        "extra_http_headers": client_hints_headers(settings),
    }
    if state:
        kwargs["storage_state"] = state
    return kwargs


def persistent_context_kwargs(settings: Settings) -> dict:
    kwargs = context_kwargs(settings, None)
    kwargs.pop("storage_state", None)
    return kwargs


def visible_browser_launch_kwargs(settings: Settings | None = None) -> dict:
    import os

    resolved = settings or None
    if resolved is None:
        from app.core.config import get_settings

        resolved = get_settings()
    kwargs = launch_kwargs(resolved, headless=False)
    if os.environ.get("DISPLAY"):
        kwargs["env"] = os.environ.copy()
    return kwargs


async def launch_browser(playwright: Playwright, settings: Settings, *, headless: bool) -> Browser:
    kwargs = launch_kwargs(settings, headless=headless)
    try:
        return await playwright.chromium.launch(**kwargs)
    except Exception:
        fallback = dict(kwargs)
        fallback.pop("channel", None)
        return await playwright.chromium.launch(**fallback)


async def _seed_cookies_from_state(context: BrowserContext, state: dict | None) -> None:
    if not state:
        return
    cookies = state.get("cookies") or []
    if not cookies:
        return
    try:
        await context.add_cookies(cookies)
    except Exception:
        pass


async def launch_persistent_context(
    playwright: Playwright,
    settings: Settings,
    platform: str,
    tenant_id: str,
    store: PlatformSessionStore,
    *,
    headless: bool,
    account_id: str = "default",
) -> BrowserContext:
    profile_dir = profile_dir_for(settings, platform, tenant_id, account_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    seed_profile_protocol_prefs(profile_dir)
    state = store.load(tenant_id, account_id)
    kwargs = launch_kwargs(settings, headless=headless)
    kwargs.update(persistent_context_kwargs(settings))
    try:
        context = await playwright.chromium.launch_persistent_context(str(profile_dir), **kwargs)
    except Exception:
        fallback = dict(kwargs)
        fallback.pop("channel", None)
        context = await playwright.chromium.launch_persistent_context(str(profile_dir), **fallback)
    await apply_stealth(context, settings, tenant_id=tenant_id)
    await _seed_cookies_from_state(context, state)
    return context


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


async def open_tenant_page(
    playwright: Playwright,
    settings: Settings,
    platform: str,
    tenant_id: str,
    store: PlatformSessionStore,
    *,
    headless: bool | None = None,
    account_id: str = "default",
) -> tuple[Browser | None, BrowserContext, Page]:
    resolved_headless = headless_for_platform(settings, platform, headless)
    if persistent_profile_enabled(settings, platform):
        context = await launch_persistent_context(
            playwright,
            settings,
            platform,
            tenant_id,
            store,
            headless=resolved_headless,
            account_id=account_id,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        return None, context, page

    browser = await launch_browser(playwright, settings, headless=resolved_headless)
    context = await new_browser_context(
        browser,
        settings,
        state=store.load(tenant_id, account_id),
        tenant_id=tenant_id,
    )
    page = await context.new_page()
    return browser, context, page


@dataclass
class AntibotContext:
    settings: Settings
    tenant_id: str | None = None
    override: TenantAntibotOverrideOut | None = None

    @classmethod
    def for_tenant(cls, settings: Settings, tenant_id: str | None) -> AntibotContext:
        override = None
        if tenant_id:
            from app.services.tenant_antibot_store import TenantAntibotStore

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


def global_antibot_config(settings: Settings) -> AntibotGlobalConfigOut:
    return AntibotContext.for_tenant(settings, None).to_effective_config().model_copy(update={"scope": "global"})


def tenant_antibot_config(settings: Settings, tenant_id: str) -> TenantAntibotConfigOut:
    from app.services.tenant_antibot_store import TenantAntibotStore

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
    await install_external_protocol_guard(context)
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if ctx.stealth_enabled:
        await context.add_init_script(stealth_init_script(settings))


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


def _bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int,
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    distance = math.hypot(ex - sx, ey - sy)
    spread = max(40.0, distance * 0.35)
    c1 = (sx + random.uniform(-spread, spread), sy + random.uniform(-spread, spread))
    c2 = (ex + random.uniform(-spread, spread), ey + random.uniform(-spread, spread))
    points: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = (
            u * u * u * sx
            + 3 * u * u * t * c1[0]
            + 3 * u * t * t * c2[0]
            + t * t * t * ex
        )
        y = (
            u * u * u * sy
            + 3 * u * u * t * c1[1]
            + 3 * u * t * t * c2[1]
            + t * t * t * ey
        )
        points.append((x, y))
    return points


def _default_mouse_origin(page: Page) -> tuple[float, float]:
    vp = page.viewport_size or {"width": 1440, "height": 1200}
    return (
        random.uniform(vp["width"] * 0.25, vp["width"] * 0.75),
        random.uniform(vp["height"] * 0.15, vp["height"] * 0.55),
    )


async def human_mouse_move(
    page: Page,
    x: float,
    y: float,
    settings: Settings,
    *,
    tenant_id: str | None = None,
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        await page.mouse.move(x, y)
        return
    page_id = id(page)
    start = _last_mouse_pos.get(page_id, _default_mouse_origin(page))
    steps = random.randint(14, 32)
    for px, py in _bezier_points(start, (x, y), steps=steps):
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.004, 0.022))
    _last_mouse_pos[page_id] = (x, y)


async def human_click(
    page: Page,
    target: str | Locator,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    timeout: float = 10000,
) -> None:
    locator = page.locator(target).first if isinstance(target, str) else target
    await locator.wait_for(state="visible", timeout=timeout)
    box = await locator.bounding_box()
    if not box:
        await locator.click(timeout=timeout)
        return
    x = box["x"] + box["width"] * random.uniform(0.28, 0.72)
    y = box["y"] + box["height"] * random.uniform(0.28, 0.72)
    await human_mouse_move(page, x, y, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    await page.mouse.click(x, y)


async def human_type(
    page: Page,
    target: str | Locator,
    text: str,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    timeout: float = 10000,
    clear_first: bool = True,
) -> None:
    locator = page.locator(target).first if isinstance(target, str) else target
    await human_click(page, locator, settings, tenant_id=tenant_id, timeout=timeout)
    if clear_first:
        modifier = "Meta" if py_platform.system() == "Darwin" else "Control"
        await page.keyboard.press(f"{modifier}+A")
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.keyboard.press("Backspace")
        await asyncio.sleep(random.uniform(0.05, 0.15))
    for char in text:
        await page.keyboard.type(char, delay=random.randint(35, 190))
        if random.random() < 0.06:
            await human_pause(settings, tenant_id=tenant_id, profile="action")


async def human_scroll(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    delta_y: int | None = None,
    profile: str = "scroll",
) -> None:
    if delta_y is None:
        delta_y = random.randint(700, 2200)
    direction = 1 if delta_y >= 0 else -1
    total = abs(delta_y)
    segments = random.randint(2, 5)
    remaining = total
    for index in range(segments):
        if index == segments - 1:
            chunk = remaining
        else:
            chunk = max(60, int(remaining * random.uniform(0.18, 0.45)))
            remaining -= chunk
        sub_steps = random.randint(2, 5)
        step_size = max(20, chunk // sub_steps)
        for _ in range(sub_steps):
            jitter = random.randint(-18, 18)
            await page.mouse.wheel(0, direction * (step_size + jitter))
            await asyncio.sleep(random.uniform(0.02, 0.09))
        await human_delay(page, settings, tenant_id=tenant_id, profile=profile)
    if direction > 0 and random.random() < 0.28:
        await page.mouse.wheel(0, -random.randint(60, 260))
        await human_delay(page, settings, tenant_id=tenant_id, profile=profile)


async def warmup_douyin(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
) -> None:
    if not settings.antibot_warmup_enabled:
        return
    home_url = settings.douyin_home_url
    try:
        await page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
    except Exception:
        return
    await human_delay(page, settings, tenant_id=tenant_id, profile="warmup")
    await human_scroll(page, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="warmup")


def require_login(
    store: PlatformSessionStore,
    tenant_id: str,
    settings: Settings,
    account_id: str = "default",
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.require_login:
        return
    state = store.load(tenant_id, account_id)
    if store.is_ready(state):
        return
    status = store.login_status(tenant_id, account_id)
    raise LoginRequiredError(
        status.get("message")
        or f"{store.platform} 账号 {account_id} 缺少有效登录态，请先完成绑定。"
    )
