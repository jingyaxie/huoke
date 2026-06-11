from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class XhsSearchNotesRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100, description="搜索关键词")
    limit: int = Field(default=10, ge=1, le=20, description="返回笔记数量上限")
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")


class XhsNoteCommentsRequest(BaseModel):
    note_url: str = Field(description="小红书笔记链接")
    max_comments: int = Field(default=200, ge=1, le=500, description="顶层评论抓取上限")
    show_browser: bool = False


class XhsKeywordCommentsRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=3, ge=1, le=20, description="搜索笔记数量")
    max_comments: int = Field(default=200, ge=1, le=500, description="每个笔记的顶层评论上限")
    show_browser: bool = False
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = None


class XhsUserTarget(BaseModel):
    """评论用户或任意小红书用户定位（单次仅操作一人）。"""

    user_id: str = Field(min_length=1, description="用户 user_id，用于拼主页 URL 和关注接口")
    username: Optional[str] = Field(default=None, description="昵称，仅用于报告展示")


class XhsFollowUserRequest(XhsUserTarget):
    show_browser: bool = False


class XhsSendMessageRequest(XhsUserTarget):
    message: str = Field(min_length=1, max_length=500, description="私信内容")
    show_browser: bool = False


class XhsToolResponse(BaseModel):
    ok: bool
    platform: Literal["xiaohongshu"] = "xiaohongshu"
    tenant_id: str
    account_id: str
    tool: str
    data: dict
    diagnostic: Optional[str] = None
    report_file: Optional[str] = None
