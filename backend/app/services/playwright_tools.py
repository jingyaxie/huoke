from __future__ import annotations

import base64
import json
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.core.antibot import human_delay
from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.agent_network_capture import extract_embedded_page_data

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": "导航到指定 URL 并等待页面加载",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle"],
                        "description": "等待策略，默认 domcontentloaded",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "点击页面元素，selector 支持 CSS 选择器或 Playwright text= 语法",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "元素选择器"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "在输入框中填入文本（会先清空）",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "输入框选择器"},
                    "text": {"type": "string", "description": "要填入的文本"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "在页面或指定元素上按键，如 Enter、Tab、Escape",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名称，如 Enter"},
                    "selector": {"type": "string", "description": "可选，聚焦到该元素后按键"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "滚动页面",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up", "bottom", "top"],
                        "description": "滚动方向",
                    },
                    "amount": {"type": "integer", "description": "滚动像素，仅 up/down 时有效，默认 600"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "等待元素出现或等待指定毫秒",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "等待出现的元素选择器"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                    "state": {
                        "type": "string",
                        "enum": ["visible", "attached", "hidden"],
                        "description": "元素状态，默认 visible",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_text",
            "description": "获取元素文本或页面可见文本摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "元素选择器，留空则返回页面 body 文本摘要（最多 3000 字符）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_page_info",
            "description": (
                "获取当前页面 URL、标题、交互元素摘要，以及最近拦截到的 XHR/Fetch JSON 接口摘要"
                "和页面内嵌 SSR 数据（如 aweme_id、video_urls）。SPA 页面优先参考 api_captures / embedded_data。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_network_data",
            "description": (
                "读取浏览器自动拦截的 JSON 接口响应（XHR/Fetch）。"
                "适用于抖音等 SPA：搜索、评论、视频详情等数据往往来自接口而非 DOM。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url_contains": {
                        "type": "string",
                        "description": "URL 或 path 包含的关键词，如 comment/list、search、aweme",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回最近匹配的接口数量，默认 5",
                    },
                    "clear_buffer": {
                        "type": "boolean",
                        "description": "读取后是否清空拦截缓存，默认 false",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "截取当前页面截图，用于视觉理解页面布局",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "任务已成功完成，停止执行并返回结果摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "任务完成摘要"},
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_failed",
            "description": "任务无法完成，停止执行并说明原因",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "失败原因"},
                },
                "required": ["reason"],
            },
        },
    },
]


async def _interactive_summary(page: Page, limit: int = 40) -> list[dict[str, str]]:
    script = """
    () => {
      const items = [];
      const seen = new Set();
      const push = (tag, text, selectorHint) => {
        const key = tag + '|' + text;
        if (!text || seen.has(key)) return;
        seen.add(key);
        items.push({ tag, text, selector_hint: selectorHint });
      };
      document.querySelectorAll('a[href], button, input, textarea, [role="button"]').forEach((el, idx) => {
        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || '').trim().slice(0, 80);
        if (!text && tag !== 'input' && tag !== 'textarea') return;
        const id = el.id ? '#' + el.id : '';
        const cls = (el.className && typeof el.className === 'string')
          ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
          : '';
        push(tag, text || `[${tag}]`, `${tag}${id}${cls}` || `nth=${idx}`);
      });
      return items.slice(0, """ + str(limit) + """);
    }
    """
    try:
        return await page.evaluate(script)
    except Exception:
        return []


