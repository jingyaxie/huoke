"""可扩展任务编排底座：Template → Instance → Executor → Capability。"""

from app.task_platform.adapters.yingxiaoyi_lead_v1 import register_yingxiaoyi_adapter
from app.task_platform.registry.executor_registry import TaskExecutorRegistry

__all__ = ["bootstrap_task_platform"]


def bootstrap_task_platform() -> None:
    """注册内置 TaskExecutor 与规则 Adapter；应用启动时调用一次。"""
    from app.task_platform.executors.lead_acquisition import LeadAcquisitionExecutor
    from app.task_platform.executors.pipeline_only import PipelineOnlyExecutor

    TaskExecutorRegistry.register(PipelineOnlyExecutor())
    TaskExecutorRegistry.register(LeadAcquisitionExecutor())
    register_yingxiaoyi_adapter()
