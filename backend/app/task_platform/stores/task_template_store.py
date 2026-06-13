from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.task_platform.schemas.template import TaskPhaseDefinition, TaskTemplateOut

_BUILTIN_ROOT = Path(__file__).resolve().parents[2] / "task_templates"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class TaskTemplateStore:
    """任务模板仓库：内置 JSON + 租户覆盖（storage/tenants/{id}/task_templates）。"""

    def __init__(self, storage_root: Path | None = None) -> None:
        self.storage_root = storage_root

    def _tenant_root(self, tenant_id: str) -> Path | None:
        if self.storage_root is None:
            return None
        return self.storage_root / "tenants" / tenant_id / "task_templates"

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _parse_template(self, raw: dict[str, Any], *, scope: str) -> TaskTemplateOut:
        phases = [TaskPhaseDefinition.model_validate(item) for item in (raw.get("phases") or [])]
        return TaskTemplateOut(
            template_id=str(raw["template_id"]),
            version=str(raw.get("version") or "1.0.0"),
            name=str(raw.get("name") or raw["template_id"]),
            description=str(raw.get("description") or ""),
            executor_id=str(raw["executor_id"]),
            platforms=list(raw.get("platforms") or []),
            phases=phases,
            default_spec=dict(raw.get("default_spec") or {}),
            scope=scope,  # type: ignore[arg-type]
        )

    def _iter_builtin(self) -> list[TaskTemplateOut]:
        items: list[TaskTemplateOut] = []
        if not _BUILTIN_ROOT.exists():
            return items
        for template_dir in sorted(_BUILTIN_ROOT.iterdir()):
            if not template_dir.is_dir():
                continue
            versions = sorted(template_dir.glob("v*.json"))
            if not versions:
                continue
            raw = self._load_json(versions[-1])
            items.append(self._parse_template(raw, scope="global"))
        return items

    def _iter_tenant(self, tenant_id: str) -> list[TaskTemplateOut]:
        root = self._tenant_root(tenant_id)
        if root is None or not root.exists():
            return []
        items: list[TaskTemplateOut] = []
        for template_dir in sorted(root.iterdir()):
            if not template_dir.is_dir():
                continue
            versions = sorted(template_dir.glob("v*.json"))
            if not versions:
                continue
            raw = self._load_json(versions[-1])
            items.append(self._parse_template(raw, scope="tenant"))
        return items

    def list_templates(self, tenant_id: str | None = None) -> list[TaskTemplateOut]:
        by_id: dict[str, TaskTemplateOut] = {t.template_id: t for t in self._iter_builtin()}
        if tenant_id:
            for item in self._iter_tenant(tenant_id):
                by_id[item.template_id] = item
        return list(by_id.values())

    def get(self, template_id: str, *, tenant_id: str | None = None, version: str | None = None) -> TaskTemplateOut | None:
        candidates: list[TaskTemplateOut] = []
        if tenant_id:
            for item in self._iter_tenant(tenant_id):
                if item.template_id == template_id:
                    candidates.append(item)
        for item in self._iter_builtin():
            if item.template_id == template_id:
                candidates.append(item)
        if not candidates:
            return None
        if version:
            for item in candidates:
                if item.version == version:
                    return item
            return None
        # tenant 优先于 global
        tenant_items = [c for c in candidates if c.scope == "tenant"]
        if tenant_items:
            return tenant_items[-1]
        return candidates[-1]

    def merge_spec(self, template: TaskTemplateOut, user_spec: dict[str, Any]) -> dict[str, Any]:
        return _deep_merge(template.default_spec, user_spec)


@lru_cache
def get_task_template_store() -> TaskTemplateStore:
    from app.core.config import get_settings

    settings = get_settings()
    return TaskTemplateStore(storage_root=settings.storage_root)
