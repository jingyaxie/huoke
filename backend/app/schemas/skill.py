from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SkillType = Literal["instruction", "actions", "builtin"]
SkillScope = Literal["tenant", "global"]
ParamType = Literal["string", "integer", "number", "boolean"]

BUILTIN_HANDLERS = {
    "crawl_hot": "抓取当前平台热榜并入库",
    "crawl_video_comments": "抓取单个视频/笔记的全部评论",
    "crawl_keyword_comments": "按关键词搜索并批量抓取评论",
    "search_videos": "按关键词搜索并返回结构化视频列表（接口拦截）",
    "login_status": "检查当前平台登录状态",
}

SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def skill_tool_name(skill_id: str) -> str:
    safe = skill_id.replace("-", "_")
    return f"skill_{safe}"


def skill_id_from_tool_name(tool_name: str) -> str | None:
    if not tool_name.startswith("skill_"):
        return None
    return tool_name[len("skill_") :].replace("_", "-")


class SkillParameter(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: ParamType = "string"
    description: str = ""
    required: bool = False
    default: str | int | float | bool | None = None


class SkillAction(BaseModel):
    tool: str = Field(..., min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class SkillBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=500)
    type: SkillType = "instruction"
    enabled: bool = True
    disable_model_invocation: bool = False
    parameters: list[SkillParameter] = Field(default_factory=list)
    content: str = ""
    actions: list[SkillAction] = Field(default_factory=list)
    builtin_handler: str | None = None

    @field_validator("builtin_handler")
    @classmethod
    def validate_builtin_handler(cls, value: str | None) -> str | None:
        if value is not None and value not in BUILTIN_HANDLERS:
            raise ValueError(f"不支持的内置处理器: {value}")
        return value


class SkillCreate(SkillBase):
    id: str = Field(..., min_length=2, max_length=64)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not SKILL_ID_PATTERN.match(normalized):
            raise ValueError("技能 ID 仅允许小写字母、数字、下划线、连字符，且以字母开头")
        return normalized


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    type: SkillType | None = None
    enabled: bool | None = None
    disable_model_invocation: bool | None = None
    parameters: list[SkillParameter] | None = None
    content: str | None = None
    actions: list[SkillAction] | None = None
    builtin_handler: str | None = None

    @field_validator("builtin_handler")
    @classmethod
    def validate_builtin_handler(cls, value: str | None) -> str | None:
        if value is not None and value not in BUILTIN_HANDLERS:
            raise ValueError(f"不支持的内置处理器: {value}")
        return value


class SkillOut(SkillBase):
    id: str
    scope: SkillScope = "tenant"
    tool_name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillUsageRecordOut(BaseModel):
    run_id: str
    timestamp: datetime | None = None
    status: str
    score: int = Field(ge=0, le=100)
    reason: str = ""
    tool_name: str
    summary: str = ""


class SkillEffectStatsOut(BaseModel):
    skill_id: str
    total: int = 0
    success: int = 0
    failed: int = 0
    success_rate: float = 0.0
    average_score: float = 0.0
    last_score: int | None = None
    blocked: int = 0
    blocked_rate: float = 0.0
    risk_level: str = "low"


class SkillEffectDetailOut(BaseModel):
    skill_id: str
    stats: SkillEffectStatsOut
    records: list[SkillUsageRecordOut] = Field(default_factory=list)


class SkillListResponse(BaseModel):
    items: list[SkillOut]
    total: int


class BuiltinHandlerOut(BaseModel):
    id: str
    description: str


class SkillExportBundle(BaseModel):
    version: int = 1
    skills: list[dict[str, Any]] = Field(default_factory=list)


class SkillImportRequest(BaseModel):
    overwrite: bool = False
    skills: list[SkillCreate] = Field(default_factory=list)


class SkillImportMarkdownRequest(BaseModel):
    content: str = Field(..., min_length=1)
    overwrite: bool = False


class SkillParseMarkdownResponse(BaseModel):
    skill: SkillCreate
    markdown_preview: str | None = None


class SkillRecordFromStepsRequest(BaseModel):
    id: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=500)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    parameters: list[SkillParameter] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not SKILL_ID_PATTERN.match(normalized):
            raise ValueError("技能 ID 仅允许小写字母、数字、下划线、连字符，且以字母开头")
        return normalized


class SkillImportResult(BaseModel):
    imported: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
