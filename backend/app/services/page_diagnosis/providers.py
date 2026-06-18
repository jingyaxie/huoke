from __future__ import annotations

from typing import Any, Protocol

from app.services.page_diagnosis.contracts import PageSnapshot, Platform
from app.services.page_diagnosis.mappers.common import sanitize_body_excerpt
from app.services.page_diagnosis.mappers.registry import normalize_platform, probe_platform_page


class PageSnapshotProvider(Protocol):
    async def collect_safe(self, *, timeout: float = 3.0) -> PageSnapshot | None: ...


class NullSnapshotProvider:
    def __init__(self, platform: str | None) -> None:
        self._platform = normalize_platform(platform)

    async def collect_safe(self, *, timeout: float = 3.0) -> PageSnapshot | None:
        return PageSnapshot(platform=self._platform, collected_via="none")


class PlaywrightPageSnapshotProvider:
    def __init__(self, *, platform: str | None, page: Any, settings: Any) -> None:
        self._platform = normalize_platform(platform)
        self._page = page
        self._settings = settings

    async def collect_safe(self, *, timeout: float = 3.0) -> PageSnapshot | None:
        page = self._page
        if page is None:
            return None
        try:
            from app.services.page_understanding import infer_page_context
            from app.services.playwright_tools import _foreground_elements, _interactive_summary, _overlay_layers

            url = str(getattr(page, "url", "") or "")
            title = ""
            try:
                title = str(await page.title())
            except Exception:
                pass
            overlays = await _overlay_layers(page)
            elements = await _interactive_summary(page)
            foreground = _foreground_elements(elements, overlays)
            page_context = infer_page_context(
                url=url,
                title=title,
                interactive_elements=foreground,
                overlays=overlays,
            )
            body_excerpt = ""
            try:
                raw_body = await page.locator("body").inner_text(timeout=int(timeout * 1000))
                body_excerpt = sanitize_body_excerpt(raw_body)
            except Exception:
                pass
            guard_probe = await probe_platform_page(self._platform, page)
            return PageSnapshot(
                platform=self._platform,
                url=url or None,
                title=title or None,
                scene=str(page_context.get("scene") or "") or None,
                body_excerpt=body_excerpt or None,
                interactive_summary=foreground[:30],
                overlays=overlays[:5],
                guard_probe=guard_probe,
                collected_via="playwright",
            )
        except Exception:
            return None


def build_snapshot_provider(
    *,
    platform: str | None,
    implementation: str,
    page: Any | None,
    settings: Any,
) -> PageSnapshotProvider:
    if page is not None and implementation not in {"unknown", "cache", "dry_run", "sidecar"}:
        return PlaywrightPageSnapshotProvider(platform=platform, page=page, settings=settings)
    return NullSnapshotProvider(platform)
