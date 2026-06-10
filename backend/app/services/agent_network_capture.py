from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Response

MAX_ENTRIES = 120
MAX_BODY_BYTES = 2_000_000
MAX_SUMMARY_CHARS = 600
MAX_STORED_PREVIEW_ITEMS = 5

_JSON_CONTENT_TYPES = ("application/json", "text/json", "application/javascript")


@dataclass
class CapturedEntry:
    capture_id: str
    url: str
    path: str
    status: int
    content_type: str
    summary: str
    data: dict[str, Any] | list[Any] | None = None
    preview: dict[str, Any] | list[Any] | None = None
    size_bytes: int = 0
    captured_at: float = field(default_factory=time.time)


def summarize_api_payload(url: str, data: Any) -> tuple[str, dict[str, Any] | list[Any] | None]:
    """通用 JSON 摘要，不做任何平台/业务字段解析。"""
    path = urlparse(url).path
    if isinstance(data, list):
        return f"JSON 数组，长度 {len(data)}", {"path": path, "items_preview": data[:MAX_STORED_PREVIEW_ITEMS]}
    if isinstance(data, dict):
        keys = list(data.keys())[:12]
        return f"JSON 对象，字段: {', '.join(keys)}", {"path": path, "keys": keys}
    return "JSON 数据", {"path": path}


class NetworkCapture:
    def __init__(self) -> None:
        self._entries: list[CapturedEntry] = []
        self._handler = None
        self._page: Page | None = None

    def attach(self, page: Page) -> None:
        self.detach()
        self._page = page

        async def on_response(resp: Response) -> None:
            await self._capture_response(resp)

        page.on("response", on_response)
        self._handler = on_response

    def detach(self) -> None:
        if self._page is not None and self._handler is not None:
            try:
                self._page.remove_listener("response", self._handler)
            except Exception:
                pass
        self._handler = None
        self._page = None

    def clear(self) -> None:
        self._entries.clear()

    @property
    def entries(self) -> list[CapturedEntry]:
        return list(self._entries)

    def _matching_entries(self, url_contains: str | None) -> list[CapturedEntry]:
        items = self._entries
        if url_contains:
            needle = url_contains.lower()
            items = [e for e in items if needle in e.url.lower() or needle in e.path.lower()]
        return items

    async def wait_until(
        self,
        *,
        url_contains: str | None = None,
        min_count: int = 1,
        timeout_ms: float = 15000,
        poll_ms: float = 400,
    ) -> bool:
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            if len(self._matching_entries(url_contains)) >= min_count:
                return True
            await asyncio.sleep(poll_ms / 1000.0)
        return len(self._matching_entries(url_contains)) >= min_count

    async def _capture_response(self, resp: Response) -> None:
        try:
            if resp.request.resource_type not in {"xhr", "fetch"}:
                return
            content_type = (resp.headers.get("content-type") or "").lower()
            if not any(token in content_type for token in _JSON_CONTENT_TYPES):
                if "json" not in content_type:
                    return
            status = resp.status
            if status >= 400:
                return
            body = await resp.body()
            if not body or len(body) > MAX_BODY_BYTES:
                return
            try:
                data = json.loads(body.decode("utf-8", errors="ignore"))
            except Exception:
                return
            url = resp.url
            summary, preview = summarize_api_payload(url, data)
            entry = CapturedEntry(
                capture_id=str(uuid.uuid4())[:8],
                url=url,
                path=urlparse(url).path,
                status=status,
                content_type=content_type.split(";")[0],
                summary=summary,
                data=data,
                preview=preview,
                size_bytes=len(body),
            )
            self._entries.append(entry)
            if len(self._entries) > MAX_ENTRIES:
                self._entries = self._entries[-MAX_ENTRIES:]
        except Exception:
            return

    def list_summaries(
        self,
        *,
        limit: int = 10,
        url_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        items = self._matching_entries(url_contains)
        rows = items[-limit:]
        return [
            {
                "capture_id": e.capture_id,
                "path": e.path,
                "summary": e.summary,
                "status": e.status,
            }
            for e in reversed(rows)
        ]

    def query(
        self,
        *,
        url_contains: str | None = None,
        limit: int = 5,
        include_data: bool = True,
    ) -> list[dict[str, Any]]:
        selected = list(reversed(self._matching_entries(url_contains)[-limit:]))
        result: list[dict[str, Any]] = []
        for entry in selected:
            row: dict[str, Any] = {
                "capture_id": entry.capture_id,
                "url": entry.url,
                "path": entry.path,
                "status": entry.status,
                "summary": entry.summary,
                "size_bytes": entry.size_bytes,
            }
            if include_data and entry.data is not None:
                row["data"] = entry.data
            result.append(row)
        return result


async def extract_embedded_page_data(page: Page) -> dict[str, Any]:
    """提取页面内嵌 JSON 来源名，不做业务字段解析（解析由 Skill/Agent 完成）。"""
    script = """
    () => {
      const sources = [];
      const globals = [
        '__INITIAL_STATE__',
        '__NEXT_DATA__',
        '__UNIVERSAL_DATA_FOR_REHYDRATION__',
        'pageConfig',
        '__PINIA__',
        '__NUXT__',
      ];
      for (const key of globals) {
        if (window[key] !== undefined) sources.push(`window.${key}`);
      }
      const scripts = Array.from(document.querySelectorAll('script'));
      for (const el of scripts.slice(0, 40)) {
        const text = el.textContent || '';
        if (!text || text.length < 40) continue;
        if (text.includes('RENDER_DATA')) sources.push('script:RENDER_DATA');
        if (text.includes('__INITIAL_STATE__')) sources.push('script:__INITIAL_STATE__');
        if (text.includes('pageConfig')) sources.push('script:pageConfig');
      }
      return { sources: [...new Set(sources)].slice(0, 12) };
    }
    """
    try:
        payload = await page.evaluate(script)
        if not isinstance(payload, dict):
            return {}
        return {
            "embedded_sources": payload.get("sources") or [],
            "hint": "内嵌 JSON 仅报告来源，字段解析请在 Skill 中通过 browser_get_network_data 或 Agent 读取",
        }
    except Exception:
        return {}
