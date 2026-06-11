from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore

REQUIRED_LOGIN_COOKIES = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "uid_tt_ss"}
USER_LOGIN_MARKERS = {"login_time", "passport_assist_user"}


class DouyinSessionStore(PlatformSessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, platform="douyin")

    def is_ready(self, state: dict | None) -> bool:
        if not state:
            return False
        cookie_names = self._cookie_names(state)
        return bool(cookie_names & REQUIRED_LOGIN_COOKIES)

    def is_user_logged_in(self, state: dict | None) -> bool:
        """扫码登录用户；仅有 sessionid 的游客态返回 False。"""
        if not self.is_ready(state):
            return False
        return bool(self._cookie_names(state) & USER_LOGIN_MARKERS)

    @staticmethod
    def _cookie_names(state: dict | None) -> set[str]:
        if not state:
            return set()
        return {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict) and c.get("name")}

    def login_status(self, tenant_id: str, account_id: str = "default") -> dict:
        result = super().login_status(tenant_id, account_id=account_id)
        if result.get("status") in {"ready", "incomplete"}:
            data = self.load(tenant_id, account_id) or {}
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            result["required_cookies_present"] = sorted(cookie_names & REQUIRED_LOGIN_COOKIES)
        return result
