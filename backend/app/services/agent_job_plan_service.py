from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings
from app.task_platform.adapters.yingxiaoyi_lead_v1 import YingxiaoyiLeadV1Adapter
from app.task_platform.stores.task_template_store import TaskTemplateStore

CAPABILITY_LABELS: dict[str, str] = {
    "pipeline_keyword_comments": "关键词视频评论抓取",
    "internal.normalize_leads": "线索标准化",
    "internal.match_leads": "线索匹配筛选",
    "social_roam_outreach": "评论 / 关注 / 私信触达",
    "internal.summarize": "汇总执行结果",
}

AGENT_RUNTIME_STEPS: list[dict[str, str]] = [
    {"id": "plan", "stage": "plan", "action": "解析用户目标与约束"},
    {"id": "execute", "stage": "execute", "action": "执行浏览器 / 技能链路并收集证据"},
    {"id": "validate", "stage": "validate", "action": "校验结果置信度与问题列表"},
    {"id": "finalize", "stage": "finalize", "action": "输出摘要与结构化结果"},
]


def _step(
    *,
    step_id: str,
    stage: str,
    action: str,
    capability: str = "",
    status: str = "pending",
    order: int,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "stage": stage,
        "action": action,
        "capability": capability,
        "status": status,
        "order": order,
    }


def _plan_from_template(template_id: str, *, settings: Settings | None) -> dict[str, Any]:
    store = TaskTemplateStore(settings.storage_root if settings else None)
    template = store.get(template_id)
    if template is None:
        return _plan_generic_agent()
    steps = [
        _step(
            step_id=phase.id,
            stage=phase.id,
            action=CAPABILITY_LABELS.get(phase.capability, phase.capability),
            capability=phase.capability,
            order=idx + 1,
        )
        for idx, phase in enumerate(template.phases)
    ]
    return {
        "source": "task_template",
        "template_id": template.template_id,
        "template_name": template.name,
        "template_version": template.version,
        "executor_id": template.executor_id,
        "steps": steps,
    }


def _unwrap_task_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """支持 compile-and-create 外层包装：提取 raw_payload 与 intent。"""
    intent = raw.get("intent")
    if intent is not None:
        intent = str(intent)
    nested = raw.get("raw_payload")
    if isinstance(nested, dict) and (
        nested.get("keyword") or nested.get("task_name") or nested.get("product_keyword")
    ):
        return nested, intent
    return raw, intent


def _looks_like_yingxiaoyi_payload(raw: dict[str, Any]) -> bool:
    payload, _ = _unwrap_task_payload(raw)
    return bool(payload.get("keyword") or payload.get("task_name") or payload.get("product_keyword"))


