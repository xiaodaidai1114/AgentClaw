"""
AgentClaw API 模块

提供：
- AgentClawServer: HTTP 服务器
- AuthConfig: 认证配置
- APIKey: API Key 管理
- WorkflowRegistry: 工作流注册表
"""

from agentclaw.api.auth import (
    AuthConfig,
    APIKey,
    APIKeyManager,
)
from agentclaw.api.registry import WorkflowRegistry

__all__ = [
    # 认证
    "AuthConfig",
    "APIKey", 
    "APIKeyManager",
    # 注册表
    "WorkflowRegistry",
]

# 延迟导入 server（避免循环依赖）
def __getattr__(name):
    if name == "AgentClawServer":
        from agentclaw.api.server import AgentClawServer
        return AgentClawServer
    if name == "create_app":
        from agentclaw.api.server import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
