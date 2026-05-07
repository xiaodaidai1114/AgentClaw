"""
Dashboard 相关数据模型
"""

from typing import List, Optional
from pydantic import BaseModel


class DashboardStats(BaseModel):
    """仪表盘全局统计"""
    workflow_count: int = 0
    execution_count_24h: int = 0
    success_rate: float = 0.0
    avg_duration_ms: Optional[float] = None
    running_count: int = 0


class TracesSummary(BaseModel):
    """追踪统计摘要"""
    total: int = 0
    success: int = 0
    error: int = 0
    running: int = 0
    avg_duration_ms: Optional[float] = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class TrendDataPoint(BaseModel):
    """趋势数据点"""
    time: str
    success: int = 0
    error: int = 0


class DurationDataPoint(BaseModel):
    """耗时数据点"""
    time: str
    avg_ms: Optional[float] = None
    p95_ms: Optional[float] = None


class TrendData(BaseModel):
    """趋势数据"""
    time_range: str
    data_points: List[TrendDataPoint] = []
    duration_points: Optional[List[DurationDataPoint]] = None


class AvailableModel(BaseModel):
    """可用模型（用于节点模型切换）"""
    id: str
    provider: str
    model: str
    model_type: str  # chat
    supports_vision: bool = False


class AvailableModelsResponse(BaseModel):
    """可用模型列表响应"""
    models: List[AvailableModel]
    default_model_id: Optional[str] = None


class NodeModelUpdateRequest(BaseModel):
    """节点模型切换请求"""
    model_id: str


class NodeModelUpdateResponse(BaseModel):
    """节点模型切换响应"""
    success: bool
    workflow_id: str
    node_id: str
    model_id: str
    message: Optional[str] = None
