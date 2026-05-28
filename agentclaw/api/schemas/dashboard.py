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


class AgentSquareApp(BaseModel):
    """Agent Square 内置应用"""
    id: str
    name: str
    description: Optional[str] = None
    category: str = ""
    tags: List[str] = []
    workflow_id: str
    recommended_input: Optional[str] = None
    copyable: bool = True
    inspectable: bool = True
    registered: bool = False


class AgentSquareAppsResponse(BaseModel):
    """Agent Square 应用列表响应"""
    apps: List[AgentSquareApp]


class TemplateLibraryApp(BaseModel):
    """模板库官方模板"""
    id: str
    name: str
    description: Optional[str] = None
    category: str = ""
    tags: List[str] = []
    workflow_id: str
    recommended_input: Optional[str] = None
    copyable: bool = True
    inspectable: bool = True
    imported: bool = False
    registered: bool = False
    target_dir: Optional[str] = None
    workflow_file: Optional[str] = None


class TemplateLibraryAppsResponse(BaseModel):
    """模板库列表响应"""
    apps: List[TemplateLibraryApp]


class TemplateLibraryImportRequest(BaseModel):
    """导入模板请求"""
    overwrite: bool = False


class TemplateLibraryImportResponse(BaseModel):
    """导入模板响应"""
    success: bool = True
    imported: bool = True
    registered: bool = False
    app_id: str
    workflow_id: str
    target_dir: str
    workflow_file: str
    init_path: Optional[str] = None
    import_added: bool = False
    message: Optional[str] = None


class AvailableModel(BaseModel):
    """可用模型（用于节点模型切换）"""
    id: str
    provider: str
    model: str
    model_type: str  # chat / embedding / rerank / speech2text / tts
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
