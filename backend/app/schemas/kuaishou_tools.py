from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class KuaishouSearchVideosRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100, description="搜索关键词")
    limit: int = Field(default=10, ge=1, le=20, description="返回视频数量上限")
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")


class KuaishouVideoCommentsRequest(BaseModel):
    video_url: str = Field(description="快手视频链接，如 https://www.kuaishou.com/short-video/{photo_id}")
    max_comments: int = Field(default=200, ge=1, le=500, description="顶层评论抓取上限")
    show_browser: bool = False


class KuaishouKeywordCommentsRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=3, ge=1, le=20, description="搜索视频数量")
    max_comments: int = Field(default=200, ge=1, le=500, description="每个视频的顶层评论上限")
    show_browser: bool = False
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = None


class KuaishouUserTarget(BaseModel):
    user_id: str = Field(min_length=1, description="用户 user_id（authorId），用于拼主页 URL 和关注接口")
    username: Optional[str] = Field(default=None, description="昵称，仅用于报告展示")


class KuaishouFollowUserRequest(KuaishouUserTarget):
    show_browser: bool = False


class KuaishouSendMessageRequest(KuaishouUserTarget):
    message: str = Field(min_length=1, max_length=500, description="私信内容")
    show_browser: bool = False


class KuaishouToolResponse(BaseModel):
    ok: bool
    platform: Literal["kuaishou"] = "kuaishou"
    tenant_id: str
    account_id: str
    tool: str
    data: dict
    diagnostic: Optional[str] = None
    report_file: Optional[str] = None
