"""
企业工具接入框架 - 把异构工具（Python/HTTP/CLI）统一成 MCP 工具

设计：
- ToolSpec：统一规范（YAML 定义），含 handler 适配（python/http/cli）
- ToolExecutor：按 handler 类型执行
- load_specs：从 tools/specs/*.yaml 批量加载
- build_server：构建 stdio MCP server（mcp.json 配置，所有 agent 全局可用）

接入流程：
1. 在 tools/specs/ 下为每个工具写一份 YAML（统一规范）
2. mcp.json 加 enterprise-tools server（python -m agentclaw.tools.server）
3. 所有 agent 自动通过 MCPManager 使用（enable_builtin_tools 或 MCPNode）

加新工具只加 YAML，不改代码。
"""

from .executor import ToolExecutor
from .loader import load_spec, load_specs
from .server import build_server
from .spec import (
    ALL_PERMISSIONS,
    HandlerSpec,
    PERMISSION_READ_ONLY,
    PERMISSION_WRITE_AUTO,
    PERMISSION_WRITE_WITH_APPROVAL,
    ToolSpec,
)

__all__ = [
    "ToolSpec",
    "HandlerSpec",
    "ToolExecutor",
    "load_specs",
    "load_spec",
    "build_server",
    "PERMISSION_READ_ONLY",
    "PERMISSION_WRITE_WITH_APPROVAL",
    "PERMISSION_WRITE_AUTO",
    "ALL_PERMISSIONS",
]
