"""
AgentClaw - 轻量级 AI Agent 框架

基于 LangGraph 构建，提供：
- 工作流定义和执行
- LLM 多模型管理
- 状态持久化
- 流式输出
"""

from agentclaw.warning_filters import install_warning_filters

install_warning_filters()

from agentclaw.version import __version__, get_version

from .platform_compat import apply_windows_selector_event_loop_policy

apply_windows_selector_event_loop_policy()

# 核心模块
from agentclaw.graph.workflow import Workflow
from agentclaw.graph.context import WorkflowContext, CancelToken
from agentclaw.graph.template import WorkflowTemplate

# 节点
from agentclaw.node.types import ErrorStrategy
from agentclaw.node.base import BaseNode, FunctionNode
from agentclaw.node.custom import CustomNode, SyncNode, node
from agentclaw.node.llm import LLMNode
from agentclaw.node.human import HumanInput, HumanNode
from agentclaw.node.sub_workflow import SubWorkflowNode
from agentclaw.node.state_extract import StateExtractNode
from agentclaw.node.mcp import MCPNode, MCPPipelineNode
from agentclaw.node.document import DocumentNode, DocumentExtractNode
from agentclaw.node.knowledgebase import KnowledgeBaseNode

# 输入参数定义
from agentclaw.inputs import Input, InputSchema, Image, File, Files, Audio

# 组件
from agentclaw.model.manager import LLMManager, LLMConfig
from agentclaw.prompt.manager import PromptManager
from agentclaw.node.toolkit import ToolKit, Tool, tool
from agentclaw.mcp import MCPToolKit, MCPManager, MCPConfig, publish_mcp_tool, publish_mcp_toolkit
from agentclaw.database.manager import DatabaseManager, init_database, get_database

# 状态管理
from agentclaw.state.checkpointer import (
    setup_checkpointer,
    get_checkpointer,
    close_checkpointer,
)
from agentclaw.state.memory import (
    create_user_message,
    create_ai_message,
    format_messages_for_llm,
    get_last_user_message,
)

# 异常
from agentclaw.exceptions import (
    AgentClawError,
    WorkflowCancelledError,
    WorkflowTimeoutError,
    NodeExecutionError,
    ConfigError,
)

# API
from agentclaw.api.registry import WorkflowRegistry
from agentclaw.api.server import AgentClawServer, create_app
from agentclaw.api.auth import APIKeyManager, AuthConfig

# Runtime
from agentclaw.runtime.streaming import output, OutputChannel, sse_format
from agentclaw.runtime.tracing import (
    DatabaseTracer, 
    get_db_tracer, 
    setup_db_tracing,
    TracedWorkflow,
    TracedLLMManager,
    create_traced_workflow,
)

# Utils
from agentclaw.utils import fake_stream

__all__ = [
    # Version
    "__version__",
    # Workflow
    "Workflow",
    "WorkflowTemplate",
    "BaseNode",
    "CustomNode",
    "SyncNode",
    "node",  # 函数式节点装饰器
    "LLMNode",
    "HumanInput",
    "HumanNode",
    "SubWorkflowNode",
    "StateExtractNode",
    "FunctionNode",
    "MCPNode",
    "MCPPipelineNode",
    "DocumentNode",
    "DocumentExtractNode",
    "KnowledgeBaseNode",
    "ErrorStrategy",
    "WorkflowContext",
    "CancelToken",
    # Inputs
    "Input",
    "InputSchema",
    "Image",
    "File",
    "Files",
    "Audio",
    # Components
    "LLMManager",
    "LLMConfig",
    "PromptManager",
    "ToolKit",
    "Tool",
    "tool",
    "MCPToolKit",
    "MCPManager",
    "MCPConfig",
    "publish_mcp_tool",
    "publish_mcp_toolkit",
    "DatabaseManager",
    "init_database",
    "get_database",
    # State
    "setup_checkpointer",
    "get_checkpointer",
    "close_checkpointer",
    "create_user_message",
    "create_ai_message",
    "format_messages_for_llm",
    "get_last_user_message",
    # Exceptions
    "AgentClawError",
    "WorkflowCancelledError",
    "WorkflowTimeoutError",
    "NodeExecutionError",
    "ConfigError",
    # API
    "WorkflowRegistry",
    "AgentClawServer",
    "create_app",
    "APIKeyManager",
    "AuthConfig",
    # Runtime
    "output",
    "OutputChannel",
    "sse_format",
    # Tracing
    "DatabaseTracer",
    "get_db_tracer",
    "setup_db_tracing",
    "TracedWorkflow",
    "TracedLLMManager",
    "create_traced_workflow",
    # Utils
    "fake_stream",
]
