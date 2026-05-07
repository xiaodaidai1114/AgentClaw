from __future__ import annotations
from typing import Optional

class AgentClawError(Exception):
    """AgentClaw 基础异常"""
    pass

class WorkflowCancelledError(AgentClawError):
    """工作流被取消异常"""
    pass

class WorkflowTimeoutError(AgentClawError):
    """工作流超时异常"""
    pass

class NodeExecutionError(AgentClawError):
    """节点执行异常"""
    
    def __init__(self, node_id: str, message: str, original_error: Optional[Exception] = None):
        self.node_id = node_id
        self.original_error = original_error
        super().__init__(f"节点 '{node_id}' 执行失败: {message}")

class ConfigError(AgentClawError):
    """配置错误异常"""
    pass
