"""
AgentClaw Runtime 模块

提供：
- 流式输出 (streaming)
- SSE 格式化
- 追踪 (tracing)
"""

from agentclaw.runtime.sse import sse_format

# 延迟导入避免循环依赖
def __getattr__(name):
    if name in ("OutputChannel", "OutputEvent", "output", "get_output_channel"):
        from agentclaw.runtime.streaming import context
        return getattr(context, name)
    if name in ("DatabaseTracer", "get_db_tracer", "setup_db_tracing"):
        from agentclaw.runtime.tracing import db_tracer
        return getattr(db_tracer, name)
    if name == "streaming":
        from agentclaw.runtime import streaming
        return streaming
    if name == "tracing":
        from agentclaw.runtime import tracing
        return tracing
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "sse_format",
    # Streaming
    "OutputChannel",
    "OutputEvent", 
    "output",
    "get_output_channel",
    # Tracing
    "DatabaseTracer",
    "get_db_tracer",
    "setup_db_tracing",
]