def _build_outreach_policy(spec: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    """从编译 spec 提取评论/私信分流与配额规则。"""
    action_policy = spec.get("action_policy") if isinstance(spec.get("action_policy"), dict) else {}
    daily_limits = spec.get("daily_limits") if isinstance(spec.get("daily_limits"), dict) else {}

    comment_ratio = action_policy.get("comment_ratio", payload.get("comment_ratio"))
    dm_ratio = action_policy.get("dm_ratio", payload.get("dm_ratio"))
    interval_min = action_policy.get("interval_min_sec", payload.get("interval_min"))
    interval_max = action_policy.get("interval_max_sec", payload.get("interval_max"))
    max_follows = daily_limits.get("max_follows", payload.get("daily_follow_limit"))
    max_dms = daily_limits.get("max_dms", payload.get("daily_dm_limit"))
    max_replies = daily_limits.get("max_comment_replies", 30)

    if comment_ratio is None and dm_ratio is None:
        return None

    c_ratio = max(0, min(100, int(comment_ratio or 0)))
    d_ratio = max(0, min(100, int(dm_ratio or 0)))
    total = c_ratio + d_ratio
    comment_prob = round(100 * c_ratio / total, 1) if total else 0.0
    dm_prob = round(100 * d_ratio / total, 1) if total else 0.0

    return {
        "mode": "random_by_ratio",
        "rule_summary": (
            f"每条线索按权重 {c_ratio}:{d_ratio} 随机选择「评论回复」或「私信」"
            f"（约 {comment_prob}% / {dm_prob}%）；"
            f"动作间隔 {interval_min or '—'}~{interval_max or '—'} 秒；"
            f"受日配额约束"
        ),
        "comment_ratio": c_ratio,
        "dm_ratio": d_ratio,
        "comment_prob_pct": comment_prob,
        "dm_prob_pct": dm_prob,
        "interval_min_sec": interval_min,
        "interval_max_sec": interval_max,
        "daily_limits": {
            "max_comment_replies": max_replies,
            "max_follows": max_follows,
            "max_dms": max_dms,
        },
        "sub_actions": [
            {
                "action": "reply",
                "label": "评论回复",
                "weight": c_ratio,
                "prob_pct": comment_prob,
                "description": "在视频下回复用户评论（reply-comment）",
            },
            {
                "action": "dm",
                "label": "私信触达",
                "weight": d_ratio,
                "prob_pct": dm_prob,
                "description": "向匹配用户发送私信（send-dm）",
            },
        ],
        "executor": "LeadOutreachService + choose_outreach_action",
    }


def _attach_outreach_substeps(plan: dict[str, Any], outreach_policy: dict[str, Any] | None) -> None:
    if not outreach_policy:
        return
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if step.get("id") != "outreach":
            continue
        sub_steps = []
        for idx, item in enumerate(outreach_policy.get("sub_actions") or [], start=1):
            sub_steps.append(
                {
                    "order": idx,
                    "action": item.get("action"),
                    "label": item.get("label"),
                    "weight": item.get("weight"),
                    "prob_pct": item.get("prob_pct"),
                    "description": item.get("description"),
                    "status": "pending",
                }
            )
        step["sub_steps"] = sub_steps
        step["policy"] = outreach_policy
        step["action"] = "按规则分流触达（评论 / 私信）"
        break


def _plan_from_yingxiaoyi(
    raw: dict[str, Any],
    *,
    settings: Settings | None,
    intent: str | None = None,
) -> dict[str, Any]:
    payload, wrapped_intent = _unwrap_task_payload(raw)
    effective_intent = intent or wrapped_intent
    adapter = YingxiaoyiLeadV1Adapter()
    compiled = adapter.compile_payload(payload, intent=effective_intent)
    spec = compiled.get("spec") or {}
    crawl = spec.get("crawl") if isinstance(spec.get("crawl"), dict) else {}
    action_policy = spec.get("action_policy") if isinstance(spec.get("action_policy"), dict) else {}
    daily_limits = spec.get("daily_limits") if isinstance(spec.get("daily_limits"), dict) else {}
    outreach_policy = _build_outreach_policy(spec, payload)
    plan = _plan_from_template(str(compiled["template_id"]), settings=settings)
    _attach_outreach_substeps(plan, outreach_policy)
    plan.setdefault(
        "execution_note",
        "编排步骤为编译预览；逐阶段抓取/触达进度请在「任务中心」提交同名任务查看。",
    )
    plan["is_preview"] = True
    plan["execution_mode"] = "agent_async"
    plan.update(
        {
            "source": "yingxiaoyi",
            "adapter_id": raw.get("adapter_id") or adapter.adapter_id,
            "intent": effective_intent,
            "confidence": compiled.get("confidence"),
            "reasoning": compiled.get("reasoning"),
            "unmapped_fields": compiled.get("unmapped_fields") or [],
            "outreach_policy": outreach_policy,
            "input_summary": {
                "task_name": spec.get("task_name") or payload.get("task_name"),
                "keyword": spec.get("keyword") or payload.get("keyword"),
                "platform": spec.get("platform") or payload.get("platform"),
                "region": spec.get("region") or payload.get("region"),
                "target_leads": crawl.get("target_leads") or payload.get("target_count"),
                "comment_days": crawl.get("comment_days") or payload.get("comment_days"),
                "video_publish_days": crawl.get("video_publish_days") or payload.get("video_publish_days"),
                "comment_ratio": action_policy.get("comment_ratio", payload.get("comment_ratio")),
                "dm_ratio": action_policy.get("dm_ratio", payload.get("dm_ratio")),
                "interval_sec": (
                    f"{action_policy.get('interval_min_sec', payload.get('interval_min'))}"
                    f"~{action_policy.get('interval_max_sec', payload.get('interval_max'))} 秒"
                    if action_policy.get("interval_min_sec") or payload.get("interval_min")
                    else None
                ),
                "daily_follow_limit": daily_limits.get("max_follows", payload.get("daily_follow_limit")),
                "daily_dm_limit": daily_limits.get("max_dms", payload.get("daily_dm_limit")),
            },
        }
    )
    plan["input_summary"] = {
        k: v for k, v in plan["input_summary"].items() if v is not None and v != ""
    }
    return plan


def _plan_generic_agent() -> dict[str, Any]:
    return {
        "source": "agent",
        "template_id": None,
        "template_name": "Agent 异步任务",
        "steps": [
            _step(step_id=item["id"], stage=item["stage"], action=item["action"], order=idx + 1)
            for idx, item in enumerate(AGENT_RUNTIME_STEPS)
        ],
    }


def build_orchestration_plan(message: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """根据任务内容生成可展示的编排步骤（创建时即可预览）。"""
    text = (message or "").strip()
    if not text:
        return _plan_generic_agent()

    if text.startswith("{"):
        try:
            raw = json.loads(text)
            if isinstance(raw, dict) and _looks_like_yingxiaoyi_payload(raw):
                return _plan_from_yingxiaoyi(raw, settings=settings)
        except json.JSONDecodeError:
            pass

    if text.startswith("/pipeline-keyword-video-comments"):
        plan = _plan_from_template("lead-crawl", settings=settings)
        plan["source"] = "slash_command"
        m = re.search(r"keyword=([^\s]+)", text)
        if m:
            plan["input_summary"] = {"keyword": m.group(1)}
        return plan

    return _plan_generic_agent()


def _sync_template_steps(
    steps: list[dict[str, Any]],
    *,
    job_stage: str,
    job_status: str,
) -> None:
    """Agent Job 运行阶段映射到任务模板编排步骤。"""
    total = len(steps)
    if total == 0:
        return
    progress_map = {"plan": 0, "execute": 1, "validate": max(1, total - 1), "finalize": total}
    progress = progress_map.get(job_stage, 0)

    if job_status == "completed":
        for step in steps:
            step["status"] = "completed"
        return
    if job_status in {"failed", "dead_letter", "cancelled"}:
        done_until = max(0, progress - 1)
        for idx, step in enumerate(steps):
            if idx < done_until:
                step["status"] = "completed"
            elif idx == done_until:
                step["status"] = job_status
            else:
                step["status"] = "pending"
        return
    if job_status in {"running", "retrying"}:
        for idx, step in enumerate(steps):
            if idx < progress - 1:
                step["status"] = "completed"
            elif idx == progress - 1:
                step["status"] = "running"
            else:
                step["status"] = "pending"
        return
    for step in steps:
        step["status"] = "pending"


def sync_orchestration_status(
    orchestration: dict[str, Any],
    *,
    job_stage: str,
    job_status: str,
) -> dict[str, Any]:
    """按 Job 当前阶段更新编排步骤状态。"""
    steps = orchestration.get("steps")
    if not isinstance(steps, list) or not steps:
        return orchestration

    if orchestration.get("source") in {"yingxiaoyi", "task_template", "slash_command", "inferred"}:
        _sync_template_steps(steps, job_stage=job_stage, job_status=job_status)
        orchestration["steps"] = steps
        return orchestration

    stage_ids = [str(item.get("stage") or item.get("id") or "") for item in steps]
    current_idx = stage_ids.index(job_stage) if job_stage in stage_ids else -1

    for idx, step in enumerate(steps):
        if job_status in {"completed"}:
            step["status"] = "completed"
        elif job_status in {"failed", "dead_letter", "cancelled"}:
            if current_idx < 0:
                step["status"] = "pending"
            elif idx < current_idx:
                step["status"] = "completed"
            elif idx == current_idx:
                step["status"] = job_status
            else:
                step["status"] = "pending"
        elif job_status in {"running", "retrying"}:
            if current_idx < 0:
                step["status"] = "pending"
            elif idx < current_idx:
                step["status"] = "completed"
            elif idx == current_idx:
                step["status"] = "running"
            else:
                step["status"] = "pending"
        elif job_status in {"queued", "pending"}:
            step["status"] = "pending"

    orchestration["steps"] = steps
    return orchestration
