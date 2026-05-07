"""
NoopTracer - 空追踪器实现

不执行任何追踪操作，用于：
- 未配置数据库时的默认追踪器
- 测试环境
- 禁用追踪时
"""

from __future__ import annotations
from typing import Optional
from contextlib import asynccontextmanager

from agentclaw.runtime.tracing.base import BaseTracer, GenerationData


class NoopTracer(BaseTracer):
    """
    空追踪器
    
    所有操作都是空操作，不记录任何数据
    """
    
    @property
    def enabled(self) -> bool:
        return False
    
    @asynccontextmanager
    async def trace(
        self,
        name: str,
        workflow_id: str = "",
        thread_id: str = "",
        user_id: Optional[str] = None,
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        yield None
    
    @asynccontextmanager
    async def span(
        self,
        name: str,
        node_type: str = "function",
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        yield None
    
    async def log_generation(
        self,
        model_id: str,
        model_name: str,
        prompt: str,
        completion: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0,
        metadata: Optional[dict] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> Optional[GenerationData]:
        return None


# 全局单例
_noop_tracer = NoopTracer()


def get_noop_tracer() -> NoopTracer:
    """获取空追踪器单例"""
    return _noop_tracer