class PlaywrightToolExecutor:
    def __init__(self, session: AgentBrowserSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def execute(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            page = await self.session.ensure_started()
        except TimeoutError:
            return {"error": "浏览器启动超时，请稍后重试"}, None
        except Exception as exc:
            return {"error": f"浏览器启动失败: {exc}"}, None
        try:
            if name == "browser_goto":
                return await self._goto(page, arguments), None
            if name == "browser_click":
                return await self._click(page, arguments), None
            if name == "browser_fill":
                return await self._fill(page, arguments), None
            if name == "browser_press":
                return await self._press(page, arguments), None
            if name == "browser_scroll":
                return await self._scroll(page, arguments), None
            if name == "browser_wait":
                return await self._wait(page, arguments), None
            if name == "browser_get_text":
                return await self._get_text(page, arguments), None
            if name == "browser_get_page_info":
                return await self._get_page_info(page), None
            if name == "browser_get_network_data":
                return await self._get_network_data(arguments), None
            if name == "browser_screenshot":
                return await self._screenshot(page), None
            if name == "task_complete":
                return {"status": "completed", "summary": arguments.get("summary", "")}, None
            if name == "task_failed":
                return {"status": "failed", "reason": arguments.get("reason", "")}, None
            return {"error": f"未知工具: {name}"}, None
        except PlaywrightTimeoutError as exc:
            return {"error": f"操作超时: {exc}"}, None
        except Exception as exc:
            return {"error": str(exc)}, None

    async def _goto(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        url = args["url"]
        wait_until = args.get("wait_until", "domcontentloaded")
        # 抖音等 SPA 页面很难达到 networkidle，容易 30s 超时
        if wait_until == "networkidle":
            wait_until = "domcontentloaded"
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="page_load")
        response = await page.goto(url, wait_until=wait_until, timeout=45000)
        info = await self.session.page_info()
        return {
            "url": info["url"],
            "title": info["title"],
            "status": response.status if response else None,
            "wait_until": wait_until,
        }

    async def _click(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args["selector"]
        timeout = args.get("timeout_ms", 10000)
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="action")
        await page.locator(selector).first.click(timeout=timeout)
        info = await self.session.page_info()
        return {"clicked": selector, "url": info["url"], "title": info["title"]}

    async def _fill(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args["selector"]
        text = args["text"]
        timeout = args.get("timeout_ms", 10000)
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="action")
        locator = page.locator(selector).first
        await locator.click(timeout=timeout)
        await locator.fill(text, timeout=timeout)
        return {"filled": selector, "text_length": len(text)}

    async def _press(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        key = args["key"]
        selector = args.get("selector")
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="action")
        if selector:
            await page.locator(selector).first.press(key)
        else:
            await page.keyboard.press(key)
        info = await self.session.page_info()
        return {"pressed": key, "url": info["url"], "title": info["title"]}

    async def _scroll(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        direction = args["direction"]
        amount = args.get("amount", 600)
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="scroll")
        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        return {"scrolled": direction, "amount": amount if direction in {"down", "up"} else None}

    async def _wait(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args.get("selector")
        timeout = args.get("timeout_ms", 10000)
        state = args.get("state", "visible")
        if selector:
            await page.locator(selector).first.wait_for(state=state, timeout=timeout)
            return {"waited_for": selector, "state": state}
        await page.wait_for_timeout(min(timeout, 30000))
        return {"waited_ms": timeout}

    async def _get_text(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args.get("selector")
        if selector:
            text = await page.locator(selector).first.inner_text(timeout=10000)
            return {"selector": selector, "text": text[:5000]}
        body_text = await page.locator("body").inner_text(timeout=10000)
        return {"text": body_text[:3000], "truncated": len(body_text) > 3000}

    async def _get_page_info(self, page: Page) -> dict[str, Any]:
        info = await self.session.page_info()
        elements = await _interactive_summary(page)
        embedded_data = await extract_embedded_page_data(page)
        api_captures = self.session.network_capture.list_summaries(limit=8)
        return {
            "url": info["url"],
            "title": info["title"],
            "interactive_elements": elements,
            "api_captures": api_captures,
            "api_capture_count": len(api_captures),
            "embedded_data": embedded_data,
            "hint": (
                "SPA 页面数据优先看 api_captures 与 embedded_data；"
                "需要更多接口详情时调用 browser_get_network_data(url_contains=...)。"
                if api_captures or embedded_data.get("aweme_ids") or embedded_data.get("video_urls")
                else None
            ),
        }

    async def _get_network_data(self, args: dict[str, Any]) -> dict[str, Any]:
        url_contains = args.get("url_contains")
        limit = int(args.get("limit", 5))
        clear_buffer = bool(args.get("clear_buffer", False))
        items = self.session.network_capture.query(
            url_contains=url_contains,
            limit=max(1, min(limit, 20)),
            include_data=True,
        )
        if clear_buffer:
            self.session.network_capture.clear()
        return {
            "url_contains": url_contains,
            "count": len(items),
            "items": items,
            "hint": "数据来自页面加载/滚动/点击后自动拦截的 XHR/Fetch JSON 响应",
        }

    async def _screenshot(self, page: Page) -> dict[str, Any]:
        png_bytes = await page.screenshot(type="png", full_page=False)
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return {
            "format": "png",
            "base64": encoded,
            "size_bytes": len(png_bytes),
        }


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
