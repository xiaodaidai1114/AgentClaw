"""
通用响应数据模型
"""

from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """成功响应"""
    data: T


class ErrorResponse(BaseModel):
    """
    统一错误响应格式
    
    所有 API 错误都应使用此格式：
    {
        "error": "错误描述",
        "code": "ERROR_CODE",
        "detail": "详细信息（可选）"
    }
    """
    error: str                          # 错误描述
    code: str = "UNKNOWN_ERROR"         # 错误编码
    detail: Optional[str] = None        # 详细信息


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    data: List[T]
    total: int
    page: int
    limit: int


# 错误编码常量
class ErrorCode:
    """错误编码常量"""
    # 通用错误
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_JSON = "INVALID_JSON"
    
    # 认证错误
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_TOKEN = "INVALID_TOKEN"
    
    # 资源错误
    NOT_FOUND = "NOT_FOUND"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    PROMPT_NOT_FOUND = "PROMPT_NOT_FOUND"
    TRACE_NOT_FOUND = "TRACE_NOT_FOUND"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    
    # 业务错误
    VALIDATION_ERROR = "VALIDATION_ERROR"
    OPERATION_FAILED = "OPERATION_FAILED"
    PROMPT_MANAGER_NOT_CONFIGURED = "PROMPT_MANAGER_NOT_CONFIGURED"
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# 自定义 API 异常
class APIError(Exception):
    """
    统一 API 异常
    
    用于在 API 路由中抛出带有错误编码的异常，
    会被全局异常处理器捕获并转换为统一错误响应格式。
    
    Example:
        raise APIError(
            error="工作流不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    """
    def __init__(
        self,
        error: str,
        code: str = ErrorCode.UNKNOWN_ERROR,
        status_code: int = 400,
        detail: str = None,
    ):
        self.error = error
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(error)


def error_response(
    error: str,
    code: str = ErrorCode.UNKNOWN_ERROR,
    detail: Optional[str] = None,
    status_code: int = 400,
) -> dict:
    """
    创建统一错误响应
    
    Args:
        error: 错误描述
        code: 错误编码
        detail: 详细信息
        status_code: HTTP 状态码
    
    Returns:
        (status_code, content) 元组，用于 JSONResponse
    """
    return {
        "status_code": status_code,
        "content": {
            "error": error,
            "code": code,
            "detail": detail,
        }
    }
