from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.skill import SkillCreate, SkillOut, SkillScope, SkillUpdate, skill_tool_name


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_GLOBAL_SKILLS: list[dict] = [
    {
        "id": "douyin-hot-list",
        "name": "打开抖音热榜",
        "description": "导航到抖音热榜页面并读取热点标题列表",
        "type": "actions",
        "enabled": True,
        "scope": "global",
        "parameters": [],
        "content": "",
        "actions": [
            {"tool": "browser_goto", "args": {"url": "https://www.douyin.com/hot"}},
            {"tool": "browser_wait", "args": {"timeout_ms": 3000}},
            {"tool": "browser_get_text", "args": {}},
        ],
        "builtin_handler": None,
    },
    {
        "id": "douyin-search-keyword",
        "name": "抖音关键词搜索",
        "description": "在抖音网页版搜索指定关键词并查看搜索结果",
        "type": "instruction",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {
                "name": "keyword",
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            }
        ],
        "content": (
            "抖音关键词搜索（已验证）：热榜入口→搜索框→拦截 general/search/single。\n"
            "1. browser_browse url=https://www.douyin.com/hot scroll_rounds=1\n"
            "2. browser_click [data-e2e=\"searchbar-input\"] → browser_fill {{keyword}} → Enter\n"
            "3. browser_wait_api url_contains=general/search/single 或 search/item\n"
            "4. browser_get_network_data 解析 aweme_id 后 task_complete\n"
            "禁止打开 /search/ URL；须 DOUYIN_HEADLESS=false"
        ),
        "actions": [],
        "builtin_handler": None,
    },
    {
        "id": "douyin-keyword-comments",
        "name": "抖音关键词视频+评论（已验证）",
        "description": "热榜入口搜索框→抓评论，一键 builtin，PlaywrightPool 持久 Profile",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {"name": "keyword", "type": "string", "description": "搜索关键词", "required": True},
            {"name": "limit", "type": "integer", "description": "抓取视频数量", "required": False, "default": 3},
            {"name": "show_browser", "type": "boolean", "description": "使用 VNC 可见浏览器", "required": False, "default": False},
        ],
        "content": "已验证生产链路，直接调用即可。",
        "actions": [],
        "builtin_handler": "crawl_keyword_comments",
    },
    {
        "id": "crawl-hot",
        "name": "抓取热榜入库",
        "description": "调用后端爬虫抓取当前平台热榜数据并写入数据库",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {
                "name": "limit",
                "type": "integer",
                "description": "抓取数量上限",
                "required": False,
                "default": 50,
            }
        ],
        "content": "",
        "actions": [],
        "builtin_handler": "crawl_hot",
    },
    {
        "id": "check-login",
        "name": "检查登录状态",
        "description": "检查当前平台是否已登录",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [],
        "content": "",
        "actions": [],
        "builtin_handler": "login_status",
    },
    {
        "id": "crawl-video-comments",
        "name": "单个视频评论抓取",
        "description": "抓取单个视频/笔记的全部评论，支持 item_id、douyin.com/video 等",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {
                "name": "video_url",
                "type": "string",
                "description": "视频链接：item_id / douyin.com/video/...",
                "required": True,
            },
            {
                "name": "show_browser",
                "type": "boolean",
                "description": "是否显示浏览器窗口",
                "required": False,
                "default": False,
            },
        ],
        "content": "",
        "actions": [],
        "builtin_handler": "crawl_video_comments",
    },
    {
        "id": "crawl-keyword-comments",
        "name": "关键词批量评论抓取",
        "description": "按关键词搜索视频并批量抓取前 N 个视频的全部评论",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {
                "name": "keyword",
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            },
            {
                "name": "limit",
                "type": "integer",
                "description": "抓取视频数量",
                "required": False,
                "default": 3,
            },
            {
                "name": "days",
                "type": "integer",
                "description": "最近天数筛选",
                "required": False,
                "default": 3,
            },
            {
                "name": "region",
                "type": "string",
                "description": "地区筛选，可选",
                "required": False,
            },
            {
                "name": "show_browser",
                "type": "boolean",
                "description": "是否显示浏览器窗口",
                "required": False,
                "default": False,
            },
        ],
        "content": "",
        "actions": [],
        "builtin_handler": "crawl_keyword_comments",
    },
    {
        "id": "search-videos",
        "name": "关键词搜索视频列表",
        "description": "按关键词搜索抖音视频，拦截搜索接口返回结构化列表（标题、作者、点赞、链接）",
        "type": "builtin",
        "enabled": True,
        "scope": "global",
        "parameters": [
            {
                "name": "keyword",
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            },
            {
                "name": "limit",
                "type": "integer",
                "description": "返回视频数量上限",
                "required": False,
                "default": 20,
            },
            {
                "name": "show_browser",
                "type": "boolean",
                "description": "是否显示浏览器窗口",
                "required": False,
                "default": False,
            },
        ],
        "content": "",
        "actions": [],
        "builtin_handler": "search_videos",
    },
    {
        "id": "douyin-reply-comment",
        "name": "抖音回复评论",
        "description": "在抖音视频页定位指定评论并发表回复（需已登录）",
        "type": "instruction",
        "enabled": True,
        "disable_model_invocation": True,
        "scope": "global",
        "parameters": [
            {
                "name": "comment_hint",
                "type": "string",
                "description": "目标评论定位：用户名或评论内容片段",
                "required": True,
            },
            {
                "name": "reply_text",
                "type": "string",
                "description": "回复内容",
                "required": True,
            },
            {
                "name": "video_url",
                "type": "string",
                "description": "视频链接；已在视频页时可留空",
                "required": False,
            },
        ],
        "content": (
            "执行抖音视频评论回复任务。必须已登录，未登录则 task_failed。\n\n"
            "参数：\n"
            "- 视频链接：{{video_url}}（可空，表示使用当前页）\n"
            "- 目标评论：{{comment_hint}}（用户名或评论文字片段）\n"
            "- 回复内容：{{reply_text}}\n\n"
            "步骤：\n"
            "1. 若 {{video_url}} 非空且当前不在该视频页，browser_goto 到 {{video_url}}；"
            "否则 browser_get_page_info 确认在 douyin.com 视频页\n"
            "2. browser_wait 2-3 秒；若评论未展开，browser_click 评论入口："
            "`[data-e2e=\"feed-comment-icon\"]`、`[data-e2e*=\"comment\"]` 或 `text=评论`\n"
            "3. browser_scroll direction=down 多次，直到页面文本中出现 {{comment_hint}}\n"
            "4. 在含 {{comment_hint}} 的评论行内 browser_click「回复」：`text=回复`\n"
            "5. browser_fill 回复框，依次尝试 "
            "`[data-e2e=\"comment-input\"]`、`textarea[placeholder*=\"评论\"]`，填入 {{reply_text}}\n"
            "6. browser_click 发送：`[data-e2e=\"comment-post\"]`、`text=发送`，或 browser_press Enter\n"
            "7. browser_wait 后 browser_get_text 确认出现 {{reply_text}}；成功 task_complete，否则 task_failed\n\n"
            "注意：一次只回复一条；遇到验证码/登录墙 task_failed；发送前核对目标评论无误。"
        ),
        "actions": [],
        "builtin_handler": None,
    },
    {
        "id": "douyin-follow-user",
        "name": "抖音关注用户",
        "description": "进入抖音用户主页并点击关注（支持从评论点头像或直达主页链接）",
        "type": "instruction",
        "enabled": True,
        "disable_model_invocation": True,
        "scope": "global",
        "parameters": [
            {
                "name": "user_profile_url",
                "type": "string",
                "description": "用户主页链接 https://www.douyin.com/user/...",
                "required": False,
            },
            {
                "name": "username",
                "type": "string",
                "description": "当前页评论/视频中的用户名（无主页链接时使用）",
                "required": False,
            },
        ],
        "content": (
            "执行抖音关注用户任务。必须已登录。\n\n"
            "参数（至少填一项，优先 user_profile_url）：\n"
            "- 用户主页：{{user_profile_url}}\n"
            "- 用户名：{{username}}（从当前页点头像/昵称进入主页）\n\n"
            "进入主页：\n"
            "A) 若 {{user_profile_url}} 非空：browser_goto 到该链接\n"
            "B) 若仅有 {{username}}：browser_click 含该昵称的链接或头像 "
            "（`a:has-text(\"{{username}}\")`、评论区内 img/avatar），等待 URL 含 /user/\n"
            "C) 两者都空：task_failed 缺少用户定位信息\n\n"
            "关注：\n"
            "1. browser_wait 2 秒，browser_get_page_info 确认在用户主页\n"
            "2. browser_get_text 若已有「已关注」「互相关注」，task_complete 说明已关注\n"
            "3. browser_click 关注按钮：`[data-e2e=\"user-follow-btn\"]`、`[data-e2e*=\"follow\"]`、"
            "`button:has-text(\"关注\")`（勿点「已关注」）\n"
            "4. browser_wait 后确认按钮变为「已关注」/「互相关注」，task_complete\n\n"
            "注意：单次只关注一人；遇到验证码 task_failed。"
        ),
        "actions": [],
        "builtin_handler": None,
    },
    {
        "id": "douyin-send-dm",
        "name": "抖音发送私信",
        "description": "进入抖音用户主页并发送私信（需已登录，可能受互关/隐私限制）",
        "type": "instruction",
        "enabled": True,
        "disable_model_invocation": True,
        "scope": "global",
        "parameters": [
            {
                "name": "message",
                "type": "string",
                "description": "私信内容",
                "required": True,
            },
            {
                "name": "user_profile_url",
                "type": "string",
                "description": "用户主页链接",
                "required": False,
            },
            {
                "name": "username",
                "type": "string",
                "description": "当前页用户名（无主页链接时使用）",
                "required": False,
            },
        ],
        "content": (
            "执行抖音发私信任务。必须已登录。\n\n"
            "参数：\n"
            "- 私信内容：{{message}}\n"
            "- 用户主页：{{user_profile_url}}（可空）\n"
            "- 用户名：{{username}}（可空，从当前页进入主页）\n\n"
            "进入主页（同 douyin-follow-user）：优先 browser_goto {{user_profile_url}}；"
            "否则 browser_click {{username}} 的头像/昵称进入 /user/ 页\n\n"
            "发私信：\n"
            "1. browser_click 私信入口：`[data-e2e=\"user-info-message-btn\"]`、"
            "`[data-e2e*=\"message\"]`、`button:has-text(\"私信\")`\n"
            "2. browser_wait 等待聊天面板出现（侧栏或 /im 页面）\n"
            "3. browser_fill 输入框：`[data-e2e=\"message-input\"]`、"
            "`textarea[placeholder*=\"消息\"]`、`div[contenteditable=\"true\"]`，填入 {{message}}\n"
            "4. browser_click 发送或 browser_press Enter\n"
            "5. browser_get_text 确认 {{message}} 出现在聊天记录，task_complete\n\n"
            "若提示无法私信、需互关或未开启私信，task_failed 并说明原因。"
        ),
        "actions": [],
        "builtin_handler": None,
    },
]


class SkillStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.global_path = settings.storage_root / "skills" / "global.json"
        self.global_path.parent.mkdir(parents=True, exist_ok=True)

    def _tenant_path(self, tenant_id: str) -> Path:
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "skills.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_global_defaults(self) -> None:
        if not self.global_path.exists():
            now = _utc_now().isoformat()
            payload = {
                "skills": [
                    {**skill, "created_at": now, "updated_at": now}
                    for skill in DEFAULT_GLOBAL_SKILLS
                ]
            }
            self.global_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
        self._merge_missing_global_defaults()

    def _merge_missing_global_defaults(self) -> None:
        existing = self._load_raw(self.global_path)
        existing_ids = {s.get("id") for s in existing}
        now = _utc_now().isoformat()
        changed = False
        for skill in DEFAULT_GLOBAL_SKILLS:
            if skill["id"] in existing_ids:
                continue
            existing.append({**skill, "created_at": now, "updated_at": now})
            changed = True
        if changed:
            self.global_path.write_text(
                json.dumps({"skills": existing}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load_raw(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            skills = raw.get("skills", [])
        elif isinstance(raw, list):
            skills = raw
        else:
            raise ValueError("skills 文件格式无效")
        if not isinstance(skills, list):
            raise ValueError("skills 必须是数组")
        return skills

    def _to_out(self, raw: dict, scope: SkillScope) -> SkillOut:
        data = dict(raw)
        data["scope"] = scope
        data["tool_name"] = skill_tool_name(data["id"])
        return SkillOut.model_validate(data)

    def list_all(self, tenant_id: str, *, include_disabled: bool = True) -> list[SkillOut]:
        self._ensure_global_defaults()
        merged: dict[str, SkillOut] = {}
        for raw in self._load_raw(self.global_path):
            skill = self._to_out(raw, "global")
            merged[skill.id] = skill
        for raw in self._load_raw(self._tenant_path(tenant_id)):
            skill = self._to_out(raw, "tenant")
            merged[skill.id] = skill
        items = list(merged.values())
        if not include_disabled:
            items = [s for s in items if s.enabled]
        return sorted(items, key=lambda s: (s.scope != "global", s.name))

    def list_enabled(self, tenant_id: str) -> list[SkillOut]:
        return self.list_all(tenant_id, include_disabled=False)

    def get(self, tenant_id: str, skill_id: str) -> SkillOut | None:
        for skill in self.list_all(tenant_id, include_disabled=True):
            if skill.id == skill_id:
                return skill
        return None

    def create(self, tenant_id: str, payload: SkillCreate, *, scope: SkillScope = "tenant") -> SkillOut:
        path = self.global_path if scope == "global" else self._tenant_path(tenant_id)
        if scope == "global":
            self._ensure_global_defaults()
        skills = self._load_raw(path)
        if any(s.get("id") == payload.id for s in skills):
            raise ValueError(f"技能 ID 已存在: {payload.id}")
        now = _utc_now().isoformat()
        record = payload.model_dump()
        record["scope"] = scope
        record["created_at"] = now
        record["updated_at"] = now
        skills.append(record)
        path.write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(record, scope)

    def update(self, tenant_id: str, skill_id: str, payload: SkillUpdate) -> SkillOut:
        skill = self.get(tenant_id, skill_id)
        if skill is None:
            raise KeyError(skill_id)
        path = self.global_path if skill.scope == "global" else self._tenant_path(tenant_id)
        skills = self._load_raw(path)
        updated: dict | None = None
        for idx, raw in enumerate(skills):
            if raw.get("id") != skill_id:
                continue
            merged = dict(raw)
            for key, value in payload.model_dump(exclude_none=True).items():
                merged[key] = value
            merged["updated_at"] = _utc_now().isoformat()
            skills[idx] = merged
            updated = merged
            break
        if updated is None:
            raise KeyError(skill_id)
        path.write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(updated, skill.scope)

    def delete(self, tenant_id: str, skill_id: str) -> bool:
        skill = self.get(tenant_id, skill_id)
        if skill is None:
            return False
        if skill.scope == "global":
            raise ValueError("不能删除全局内置技能，可将其 disabled 设为 false")
        path = self._tenant_path(tenant_id)
        skills = self._load_raw(path)
        new_skills = [s for s in skills if s.get("id") != skill_id]
        if len(new_skills) == len(skills):
            return False
        path.write_text(json.dumps({"skills": new_skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def load_safe(self, tenant_id: str) -> list[SkillOut]:
        try:
            return self.list_enabled(tenant_id)
        except (json.JSONDecodeError, ValidationError, ValueError):
            return []

    def list_tenant_raw(self, tenant_id: str) -> list[dict]:
        return self._load_raw(self._tenant_path(tenant_id))

    def export_tenant_skills(self, tenant_id: str, skill_ids: list[str] | None = None) -> list[dict]:
        skills = self.list_tenant_raw(tenant_id)
        if skill_ids:
            wanted = set(skill_ids)
            skills = [s for s in skills if s.get("id") in wanted]
        exportable: list[dict] = []
        for raw in skills:
            item = {k: v for k, v in raw.items() if k not in {"scope", "tool_name"}}
            exportable.append(item)
        return exportable

    def import_skills(
        self,
        tenant_id: str,
        payloads: list[SkillCreate],
        *,
        overwrite: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        imported: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        for payload in payloads:
            try:
                existing = self.get(tenant_id, payload.id)
                if existing and existing.scope == "tenant":
                    if overwrite:
                        self.update(tenant_id, payload.id, SkillUpdate(**payload.model_dump()))
                        imported.append(payload.id)
                    else:
                        skipped.append(payload.id)
                elif existing and existing.scope == "global":
                    if overwrite:
                        self.create(tenant_id, payload, scope="tenant")
                        imported.append(payload.id)
                    else:
                        skipped.append(payload.id)
                else:
                    self.create(tenant_id, payload, scope="tenant")
                    imported.append(payload.id)
            except Exception as exc:
                errors.append(f"{payload.id}: {exc}")
        return imported, skipped, errors
