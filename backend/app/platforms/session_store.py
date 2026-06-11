from __future__ import annotations

import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from playwright.async_api import BrowserContext

from app.core.config import Settings
from app.platforms.account_id import normalize_account_id
from app.platforms.types import normalize_platform
from app.platforms.tenant import normalize_tenant_id
from app.utils.crypto import decrypt_json, encrypt_json

_ENC_MARKER = "__enc_v1__"


class PlatformSessionStore(ABC):
    platform: str

    def __init__(self, settings: Settings, platform: str) -> None:
        self.settings = settings
        self.platform = normalize_platform(platform)
        self.tenants_dir = self._resolve_tenants_dir()
        self.tenants_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_tenants_dir(self) -> Path:
        return self.settings.storage_root / self.platform / "tenants"

    def path_for(self, tenant_id: str, account_id: str = "default") -> Path:
        safe = normalize_tenant_id(tenant_id)
        account = normalize_account_id(account_id)
        return self.tenants_dir / safe / "accounts" / account / "storage_state.json"

    def profile_dir_for(self, tenant_id: str, account_id: str = "default") -> Path:
        safe = normalize_tenant_id(tenant_id)
        account = normalize_account_id(account_id)
        if self.platform == "douyin":
            base = self.settings.douyin_profile_dir
        else:
            base = self.settings.storage_root / self.platform / "profile"
        return base / safe / account

    def _read_file(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and _ENC_MARKER in raw:
            key = self.settings.storage_state_encryption_key
            if not key:
                raise ValueError("检测到加密登录态，但未配置 STORAGE_STATE_ENCRYPTION_KEY")
            return decrypt_json(str(raw[_ENC_MARKER]), key)
        if isinstance(raw, dict):
            return raw
        raise ValueError("登录态文件格式无效")

    def _write_file(self, path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = self.settings.storage_state_encryption_key
        if key:
            payload = {_ENC_MARKER: encrypt_json(state, key)}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, tenant_id: str, account_id: str = "default") -> dict | None:
        return self._read_file(self.path_for(tenant_id, account_id))

    def save_dict(self, tenant_id: str, state: dict, account_id: str = "default") -> Path:
        path = self.path_for(tenant_id, account_id)
        self._write_file(path, state)
        return path

    async def save_from_context(
        self, tenant_id: str, context: BrowserContext, account_id: str = "default"
    ) -> Path:
        path = self.path_for(tenant_id, account_id)
        temp_path = path.with_name(f".{path.name}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(temp_path))
        try:
            state = json.loads(temp_path.read_text(encoding="utf-8"))
            return self.save_dict(tenant_id, state, account_id)
        finally:
            temp_path.unlink(missing_ok=True)

    @abstractmethod
    def is_ready(self, state: dict | None) -> bool: ...

    def clear_session(self, tenant_id: str, account_id: str = "default") -> dict:
        """删除 storage_state 与 Playwright 持久化 Profile，用于解决 Cookie 与浏览器状态不同步。"""
        account = normalize_account_id(account_id)
        tid = normalize_tenant_id(tenant_id)
        state_path = self.path_for(tid, account)
        profile_dir = self.profile_dir_for(tid, account)
        storage_removed = False
        if state_path.exists():
            state_path.unlink()
            storage_removed = True
        profile_removed = False
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
            profile_removed = profile_dir.exists() is False
        return {
            "platform": self.platform,
            "tenant_id": tid,
            "account_id": account,
            "cleared": storage_removed or profile_removed,
            "storage_state_removed": storage_removed,
            "profile_removed": profile_removed,
            "storage_state_path": str(state_path),
            "profile_dir": str(profile_dir),
        }

    def login_status(self, tenant_id: str, account_id: str = "default") -> dict:
        account = normalize_account_id(account_id)
        path = self.path_for(tenant_id, account)
        encrypted = bool(self.settings.storage_state_encryption_key)
        profile_dir = self.profile_dir_for(tenant_id, account)
        base = {
            "platform": self.platform,
            "tenant_id": normalize_tenant_id(tenant_id),
            "account_id": account,
            "storage_state_path": str(path),
            "profile_dir": str(profile_dir),
            "profile_exists": profile_dir.exists(),
            "encrypted": encrypted,
        }
        if not path.exists():
            return {
                **base,
                "status": "missing",
                "message": f"未找到 {self.platform} 登录态，请先绑定账号。",
                "cookie_count": 0,
            }
        try:
            data = self.load(tenant_id, account) or {}
            cookies = data.get("cookies") or []
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            has_session = self.is_ready(data)
            return {
                **base,
                "status": "ready" if has_session else "incomplete",
                "message": "登录态可用" if has_session else "已找到 Cookie，但缺少关键会话，请重新登录。",
                "cookie_count": len(cookies),
                "cookie_names_preview": sorted(cookie_names)[:20],
            }
        except Exception as exc:
            return {
                **base,
                "status": "error",
                "message": f"读取登录态失败：{exc}",
                "cookie_count": 0,
            }
