"""
工作流相关数据模型
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class NodeSchema(BaseModel):
    """节点输入/输出 Schema"""
    fields: Optional[List[str]] = None
    description: Optional[str] = None


class WorkflowNode(BaseModel):
    """工作流节点"""
    id: str
    name: str
    type: str  # llm / function / human / parallel
    model_id: Optional[str] = None
    has_prompt: bool = False
    interrupt: Optional[bool] = None
    is_group: Optional[bool] = None  # 是否是组节点（如 ParallelGroup）
    # 输入/输出 schema
    input_schema: Optional[NodeSchema] = None
    output_schema: Optional[NodeSchema] = None
    output_key: Optional[str] = None
    # HumanNode 特有字段
    feedback_field: Optional[str] = None
    input_hint: Optional[str] = None
    # ParallelGroup 子节点
    children: Optional[List[Dict[str, Any]]] = None


class WorkflowEdge(BaseModel):
    """工作流边"""
    source: str
    target: str
    type: str  # normal / conditional
    condition: Optional[str] = None


class WorkflowListStats(BaseModel):
    """工作流列表卡片统计"""
    execution_count: int = 0
    success_rate: Optional[float] = None
    avg_duration_ms: Optional[float] = None
    total_tokens: int = 0
    running_count: int = 0
    last_execution_time: Optional[Any] = None


class WorkflowInfo(BaseModel):
    """工作流基本信息"""
    id: str
    name: str
    version: str
    description: Optional[str] = None
    node_count: int = 0
    is_builtin: bool = False
    public_share_enabled: bool = False
    public_share_token: Optional[str] = None
    rate_limit: Optional[str] = None
    public_conversation_limit: int = 20
    public_message_limit: int = 200
    inject_as_agentic_capability: bool = True
    workflow_api_key_set: bool = False
    like_count: int = 0
    dislike_count: int = 0
    # 统计摘要（默认最近24小时；仪表盘可按 time_range 返回 7d/30d）
    stats_24h: Optional[WorkflowListStats] = None


class WorkflowStructure(BaseModel):
    """工作流结构（用于可视化）"""
    id: str
    name: str
    version: str
    description: Optional[str] = None
    like_count: int = 0
    dislike_count: int = 0
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    node_order: List[str]
    input_schema: Optional[Dict[str, Any]] = None  # 工作流输入 schema
    inputs_config: Optional[Dict[str, Any]] = None  # 输入参数配置
    form_config: Optional[List[Dict[str, Any]]] = None  # 前端表单配置
    user_input_field: Optional[str] = None  # 用户输入字段名
    welcome: Optional[str] = None  # 前端开场白
    is_builtin: bool = False  # 是否为内置智能体
    public_share_enabled: bool = False
    public_share_token: Optional[str] = None
    rate_limit: Optional[str] = None
    public_conversation_limit: int = 20
    public_message_limit: int = 200
    inject_as_agentic_capability: bool = True
    workflow_api_key_set: bool = False


class WorkflowStats(BaseModel):
    """工作流统计数据"""
    total_count: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    success_rate: float = 0.0
    avg_duration_ms: Optional[float] = None
    p95_duration_ms: Optional[float] = None
    p99_duration_ms: Optional[float] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class WorkflowListResponse(BaseModel):
    """工作流列表响应"""
    workflows: List[WorkflowInfo]


class WorkflowDetailResponse(BaseModel):
    """工作流详情响应"""
    workflow: WorkflowStructure
    stats: Optional[WorkflowStats] = None
