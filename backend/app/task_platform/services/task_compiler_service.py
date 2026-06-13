from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings
from app.services.ai_client import AIClientFactory
from app.services.agent_llm import resolve_default_provider
from app.task_platform.registry.adapter_registry import TaskAdapterRegistry
from app.task_platform.registry.executor_registry import TaskExecutorRegistry
from app.task_platform.schemas.compile import TaskCompilePlan, TaskCompileRequest, TaskCompileResponse
from app.task_platform.schemas.instance import TaskCreateRequest
from app.task_platform.services.task_schedule_utils import parse_scheduled_at
from app.task_platform.stores.task_template_store import TaskTemplateStore, get_task_template_store


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


class TaskCompilerService:
    """外部原始 JSON → TaskCompilePlan；规则优先，LLM 兜底。"""

    def __init__(
        self,
        settings: Settings,
        template_store: TaskTemplateStore | None = None,
        *,
        tenant_id: str,
    ) -> None:
        self.settings = settings
        self.template_store = template_store or get_task_template_store()
        self.tenant_id = tenant_id

    async def compile(self, request: TaskCompileRequest) -> TaskCompileResponse:
        plan = await self._compile_plan(request)
        plan = await self._finalize_plan(plan)
        create_req = self._to_create_request(request, plan) if plan.validation_ok else None
        return TaskCompileResponse(ok=plan.validation_ok, plan=plan, create_request=create_req)

    async def _compile_plan(self, request: TaskCompileRequest) -> TaskCompilePlan:
        rule_plan: TaskCompilePlan | None = None
        if request.adapter_id and not request.force_llm:
            rule_plan = await self._compile_with_rule(request)
            if rule_plan and rule_plan.confidence >= 0.85 and rule_plan.validation_ok:
                return rule_plan

        llm_plan = await self._compile_with_llm(request, prior=rule_plan)
        if llm_plan is not None:
            if rule_plan and rule_plan.validation_ok and not llm_plan.validation_ok:
                merged = rule_plan.model_copy(
                    update={
                        "method": "hybrid",
                        "reasoning": f"{rule_plan.reasoning}；LLM 校验失败，回退规则结果",
                    }
                )
                return merged
            if rule_plan and llm_plan.validation_ok:
                llm_plan.method = "hybrid"
                llm_plan.reasoning = f"{rule_plan.reasoning}；{llm_plan.reasoning}"
            return llm_plan

        if rule_plan is not None:
            return rule_plan

        return TaskCompilePlan(
            template_id="lead-crawl",
            template_version="1.0.0",
            spec={},
            confidence=0.0,
            unmapped_fields=list(request.raw_payload.keys()),
            reasoning="无法编译：无匹配 adapter 且 LLM 不可用",
            method="rule",
            validation_ok=False,
            validation_error="缺少 keyword 或无法识别字段",
        )

    async def _compile_with_rule(self, request: TaskCompileRequest) -> TaskCompilePlan | None:
        adapter = TaskAdapterRegistry.get(request.adapter_id or "")
        if adapter is None:
            return None
        result = adapter.compile_payload(request.raw_payload, intent=request.intent)
        template_id = str(result.get("template_id") or adapter.template_id)
        template = self.template_store.get(template_id, tenant_id=self.tenant_id)
        if template is None:
            return TaskCompilePlan(
                template_id=template_id,
                template_version="1.0.0",
                spec={},
                confidence=0.0,
                reasoning=f"模板不存在: {template_id}",
                method="rule",
                validation_ok=False,
                validation_error=f"模板不存在: {template_id}",
            )

        spec = self.template_store.merge_spec(template, dict(result.get("spec") or {}))
        if request.account_id:
            spec["account_id"] = request.account_id
        if request.hints.get("account_id"):
            spec["account_id"] = str(request.hints["account_id"])

        validation_ok, validation_error, spec = await self.validate_spec_async(
            template_id, spec, version=template.version
        )
        return TaskCompilePlan(
            template_id=template_id,
            template_version=template.version,
            spec=spec,
            confidence=float(result.get("confidence") or 0.0),
            unmapped_fields=list(result.get("unmapped_fields") or []),
            reasoning=str(result.get("reasoning") or ""),
            method="rule",
            validation_ok=validation_ok,
            validation_error=validation_error,
        )

    async def _compile_with_llm(
        self,
        request: TaskCompileRequest,
        *,
        prior: TaskCompilePlan | None,
    ) -> TaskCompilePlan | None:
        provider = request.provider or resolve_default_provider(self.settings)
        factory = AIClientFactory(self.settings)
        client = factory.deepseek() if provider == "deepseek" else factory.openai()
        if client is None:
            client = factory.openai() or factory.deepseek()
        if client is None:
            return None

        templates = self.template_store.list_templates(tenant_id=self.tenant_id)
        catalog = [
            {
                "template_id": t.template_id,
                "version": t.version,
                "name": t.name,
                "description": t.description,
                "platforms": t.platforms,
                "default_spec": t.default_spec,
            }
            for t in templates
        ]
        model = (
            self.settings.deepseek_model
            if provider == "deepseek"
            else self.settings.openai_model
        )

        prior_text = ""
        if prior is not None:
            prior_text = json.dumps(
                {
                    "template_id": prior.template_id,
                    "spec": prior.spec,
                    "unmapped_fields": prior.unmapped_fields,
                },
                ensure_ascii=False,
            )

        system = (
            "你是任务编译器。将外部系统的原始 JSON 映射为 Huoke 内部结构化任务。"
            "只输出一个 JSON 对象，不要 markdown。字段："
            "template_id, template_version, spec, confidence(0-1), unmapped_fields(array), reasoning(string)."
            "spec 必须满足所选 template 的 default_spec 结构；keyword 必填。"
            "platform 仅允许 douyin 或 xiaohongshu。"
        )
        user = json.dumps(
            {
                "intent": request.intent,
                "adapter_id": request.adapter_id,
                "raw_payload": request.raw_payload,
                "hints": request.hints,
                "template_catalog": catalog,
                "rule_draft": prior_text or None,
            },
            ensure_ascii=False,
        )

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
            )
            content = resp.choices[0].message.content or ""
        except Exception as exc:
            return TaskCompilePlan(
                template_id=prior.template_id if prior else "lead-crawl",
                template_version=prior.template_version if prior else "1.0.0",
                spec=prior.spec if prior else {},
                confidence=0.0,
                reasoning=f"LLM 编译失败: {exc}",
                method="llm",
                validation_ok=False,
                validation_error=str(exc),
            )

        parsed = _extract_json_object(content)
        if parsed is None:
            return None

        template_id = str(parsed.get("template_id") or "lead-crawl")
        template = self.template_store.get(template_id, tenant_id=self.tenant_id)
        if template is None:
            return TaskCompilePlan(
                template_id=template_id,
                template_version=str(parsed.get("template_version") or "1.0.0"),
                spec={},
                confidence=float(parsed.get("confidence") or 0.0),
                unmapped_fields=list(parsed.get("unmapped_fields") or []),
                reasoning=str(parsed.get("reasoning") or content[:200]),
                method="llm",
                validation_ok=False,
                validation_error=f"模板不存在: {template_id}",
            )

        spec = self.template_store.merge_spec(template, dict(parsed.get("spec") or {}))
        if request.account_id:
            spec["account_id"] = request.account_id

        validation_ok, validation_error, spec = await self.validate_spec_async(
            template_id, spec, version=template.version
        )
        return TaskCompilePlan(
            template_id=template_id,
            template_version=template.version,
            spec=spec,
            confidence=float(parsed.get("confidence") or 0.5),
            unmapped_fields=[str(x) for x in (parsed.get("unmapped_fields") or [])],
            reasoning=str(parsed.get("reasoning") or "LLM 编译"),
            method="llm",
            validation_ok=validation_ok,
            validation_error=validation_error,
        )

    async def _finalize_plan(self, plan: TaskCompilePlan) -> TaskCompilePlan:
        """执行器未就绪时降级为 lead-crawl，保证 compile-and-create 可用。"""
        if not plan.validation_ok:
            return plan
        template = self.template_store.get(plan.template_id, tenant_id=self.tenant_id, version=plan.template_version)
        if template is None:
            return plan
        executor = TaskExecutorRegistry.get(template.executor_id)
        if executor is not None:
            return plan
        if plan.template_id != "lead-acquisition":
            return plan.model_copy(
                update={
                    "validation_ok": False,
                    "validation_error": f"执行器未注册: {template.executor_id}",
                }
            )
        crawl_template = self.template_store.get("lead-crawl", tenant_id=self.tenant_id)
        if crawl_template is None:
            return plan.model_copy(
                update={
                    "validation_ok": False,
                    "validation_error": "lead-acquisition 执行器未就绪且 lead-crawl 模板缺失",
                }
            )
        crawl_spec = self.template_store.merge_spec(crawl_template, plan.spec)
        ok, err, normalized = await self.validate_spec_async(
            "lead-crawl", crawl_spec, version=crawl_template.version
        )
        return plan.model_copy(
            update={
                "template_id": "lead-crawl",
                "template_version": crawl_template.version,
                "spec": normalized,
                "validation_ok": ok,
                "validation_error": err,
                "reasoning": (
                    f"{plan.reasoning}；lead-acquisition 执行器未就绪，已降级为 lead-crawl（仅抓取）"
                ),
            }
        )

    async def validate_spec_async(
        self,
        template_id: str,
        spec: dict[str, Any],
        *,
        version: str | None = None,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        template = self.template_store.get(template_id, tenant_id=self.tenant_id, version=version)
        if template is None:
            return False, f"模板不存在: {template_id}", spec
        executor = TaskExecutorRegistry.get(template.executor_id)
        if executor is None:
            return False, f"执行器未注册: {template.executor_id}", spec
        result = await executor.validate_spec(spec, template)
        if result.ok:
            return True, None, result.spec or spec
        return False, result.error or "spec 校验失败", spec

    def _to_create_request(self, request: TaskCompileRequest, plan: TaskCompilePlan) -> TaskCreateRequest:
        external_ref = request.raw_payload.get("external_ref") or request.raw_payload.get("task_id")
        if external_ref is not None:
            external_ref = str(external_ref)
        webhook_url = request.raw_payload.get("webhook_url") or request.hints.get("webhook_url")
        if webhook_url is not None:
            webhook_url = str(webhook_url)
        name = plan.spec.get("task_name") or request.raw_payload.get("task_name")
        scheduled_at = parse_scheduled_at(
            request.raw_payload.get("scheduled_at")
            or request.raw_payload.get("run_at")
            or request.raw_payload.get("execute_at")
            or request.hints.get("scheduled_at")
        )
        return TaskCreateRequest(
            template_id=plan.template_id,
            template_version=plan.template_version,
            spec=plan.spec,
            name=str(name).strip() if name else None,
            external_ref=external_ref,
            adapter_id=request.adapter_id,
            source=request.source,
            webhook_url=webhook_url,
            scheduled_at=scheduled_at,
        )
