from __future__ import annotations

from typing import Any

TASK_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_task_templates",
        "create_structured_task",
    }
)

TASK_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_task_templates",
            "description": (
                "列出当前租户可用的任务模板（lead-crawl、lead-acquisition 等）。"
                "创建外部任务前可先查询模板结构与默认参数。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_structured_task",
            "description": (
                "将外部系统原始 JSON 编译为结构化任务并创建实例。"
                "适用于盈小蚁等外部表单字段；内部会先规则映射再必要时 LLM 补全，"
                "成功后返回 task_id 与编译摘要。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "raw_payload": {
                        "type": "object",
                        "description": "外部原始 JSON，如盈小蚁创建任务表单字段",
                    },
                    "adapter_id": {
                        "type": "string",
                        "description": "适配器 ID，盈小蚁默认 yingxiaoyi-lead-v1",
                    },
                    "intent": {
                        "type": "string",
                        "description": "意图：lead_crawl / lead_acquisition",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "执行账号 ID，默认当前 Agent 会话账号",
                    },
                    "auto_submit": {
                        "type": "boolean",
                        "description": "创建后是否自动 submit 入队，默认 true",
                    },
                    "force_llm": {
                        "type": "boolean",
                        "description": "跳过规则层强制走 LLM 编译",
                    },
                },
                "required": ["raw_payload"],
            },
        },
    },
]
