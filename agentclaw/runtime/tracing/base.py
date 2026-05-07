"""
BaseTracer - 追踪器抽象基类

定义追踪器接口，支持：
- Trace: 工作流级别追踪
- Span: 节点级别追踪
- Generation: LLM 调用追踪
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class TraceData:
    """Trace 数据"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = ""
    thread_id: str = ""
    user_id: Optional[str] = None
    name: str = ""
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "running"
    error: Optional[str] = None


@dataclass
class SpanData:
    """Span 数据"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    parent_span_id: Optional[str] = None
    name: str = ""
    node_type: str = ""
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_ms: float = 0
    status: str = "running"
    error: Optional[str] = None


@dataclass
class GenerationData:
    """Generation 数据（LLM 调用）"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    span_id: str = ""
    model_id: str = ""
    model_name: str = ""
    prompt: str = ""
    completion: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "success"
    error: Optional[str] = None


class BaseTracer(ABC):
    """
    追踪器抽象基类
    
    子类需要实现：
    - trace(): 创建 Trace 上下文
    - span(): 创建 Span 上下文
    - log_generation(): 记录 LLM 调用
    """
    
    @property
    @abstractmethod
    def enabled(self) -> bool:
        """是否启用追踪"""
        pass
    
    @abstractmethod
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
        """
        创建 Trace 上下文
        
        Example:
            async with tracer.trace("my_workflow", thread_id="xxx") as trace:
                # 执行工作流
                pass
        """
        yield
    
    @abstractmethod
    @asynccontextmanager
    async def span(
        self,
        name: str,
        node_type: str = "function",
        input_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        """
        创建 Span 上下文
        
        Example:
            async with tracer.span("node_1", node_type="llm") as span:
                # 执行节点
                pass
        """
        yield
    
    @abstractmethod
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
        """记录 LLM 调用"""
        pass
    
    async def update_generation_metadata(self, generation_id: str, metadata_update: dict) -> None:
        """更新 Generation 的 metadata（合并）"""
        pass

    def set_trace_output(self, output_data: dict) -> None:
        """设置当前 Trace 的输出数据"""
        pass
    
    def set_span_output(self, output_data: dict) -> None:
        """设置当前 Span 的输出数据"""
        pass
