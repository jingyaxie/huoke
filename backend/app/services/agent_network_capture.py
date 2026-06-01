from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Response

MAX_ENTRIES = 80
MAX_BODY_BYTES = 400_000
MAX_SUMMARY_CHARS = 600
MAX_STORED_PREVIEW_ITEMS = 12

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
    size_bytes: int = 0
    captured_at: float = field(default_factory=time.time)


def _truncate(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _walk_aweme_ids(node: Any, out: list[str], limit: int = 30) -> None:
    if len(out) >= limit:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "aweme_id" and isinstance(value, (str, int)):
                vid = str(value)
                if re.fullmatch(r"\d{8,22}", vid) and vid not in out:
                    out.append(vid)
            else:
                _walk_aweme_ids(value, out, limit)
    elif isinstance(node, list):
        for item in node:
            _walk_aweme_ids(item, out, limit)


def _pick_text(value: Any, *keys: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _summarize_douyin_api(path: str, data: Any) -> tuple[str, dict[str, Any] | list[Any] | None]:
    if not isinstance(data, (dict, list)):
        return "非 JSON 对象", None

    if "/comment/list" in path and isinstance(data, dict):
        comments = data.get("comments") or []
        total = int(data.get("total") or len(comments))
        preview = []
        for item in comments[:MAX_STORED_PREVIEW_ITEMS]:
            if not isinstance(item, dict):
                continue
            user = item.get("user") or {}
            preview.append(
                {
                    "comment_id": str(item.get("cid") or ""),
                    "username": user.get("nickname") or "",
                    "text": _truncate(str(item.get("text") or ""), 120),
                    "digg_count": int(item.get("digg_count") or 0),
                    "reply_total": int(item.get("reply_comment_total") or 0),
                }
            )
        summary = f"评论接口：共 {total} 条，预览 {len(preview)} 条"
        return summary, {"total": total, "comments_preview": preview}

    if "search" in path and isinstance(data, dict):
        aweme_ids: list[str] = []
        _walk_aweme_ids(data, aweme_ids)
        videos = []
        for aweme_id in aweme_ids[:MAX_STORED_PREVIEW_ITEMS]:
            videos.append(
                {
                    "aweme_id": aweme_id,
                    "video_url": f"https://www.douyin.com/video/{aweme_id}",
                }
            )
        summary = f"搜索接口：捕获 {len(aweme_ids)} 个视频 ID"
        return summary, {"video_count": len(aweme_ids), "videos_preview": videos}

    if isinstance(data, dict) and ("aweme_list" in data or "data" in data):
        aweme_ids = []
        _walk_aweme_ids(data, aweme_ids)
        if aweme_ids:
            preview = [
                {"aweme_id": vid, "video_url": f"https://www.douyin.com/video/{vid}"}
                for vid in aweme_ids[:MAX_STORED_PREVIEW_ITEMS]
            ]
            return f"视频列表接口：{len(aweme_ids)} 个 aweme_id", {
                "video_count": len(aweme_ids),
                "videos_preview": preview,
            }

    if isinstance(data, dict) and "comments" in data:
        total = int(data.get("total") or len(data.get("comments") or []))
        return f"评论数据：约 {total} 条", {"total": total}

    if isinstance(data, list):
        return f"JSON 数组，长度 {len(data)}", {"items_preview": data[:5]}

    if isinstance(data, dict):
        keys = list(data.keys())[:12]
        return f"JSON 对象，字段: {', '.join(keys)}", {"keys": keys}

    return "JSON 数据", None


def summarize_api_payload(url: str, data: Any) -> tuple[str, dict[str, Any] | list[Any] | None]:
    path = urlparse(url).path
    if "/aweme/" in path or "douyin.com" in url or "iesdouyin.com" in url:
        return _summarize_douyin_api(path, data)
    if isinstance(data, list):
        return f"JSON 数组，长度 {len(data)}", {"items_preview": data[:5]}
    if isinstance(data, dict):
        keys = list(data.keys())[:12]
        return f"JSON 对象，字段: {', '.join(keys)}", {"keys": keys}
    return "JSON 数据", None


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
                data=preview,
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
        items = self._entries
        if url_contains:
            needle = url_contains.lower()
            items = [e for e in items if needle in e.url.lower() or needle in e.path.lower()]
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
        items = self._entries
        if url_contains:
            needle = url_contains.lower()
            items = [e for e in items if needle in e.url.lower() or needle in e.path.lower()]
        selected = list(reversed(items[-limit:]))
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
    """Extract SSR / inline JSON payloads that SPAs embed in HTML."""
    script = """
    () => {
      const out = { sources: [], aweme_ids: [], video_urls: [] };
      const pushIds = (value) => {
        const text = String(value || '');
        const ids = text.match(/"aweme_id"\\s*:\\s*"(\\d{8,22})"/g) || [];
        for (const m of ids) {
          const id = (m.match(/"(\\d{8,22})"/) || [])[1];
          if (id && !out.aweme_ids.includes(id)) out.aweme_ids.push(id);
        }
        const hrefs = text.match(/\\/video\\/(\\d{8,22})/g) || [];
        for (const m of hrefs) {
          const id = m.replace('/video/', '');
          const url = `https://www.douyin.com/video/${id}`;
          if (!out.video_urls.includes(url)) out.video_urls.push(url);
        }
      };

      const globals = ['__INITIAL_STATE__', '__NEXT_DATA__', '__UNIVERSAL_DATA_FOR_REHYDRATION__'];
      for (const key of globals) {
        const value = window[key];
        if (value !== undefined) {
          out.sources.push(key);
          try { pushIds(JSON.stringify(value).slice(0, 500000)); } catch (_) {}
        }
      }

      const scripts = Array.from(document.querySelectorAll('script'));
      for (const el of scripts.slice(0, 40)) {
        const text = el.textContent || '';
        if (!text || text.length < 40) continue;
        if (text.includes('aweme_id') || text.includes('/video/') || text.includes('RENDER_DATA')) {
          pushIds(text.slice(0, 300000));
          if (text.includes('RENDER_DATA')) out.sources.push('script:RENDER_DATA');
        }
      }

      out.aweme_ids = out.aweme_ids.slice(0, 30);
      out.video_urls = out.video_urls.slice(0, 30);
      out.sources = [...new Set(out.sources)].slice(0, 8);
      return out;
    }
    """
    try:
        payload = await page.evaluate(script)
        if not isinstance(payload, dict):
            return {}
        aweme_ids = payload.get("aweme_ids") or []
        video_urls = payload.get("video_urls") or []
        if aweme_ids and not video_urls:
            video_urls = [f"https://www.douyin.com/video/{vid}" for vid in aweme_ids[:20]]
        return {
            "embedded_sources": payload.get("sources") or [],
            "aweme_ids": aweme_ids[:20],
            "video_urls": video_urls[:20],
        }
    except Exception:
        return {}
