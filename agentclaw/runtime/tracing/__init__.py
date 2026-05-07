"""
追踪模块

提供：
- BaseTracer: 追踪器抽象基类
- DatabaseTracer: 数据库追踪器
- NoopTracer: 空追踪器
- TracedWorkflow: 工作流追踪包装器
- TracedLLMManager: LLM 管理器追踪包装器
- create_traced_workflow: 创建追踪工作流的便捷函数
- auto_setup_tracing: 自动设置追踪（检测数据库可用性）
"""

from agentclaw.runtime.tracing.base import (
    BaseTracer,
    TraceData,
    SpanData,
    GenerationData,
)
from agentclaw.runtime.tracing.db_tracer import (
    DatabaseTracer,
    get_db_tracer,
    setup_db_tracing,
    auto_setup_tracing,
    disable_tracing,
    reset_tracing,
    TraceRecord,
    SpanRecord,
    GenerationRecord,
)
from agentclaw.runtime.tracing.noop_tracer import (
    NoopTracer,
    get_noop_tracer,
)
from agentclaw.runtime.tracing.wrappers import (
    TracedWorkflow,
    TracedLLMManager,
    StateProxy,
    create_traced_workflow,
    get_current_span_id,
    get_current_trace_id,
)

__all__ = [
    # 抽象基类
    "BaseTracer",
    "TraceData",
    "SpanData",
    "GenerationData",
    # 数据库追踪器
    "DatabaseTracer",
    "get_db_tracer",
    "setup_db_tracing",
    "auto_setup_tracing",
    "disable_tracing",
    "reset_tracing",
    "TraceRecord",
    "SpanRecord",
    "GenerationRecord",
    # 空追踪器
    "NoopTracer",
    "get_noop_tracer",
    # 包装器
    "TracedWorkflow",
    "TracedLLMManager",
    "StateProxy",
    "create_traced_workflow",
    "get_current_span_id",
    "get_current_trace_id",
]
