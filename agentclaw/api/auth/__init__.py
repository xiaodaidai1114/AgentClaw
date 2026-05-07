"""
统一认证模块

提供：
- AdminTokenManager: Admin API Token 管理
- WorkflowAPIKeyManager: 工作流 API Key 管理
- APIKeyManager: 工作流 API Key 管理（旧版）
- AuthMiddleware: 统一认证中间件
- verify_admin_token: Token 验证函数
"""

from agentclaw.api.auth.middleware import AuthMiddleware, verify_admin_token, add_auth_middleware
from agentclaw.api.auth.token import AdminTokenManager, WorkflowAPIKeyManager
from agentclaw.api.auth.api_key import APIKeyManager, APIKey, AuthConfig, AuthResult

__all__ = [
    "AuthMiddleware",
    "add_auth_middleware",
    "verify_admin_token",
    "AdminTokenManager",
    "WorkflowAPIKeyManager",
    "APIKeyManager",
    "APIKey",
    "AuthConfig",
    "AuthResult",
]
