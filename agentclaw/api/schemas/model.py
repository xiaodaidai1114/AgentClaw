"""
模型相关数据模型
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class ModelInfo(BaseModel):
    """模型信息"""
    id: str
    provider: str
    model: str
    model_type: str  # chat / embedding / rerank
    supports_vision: bool = False
    temperature: float = 0.1
    max_tokens: int = 8192
    timeout: int = 240
    # 运行时状态
    status: str  # primary / fallback / standby / disabled
    is_current: bool = False


class ModelStats(BaseModel):
    """模型使用统计"""
    total_calls: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_tokens: int = 0
    estimated_cost: float = 0.0


class FallbackState(BaseModel):
    """降级状态"""
    is_fallback: bool = False
    fallback_reason: Optional[str] = None
    fallback_until: Optional[datetime] = None
    failure_count: int = 0
    current_model_id: Optional[str] = None
    default_model_id: Optional[str] = None
    fallback_model_id: Optional[str] = None


class ModelListResponse(BaseModel):
    """模型列表响应"""
    models: List[ModelInfo]
    fallback_state: FallbackState


class ModelUpdateRequest(BaseModel):
    """模型配置更新请求"""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None


class ModelFallbackRequest(BaseModel):
    """手动降级请求"""
    reason: Optional[str] = "手动触发"
