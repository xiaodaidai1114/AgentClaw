"""
追踪相关数据模型
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, computed_field


class TraceRecord(BaseModel):
    """追踪记录"""
    id: str
    workflow_id: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    name: str
    status: str  # running / success / error / timeout
    duration_ms: Optional[float] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    # Token 统计
    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    llm_calls: Optional[int] = None
    
    @computed_field
    @property
    def conversation_id(self) -> Optional[str]:
        """conversation_id 别名（对外显示用）"""
        return self.thread_id


class NodeLog(BaseModel):
    """节点执行日志"""
    id: str
    name: str
    node_type: str
    status: str  # running / success / error / timeout
    duration_ms: float = 0
    start_time: datetime
    end_time: Optional[datetime] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class LLMLog(BaseModel):
    """LLM 调用日志"""
    id: str
    model_id: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0
    status: str  # success / error
    error: Optional[str] = None
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = None  # 工具调用等元数据
    node_log_id: Optional[str] = None  # 关联的节点日志 ID


class TraceDetail(BaseModel):
    """追踪详情"""
    id: str
    workflow_id: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    name: str
    status: str
    duration_ms: Optional[float] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    node_logs: List[NodeLog] = []
    llm_logs: List[LLMLog] = []
    internal_traces: List[Dict[str, Any]] = []
    
    @computed_field
    @property
    def conversation_id(self) -> Optional[str]:
        """conversation_id 别名（对外显示用）"""
        return self.thread_id


class TraceListResponse(BaseModel):
    """追踪列表响应"""
    traces: List[TraceRecord]
    total: int
    page: int
    limit: int


class TraceTimelineEvent(BaseModel):
    """时间线事件"""
    timestamp: datetime
    event_type: str  # node_start / node_end / llm_call
    name: str
    status: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class TraceTimelineResponse(BaseModel):
    """追踪时间线响应"""
    trace_id: str
    events: List[TraceTimelineEvent]
