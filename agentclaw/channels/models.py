"""
渠道模块 - 数据模型

包含域模型和 API 请求/响应 schemas。
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── 域模型 ────────────────────────────────────────────

class ChannelRecord(BaseModel):
    """渠道配置记录"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: str                          # feishu | dingtalk | wecom | qq
    workflow_id: str = "__builtin__"
    user_input_field: str = "user_input"
    thread_mode: str = "per_user"      # per_user | per_chat | shared
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)  # 平台配置
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelMessageLog(BaseModel):
    """渠道消息日志"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel_id: str
    channel_name: str = ""
    user_id: str = ""
    chat_id: str = ""
    message: str = ""
    reply: str = ""
    workflow_id: str = ""
    trace_id: str = ""
    status: str = "pending"            # pending | success | error | timeout | cancelled
    duration_ms: int = 0
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Schemas ───────────────────────────────────────

class ChannelCreate(BaseModel):
    """创建渠道请求"""
    name: str = Field(..., description="渠道实例名称（唯一标识，如 feishu_sales）")
    type: str = Field(..., description="渠道类型：feishu | dingtalk | wecom | qq")
    workflow_id: str = Field("__builtin__", description="绑定的工作流 ID")
    user_input_field: str = Field("user_input", description="用户消息注入的输入字段名")
    thread_mode: str = Field("per_user", description="会话模式：per_user | per_chat | shared")
    enabled: bool = Field(True, description="是否启用")
    config: Dict[str, Any] = Field(default_factory=dict, description="平台特定配置")


class ChannelUpdate(BaseModel):
    """更新渠道请求（所有字段可选）"""
    workflow_id: Optional[str] = None
    user_input_field: Optional[str] = None
    thread_mode: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class ChannelResponse(BaseModel):
    """渠道响应（含运行状态）"""
    id: str
    name: str
    type: str
    workflow_id: str
    user_input_field: str
    thread_mode: str
    enabled: bool
    config: Dict[str, Any] = Field(default_factory=dict)
    running: bool = False
    created_at: datetime
    updated_at: datetime


class ChannelListResponse(BaseModel):
    """渠道列表响应"""
    channels: List[ChannelResponse]
    total: int


class ChannelLogResponse(BaseModel):
    """消息日志响应"""
    id: str
    channel_id: str
    channel_name: str
    user_id: str
    chat_id: str
    message: str
    reply: str
    workflow_id: str
    trace_id: str = ""
    status: str
    duration_ms: int
    error: str
    created_at: datetime


class ChannelLogListResponse(BaseModel):
    """消息日志列表响应"""
    logs: List[ChannelLogResponse]
    total: int
    page: int
    limit: int


class ChannelLogStats(BaseModel):
    """消息日志统计"""
    total: int = 0
    success: int = 0
    error: int = 0
    timeout: int = 0
    avg_duration_ms: float = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
