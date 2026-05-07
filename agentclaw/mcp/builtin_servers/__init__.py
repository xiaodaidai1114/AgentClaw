"""Built-in MCP servers package."""

# 延迟导入以避免循环依赖和命名冲突
# 当作为子进程运行时（python -m agentclaw.mcp.builtin_servers），
# 不需要导入所有 server 类，只需要 registry

from .registry import BUILTIN_SERVERS, get_builtin_server_config, is_builtin_server, main

# 只在需要时才导入具体的 server 类
def _get_server_class(name: str):
    """延迟导入 server 类"""
    if name == "CodingToolsServer":
        from .coding_tools import CodingToolsServer
        return CodingToolsServer
    elif name == "ComputerToolsServer":
        from .computer_tools import ComputerToolsServer
        return ComputerToolsServer
    elif name == "DownloadToolsServer":
        from .download_tools import DownloadToolsServer
        return DownloadToolsServer
    elif name == "PlanningToolsServer":
        from .planning_tools import PlanningToolsServer
        return PlanningToolsServer
    elif name == "SearchToolsServer":
        from .search_tools import SearchToolsServer
        return SearchToolsServer
    elif name == "SkillToolsServer":
        from .skill_tools import SkillToolsServer
        return SkillToolsServer
    else:
        raise ValueError(f"Unknown server class: {name}")

__all__ = [
    "BUILTIN_SERVERS",
    "get_builtin_server_config",
    "is_builtin_server",
    "main",
    "_get_server_class",
]
