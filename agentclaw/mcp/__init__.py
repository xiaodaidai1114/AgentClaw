"""
MCP (Model Context Protocol) 集成模块

提供：
- MCPClient: 单个 MCP Server 连接管理
- MCPManager: 多 Server 管理
- MCPToolKit: 工作流集成
"""

import atexit
import asyncio
import weakref
import sys
import warnings
import logging

from agentclaw.mcp.client import MCPClient
from agentclaw.mcp.manager import MCPManager
from agentclaw.mcp.toolkit import MCPToolKit
from agentclaw.mcp.config import MCPConfig, MCPServerConfig
from agentclaw.mcp.token_manager import (
    MCPTokenManager,
    MCPServerRegistry,
    MCPPublishedTool,
    publish_mcp_tool,
    publish_mcp_toolkit,
)

# 延迟导入 builtin_servers 以避免循环导入
def get_builtin_server_config(server_name: str):
    """获取内置 server 配置（延迟导入）"""
    from agentclaw.mcp.builtin_servers import get_builtin_server_config as _get_config
    return _get_config(server_name)

def is_builtin_server(server_name: str) -> bool:
    """检查是否为内置 server（延迟导入）"""
    from agentclaw.mcp.builtin_servers import is_builtin_server as _is_builtin
    return _is_builtin(server_name)

# BUILTIN_SERVERS 使用属性访问时才导入
class _BuiltinServersProxy:
    """延迟加载 BUILTIN_SERVERS 的代理"""
    _cache = None

    def __getattr__(self, name):
        if self._cache is None:
            from agentclaw.mcp.builtin_servers import BUILTIN_SERVERS
            self._cache = BUILTIN_SERVERS
        return getattr(self._cache, name)

    def __getitem__(self, key):
        if self._cache is None:
            from agentclaw.mcp.builtin_servers import BUILTIN_SERVERS
            self._cache = BUILTIN_SERVERS
        return self._cache[key]

    def __iter__(self):
        if self._cache is None:
            from agentclaw.mcp.builtin_servers import BUILTIN_SERVERS
            self._cache = BUILTIN_SERVERS
        return iter(self._cache)

    def __len__(self):
        if self._cache is None:
            from agentclaw.mcp.builtin_servers import BUILTIN_SERVERS
            self._cache = BUILTIN_SERVERS
        return len(self._cache)

BUILTIN_SERVERS = _BuiltinServersProxy()

# 全局注册表：跟踪所有 MCPManager 实例
_active_managers: weakref.WeakSet = weakref.WeakSet()

# 标记是否正在清理
_cleaning_up = False


def _register_manager(manager: MCPManager) -> None:
    """注册 MCPManager 实例"""
    _active_managers.add(manager)


def _cleanup_all_mcp_connections() -> None:
    """程序退出时清理所有 MCP 连接"""
    global _cleaning_up
    _cleaning_up = True
    
    # 抑制 stderr 输出
    import io
    import os
    
    # 保存原始 stderr
    old_stderr = sys.stderr
    devnull = open(os.devnull, 'w')
    
    try:
        # 重定向 stderr 到 /dev/null
        sys.stderr = devnull
        
        for manager in list(_active_managers):
            try:
                # 尝试在当前事件循环中断开
                try:
                    loop = asyncio.get_running_loop()
                    # 如果循环正在运行，创建任务但不等待
                    asyncio.ensure_future(manager.disconnect_all())
                except RuntimeError:
                    # 没有运行中的循环，尝试获取或创建
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_closed():
                            loop.run_until_complete(manager.disconnect_all())
                    except Exception:
                        pass
            except Exception:
                pass
    finally:
        sys.stderr = old_stderr
        devnull.close()
        _cleaning_up = False


# 注册退出清理函数
atexit.register(_cleanup_all_mcp_connections)

# 抑制异步生成器关闭时的错误输出
_original_excepthook = sys.excepthook

# MCP 相关错误关键词
_MCP_ERROR_KEYWORDS = [
    "cancel scope",
    "asynchronous generator",
    "generator didn't stop",
    "aclose()",
    "athrow()",
    "GeneratorExit",
    "TaskGroup",
    "ExceptionGroup",
]


def _is_mcp_cleanup_error(exc_value) -> bool:
    """检查是否是 MCP 清理时的错误"""
    if exc_value is None:
        return False
    msg = str(exc_value)
    return any(s in msg for s in _MCP_ERROR_KEYWORDS)


def _mcp_excepthook(exc_type, exc_value, exc_tb):
    """自定义异常钩子，抑制 MCP 关闭时的错误"""
    if exc_type in (RuntimeError, GeneratorExit, BaseExceptionGroup, ExceptionGroup):
        if _is_mcp_cleanup_error(exc_value):
            return  # 静默忽略
    _original_excepthook(exc_type, exc_value, exc_tb)


sys.excepthook = _mcp_excepthook

# 抑制 unraisable 异常（异步生成器关闭时的错误）
_original_unraisablehook = getattr(sys, 'unraisablehook', None)


def _mcp_unraisablehook(unraisable):
    """自定义 unraisable 钩子，抑制 MCP 关闭时的错误"""
    exc = unraisable.exc_value
    if exc and _is_mcp_cleanup_error(exc):
        return  # 静默忽略
    if _original_unraisablehook:
        _original_unraisablehook(unraisable)


if hasattr(sys, 'unraisablehook'):
    sys.unraisablehook = _mcp_unraisablehook


# 自定义 showwarning 来抑制 MCP 相关警告
_original_showwarning = warnings.showwarning


def _mcp_showwarning(message, category, filename, lineno, file=None, line=None):
    """抑制 MCP 相关的警告"""
    msg_str = str(message)
    if any(s in msg_str for s in _MCP_ERROR_KEYWORDS):
        return  # 静默忽略
    if "mcp" in filename.lower() or "anyio" in filename.lower():
        if _is_mcp_cleanup_error(message):
            return
    _original_showwarning(message, category, filename, lineno, file, line)


warnings.showwarning = _mcp_showwarning


# 设置 asyncio 日志级别，抑制 "Task exception was never retrieved" 消息
logging.getLogger("asyncio").setLevel(logging.CRITICAL)


# 抑制 MCP SDK 的 JSONRPC 解析错误（npm stdout 输出被当作 JSON 解析导致）
class _MCPJsonRpcFilter(logging.Filter):
    """过滤 MCP SDK 中 JSONRPC 解析错误的日志"""
    _SUPPRESS_KEYWORDS = [
        "Failed to parse",
        "JSONDecodeError",
        "json.decoder.JSONDecodeError",
        "Expecting value",
        "Extra data",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(kw in msg for kw in self._SUPPRESS_KEYWORDS)


for _logger_name in ("mcp", "mcp.client", "mcp.client.stdio"):
    logging.getLogger(_logger_name).addFilter(_MCPJsonRpcFilter())


__all__ = [
    "MCPClient",
    "MCPManager",
    "MCPToolKit",
    "MCPConfig",
    "MCPServerConfig",
    "MCPTokenManager",
    "MCPServerRegistry",
    "MCPPublishedTool",
    "publish_mcp_tool",
    "publish_mcp_toolkit",
    "BUILTIN_SERVERS",
    "get_builtin_server_config",
    "is_builtin_server",
    "_register_manager",
]
