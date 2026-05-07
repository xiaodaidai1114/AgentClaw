"""
提示词相关数据模型
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel


class PromptInfo(BaseModel):
    """提示词信息"""
    workflow_id: str
    prompt_key: str
    content: str
    default_content: Optional[str] = None
    is_custom: bool = False
    version: int = 1
    created_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    # 变量占位符列表
    variables: Optional[List[str]] = None


class PromptHistory(BaseModel):
    """提示词历史版本"""
    version: int
    content: str
    created_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class PromptListResponse(BaseModel):
    """提示词列表响应"""
    prompts: List[PromptInfo]


class PromptUpdateRequest(BaseModel):
    """提示词更新请求"""
    content: str


class PromptPreviewRequest(BaseModel):
    """提示词预览请求"""
    content: str
    variables: Dict[str, Any] = {}


class PromptPreviewResponse(BaseModel):
    """提示词预览响应"""
    rendered: str


class PromptHistoryResponse(BaseModel):
    """提示词历史响应"""
    history: List[PromptHistory]


class PromptRollbackRequest(BaseModel):
    """提示词回滚请求"""
    version: int
