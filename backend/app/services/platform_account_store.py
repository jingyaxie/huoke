from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import Settings
from app.platforms.account_id import normalize_account_id
from app.platforms.constants import BINDABLE_PLATFORMS, PLATFORM_LABELS
from app.platforms.registry import get_hot_crawler, get_session_store
from app.platforms.tenant import normalize_tenant_id
from app.schemas.platform_account import PlatformAccountCreate, PlatformAccountOut, PlatformBindingStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _vnc_url_for_platform(settings: Settings, platform: str) -> str:
    if platform == "douyin":
        return settings.douyin_vnc_url
    if platform == "xiaohongshu":
        return settings.xhs_vnc_url
    if platform == "kuaishou":
        return settings.kuaishou_vnc_url
    return settings.douyin_vnc_url


class PlatformAccountStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _index_path(self, tenant_id: str):
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "accounts" / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_index(self, tenant_id: str) -> dict:
        path = self._index_path(tenant_id)
        if not path.exists():
            return {"items": [], "active_account_id": "default"}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"items": [], "active_account_id": "default"}
        raw.setdefault("items", [])
        raw.setdefault("active_account_id", "default")
        return raw

    def _save_index(self, tenant_id: str, payload: dict) -> None:
        path = self._index_path(tenant_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_default(self, tenant_id: str) -> dict:
        raw = self._load_index(tenant_id)
        items = list(raw.get("items") or [])
        if not any(item.get("id") == "default" for item in items):
            now = _utc_now().isoformat()
            items.insert(
                0,
                {"id": "default", "label": "默认账号", "created_at": now, "updated_at": now},
            )
            raw["items"] = items
            raw["active_account_id"] = raw.get("active_account_id") or "default"
            self._save_index(tenant_id, raw)
        return raw

    def list_accounts(self, tenant_id: str) -> list[PlatformAccountOut]:
        raw = self._ensure_default(tenant_id)
        return [PlatformAccountOut.model_validate(item) for item in raw.get("items", [])]

    def get_active_account_id(self, tenant_id: str) -> str:
        raw = self._ensure_default(tenant_id)
        return normalize_account_id(raw.get("active_account_id"))

    def set_active_account(self, tenant_id: str, account_id: str) -> str:
        account_id = normalize_account_id(account_id)
        raw = self._ensure_default(tenant_id)
        ids = {item.get("id") for item in raw.get("items", [])}
        if account_id not in ids:
            raise KeyError(account_id)
        raw["active_account_id"] = account_id
        self._save_index(tenant_id, raw)
        return account_id

    def create_account(self, tenant_id: str, payload: PlatformAccountCreate) -> PlatformAccountOut:
        raw = self._ensure_default(tenant_id)
        account_id = normalize_account_id(payload.id)
        items = list(raw.get("items") or [])
        if any(item.get("id") == account_id for item in items):
            raise ValueError(f"账号 ID 已存在: {account_id}")
        now = _utc_now().isoformat()
        record = {
            "id": account_id,
            "label": payload.label.strip(),
            "created_at": now,
            "updated_at": now,
        }
        items.append(record)
        raw["items"] = items
        self._save_index(tenant_id, raw)
        return PlatformAccountOut.model_validate(record)

    def delete_account(self, tenant_id: str, account_id: str) -> bool:
        account_id = normalize_account_id(account_id)
        if account_id == "default":
            raise ValueError("不能删除默认账号")
        raw = self._ensure_default(tenant_id)
        items = list(raw.get("items") or [])
        new_items = [item for item in items if item.get("id") != account_id]
        if len(new_items) == len(items):
            return False
        raw["items"] = new_items
        if raw.get("active_account_id") == account_id:
            raw["active_account_id"] = "default"
        self._save_index(tenant_id, raw)
        return True

    def get_account(self, tenant_id: str, account_id: str) -> PlatformAccountOut | None:
        account_id = normalize_account_id(account_id)
        for item in self.list_accounts(tenant_id):
            if item.id == account_id:
                return item
        return None

    def platform_bindings(self, tenant_id: str, account_id: str) -> list[PlatformBindingStatus]:
        account_id = normalize_account_id(account_id)
        bindings: list[PlatformBindingStatus] = []
        for platform in sorted(BINDABLE_PLATFORMS):
            store = get_session_store(self.settings, platform)
            status = store.login_status(tenant_id, account_id)
            bindings.append(
                PlatformBindingStatus(
                    platform=platform,
                    platform_label=PLATFORM_LABELS.get(platform, platform),
                    status=status.get("status", "missing"),
                    message=str(status.get("message") or ""),
                    cookie_count=int(status.get("cookie_count") or 0),
                    vnc_url=_vnc_url_for_platform(self.settings, platform),
                )
            )
        return bindings

    async def start_server_login(self, tenant_id: str, platform: str, account_id: str) -> dict:
        from app.platforms.interactive_login import restart_interactive_login_for_platform

        platform = platform.strip().lower()
        if platform not in BINDABLE_PLATFORMS:
            raise ValueError(f"不支持绑定的平台: {platform}")
        account_id = normalize_account_id(account_id)
        if self.get_account(tenant_id, account_id) is None:
            raise KeyError(account_id)
        stopped = await restart_interactive_login_for_platform(tenant_id, account_id, platform)
        crawler = get_hot_crawler(self.settings, platform, tenant_id, account_id=account_id)
        result = await crawler.start_interactive_login_session()
        if stopped:
            labels = ", ".join(stopped)
            result = {
                **result,
                "stopped_platforms": stopped,
                "message": f"已关闭 {labels} 的旧窗口；{result.get('message', '')}".strip(),
            }
        store = get_session_store(self.settings, platform)
        return {
            **result,
            "storage_state_path": str(store.path_for(tenant_id, account_id)),
            "vnc_url": _vnc_url_for_platform(self.settings, platform),
        }

    def upload_storage_state(
        self, tenant_id: str, platform: str, account_id: str, storage_state: dict
    ) -> dict:
        platform = platform.strip().lower()
        if platform not in BINDABLE_PLATFORMS:
            raise ValueError(f"不支持绑定的平台: {platform}")
        account_id = normalize_account_id(account_id)
        if self.get_account(tenant_id, account_id) is None:
            raise KeyError(account_id)
        store = get_session_store(self.settings, platform)
        path = store.save_dict(tenant_id, storage_state, account_id)
        status = store.login_status(tenant_id, account_id)
        return {"storage_state_path": str(path), **status}
