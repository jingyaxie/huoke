from __future__ import annotations

from typing import Any, Protocol


class RuleTaskAdapter(Protocol):
    adapter_id: str
    template_id: str

    def compile_payload(self, raw: dict[str, Any], *, intent: str | None = None) -> dict[str, Any]: ...


class TaskAdapterRegistry:
    _adapters: dict[str, RuleTaskAdapter] = {}

    @classmethod
    def register(cls, adapter: RuleTaskAdapter) -> None:
        cls._adapters[adapter.adapter_id] = adapter

    @classmethod
    def get(cls, adapter_id: str) -> RuleTaskAdapter | None:
        return cls._adapters.get(adapter_id)

    @classmethod
    def all_ids(cls) -> list[str]:
        return list(cls._adapters.keys())
