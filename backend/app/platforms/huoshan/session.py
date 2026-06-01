from app.core.config import Settings
from app.platforms.huoshan.constants import REQUIRED_LOGIN_COOKIES
from app.platforms.session_store import PlatformSessionStore


class HuoshanSessionStore(PlatformSessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, platform="huoshan")

    def is_ready(self, state: dict | None) -> bool:
        if not state:
            return False
        cookie_names = {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict)}
        return bool(cookie_names & REQUIRED_LOGIN_COOKIES)

    def login_status(self, tenant_id: str) -> dict:
        result = super().login_status(tenant_id)
        if result.get("status") in {"ready", "incomplete"}:
            data = self.load(tenant_id) or {}
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            result["required_cookies_present"] = sorted(cookie_names & REQUIRED_LOGIN_COOKIES)
            result["note"] = (
                "抖音火山版无独立 Web 热榜，登录与抓取复用抖音 Web Cookie；"
                "也可上传 App 分享页登录态。"
            )
        return result
