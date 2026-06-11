from __future__ import annotations

import json
import logging
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)

LOGIN_MODAL_SELECTORS = (
    'input[placeholder*="手机号"]',
    'input[placeholder*="验证码"]',
    "button.submit:has-text('登录')",
    ".login-container",
    ".reds-modal",
)

CLOSE_SELECTORS = (
    ".reds-modal .close",
    ".reds-modal [class*='close']",
    ".login-container [class*='close']",
    "[class*='close-icon']",
    "svg[class*='close']",
    "button:has-text('关闭')",
    "button:has-text('我知道了')",
    ".reds-alert-footer__right",
)

LOGIN_ACTIVATE_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/login/activate"


async def has_login_modal(page: Page) -> bool:
    for selector in LOGIN_MODAL_SELECTORS:
        try:
            if await page.locator(selector).first.count() > 0:
                if await page.locator(selector).first.is_visible():
                    return True
        except Exception:
            continue
    return False


async def dismiss_login_overlay(page: Page) -> dict[str, Any]:
    """尝试关闭小红书登录弹窗/遮罩。"""
    result: dict[str, Any] = {"dismissed": False, "had_modal": False, "actions": []}

    if not await has_login_modal(page):
        return result
    result["had_modal"] = True

    try:
        await page.keyboard.press("Escape")
        result["actions"].append("escape")
        await page.wait_for_timeout(400)
    except Exception:
        pass

    if not await has_login_modal(page):
        result["dismissed"] = True
        return result

    for selector in CLOSE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(force=True, timeout=2000)
            result["actions"].append(f"click:{selector}")
            await page.wait_for_timeout(500)
            if not await has_login_modal(page):
                result["dismissed"] = True
                return result
        except Exception:
            continue

    for selector in (".reds-mask", ".mask", "[class*='mask']"):
        try:
            mask = page.locator(selector).first
            if await mask.count() == 0:
                continue
            box = await mask.bounding_box()
            if not box:
                continue
            await page.mouse.click(box["x"] + 5, box["y"] + 5)
            result["actions"].append(f"mask_click:{selector}")
            await page.wait_for_timeout(500)
            if not await has_login_modal(page):
                result["dismissed"] = True
                return result
        except Exception:
            continue

    try:
        removed = await page.evaluate(
            """() => {
                const selectors = [
                    '.reds-modal', '.login-container', '.login-modal',
                    '[class*="login-container"]', '[class*="login-modal"]',
                ];
                let count = 0;
                for (const sel of selectors) {
                    document.querySelectorAll(sel).forEach((el) => {
                        el.remove();
                        count += 1;
                    });
                }
                document.querySelectorAll('.reds-mask, [class*="mask"]').forEach((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'absolute') {
                        el.remove();
                        count += 1;
                    }
                });
                document.body.style.overflow = 'auto';
                return count;
            }"""
        )
        if removed:
            result["actions"].append(f"js_remove:{removed}")
            await page.wait_for_timeout(300)
            if not await has_login_modal(page):
                result["dismissed"] = True
    except Exception:
        pass

    return result


async def activate_session(page: Page) -> dict[str, Any]:
    """用已登录 Cookie 激活小红书 Web 会话。"""
    try:
        response = await page.goto(LOGIN_ACTIVATE_URL, wait_until="commit", timeout=15000)
        status = response.status if response else 0
        body = ""
        if response:
            try:
                body = await response.text()
            except Exception:
                body = ""
        if body:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return {"ok": status == 200, "status": status, "data": parsed}
            except Exception:
                return {"ok": status == 200, "status": status, "raw": body[:200]}
        return {"ok": status == 200, "status": status}
    except Exception as exc:
        logger.debug("xhs activate_session failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def prepare_logged_in_page(page: Page) -> dict[str, Any]:
    """关闭登录弹窗并尝试激活会话。"""
    dismiss = await dismiss_login_overlay(page)
    activate = await activate_session(page)
    if dismiss.get("had_modal"):
        dismiss = await dismiss_login_overlay(page)
    return {"dismiss": dismiss, "activate": activate}
