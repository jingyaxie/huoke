from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import REQUIRED_LOGIN_COOKIES


class XhsSessionStore(PlatformSessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, platform="xiaohongshu")

    def is_ready(self, state: dict | None) -> bool:
        if not state:
            return False
        cookie_names = {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict)}
        return "web_session" in cookie_names and bool(cookie_names & REQUIRED_LOGIN_COOKIES)

    def login_status(self, tenant_id: str) -> dict:
        result = super().login_status(tenant_id)
        if result.get("status") in {"ready", "incomplete"}:
            data = self.load(tenant_id) or {}
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            result["required_cookies_present"] = sorted(cookie_names & REQUIRED_LOGIN_COOKIES)
        return result
