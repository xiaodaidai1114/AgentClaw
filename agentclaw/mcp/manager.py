"""
MCP Manager - 多 Server 管理

管理多个 MCP Server 连接，提供统一的工具访问接口
"""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentclaw.logger.config import get_logger
from agentclaw.mcp.config import MCPConfig, MCPServerConfig, TransportType
from agentclaw.mcp.client import MCPClient, MCPTool

logger = get_logger(__name__)


class MCPManager:
    """
    MCP Server 管理器
    
    管理多个 MCP Server 连接，提供统一的工具访问接口
    
    Example:
        # 从配置文件加载
        manager = MCPManager.from_config("mcp.json")
        await manager.connect_all()
        
        # 列出所有工具
        tools = manager.list_tools()
        
        # 调用工具
        result = await manager.call_tool("filesystem/read_file", {"path": "README.md"})
        
        # 断开连接
        await manager.disconnect_all()
    """
    
    def __init__(self, config: Optional[MCPConfig] = None):
        self._config = config or MCPConfig()
        self._clients: Dict[str, MCPClient] = {}
        self._tool_map: Dict[str, str] = {}  # tool_name -> server_name
        self._server_locks: Dict[str, asyncio.Lock] = {}  # server_name -> Lock (防止同一 server 并行调用)
        self._connect_tasks: Dict[str, asyncio.Task] = {}

        # 注册到全局管理器，用于程序退出时清理
        try:
            from agentclaw.mcp import _register_manager
            _register_manager(self)
        except ImportError:
            pass
    
    @classmethod
    def from_config(cls, path: Union[str, Path]) -> MCPManager:
        """从配置文件创建 Manager"""
        config = MCPConfig.from_file(path)
        return cls(config)
    
    @classmethod
    def from_dict(cls, data: dict) -> MCPManager:
        """从字典创建 Manager"""
        config = MCPConfig.from_dict(data)
        return cls(config)
    
    def add_server(self, config: MCPServerConfig) -> None:
        """添加 Server 配置"""
        self._config.servers[config.name] = config
    
    async def connect(
        self,
        server_name: str,
        connect_timeout: Optional[float] = None,
    ) -> None:
        """连接指定 Server"""
        config = self._config.get_server(server_name)
        if not config:
            raise ValueError(f"Server '{server_name}' 未配置")
        
        if config.disabled:
            logger.info(f"Server '{server_name}' 已禁用，跳过连接")
            return
        
        if server_name in self._clients:
            if self._clients[server_name].is_connected:
                return

        connect_task = self._connect_tasks.get(server_name)
        if connect_task and not connect_task.done():
            await connect_task
            return
        if connect_task and connect_task.done():
            self._connect_tasks.pop(server_name, None)

        client = MCPClient(config)
        connect_task = asyncio.create_task(
            client.connect(connect_timeout=connect_timeout),
            name=f"mcp-connect-{server_name}",
        )
        self._connect_tasks[server_name] = connect_task
        try:
            await connect_task
        except asyncio.CancelledError as e:
            # 子任务内的 anyio cancel scope 可能触发“伪取消”；
            # 仅在当前任务确实被外部取消时才透传。
            task = asyncio.current_task()
            if task and task.cancelling():
                raise
            raise RuntimeError(f"MCP Server '{server_name}' 连接被内部取消: {e}") from e
        finally:
            if connect_task.done():
                self._connect_tasks.pop(server_name, None)
        self._clients[server_name] = client
        if client.connected_transport:
            self._config.record_detected_transport(server_name, client.connected_transport)

        # 为该 server 创建锁
        if server_name not in self._server_locks:
            self._server_locks[server_name] = asyncio.Lock()

        # 更新工具映射
        for tool in client.list_tools():
            self._tool_map[tool.name] = server_name
    
    async def connect_all(
        self,
        connect_timeout: Optional[float] = None,
    ) -> Dict[str, Optional[str]]:
        """
        连接所有启用的 Server
        
        Returns:
            {server_name: error_message or None}
        """
        results = {}
        servers = self._config.get_enabled_servers()
        
        if not servers:
            logger.info("未配置任何外部 MCP Server，跳过连接")
            return results
        
        # 并行连接所有 Server
        async def connect_one(config: MCPServerConfig) -> tuple[str, Optional[str]]:
            try:
                await self.connect(config.name, connect_timeout=connect_timeout)
                return config.name, None
            except Exception as e:
                logger.error(f"连接 Server '{config.name}' 失败: {e}")
                return config.name, str(e)
        
        task_map = {
            asyncio.create_task(connect_one(server), name=f"mcp-connect-all-{server.name}"): server.name
            for server in servers
        }
        done, pending = await asyncio.wait(
            task_map.keys(),
            timeout=connect_timeout,
        )

        for task in done:
            name, error = await task
            results[name] = error

        for task in pending:
            server_name = task_map[task]
            logger.warning(
                f"连接 Server '{server_name}' 超过等待时间，继续在后台初始化"
            )
            task.add_done_callback(self._finalize_background_connect_task)
            results[server_name] = "connect still running in background"

        connected = sum(1 for e in results.values() if e is None)
        logger.info(f"MCP Server 连接完成: {connected}/{len(servers)} 成功")

        return results

    def _finalize_background_connect_task(self, task: asyncio.Task) -> None:
        for server_name, connect_task in list(self._connect_tasks.items()):
            if connect_task is task and task.done():
                self._connect_tasks.pop(server_name, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.warning(f"后台 MCP 连接任务被取消: {task.get_name()}")
        except Exception as e:
            logger.error(f"后台 MCP 连接任务失败: {e}")
    
    async def disconnect(self, server_name: str) -> None:
        """断开指定 Server"""
        task = self._connect_tasks.pop(server_name, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"取消 Server '{server_name}' 连接任务失败: {e}")

        if server_name in self._clients:
            await self._clients[server_name].disconnect()

            # 清理工具映射
            self._tool_map = {
                k: v for k, v in self._tool_map.items()
                if v != server_name
            }

            # 清理锁
            if server_name in self._server_locks:
                del self._server_locks[server_name]
    
    async def disconnect_all(self) -> None:
        """断开所有 Server"""
        for server_name, task in list(self._connect_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"取消 Server '{server_name}' 连接任务失败: {e}")
        self._connect_tasks.clear()

        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception as e:
                logger.error(f"断开 Server '{client.name}' 失败: {e}")

        self._clients.clear()
        self._tool_map.clear()
        self._server_locks.clear()
    
    def list_servers(self) -> List[str]:
        """列出所有已连接的 Server"""
        return [name for name, client in self._clients.items() if client.is_connected]

    def has_pending_connections(self) -> bool:
        """是否仍有后台 MCP Server 正在初始化。"""
        return any(not task.done() for task in self._connect_tasks.values())
    
    def list_tools(self, server_name: Optional[str] = None) -> List[MCPTool]:
        """
        列出工具
        
        Args:
            server_name: 指定 Server，None 表示所有
        """
        tools = []
        
        if server_name:
            if server_name in self._clients:
                tools = self._clients[server_name].list_tools()
        else:
            for client in self._clients.values():
                if client.is_connected:
                    tools.extend(client.list_tools())
        
        return tools
    
    def get_tool(self, name: str) -> Optional[MCPTool]:
        """获取指定工具"""
        server_name = self._tool_map.get(name)
        if server_name and server_name in self._clients:
            return self._clients[server_name].get_tool(name)
        return None
    
    def get_tools_schema(self, tool_names: Optional[List[str]] = None) -> List[dict]:
        """
        获取 OpenAI function calling 格式的工具列表
        
        Args:
            tool_names: 指定工具名列表，None 表示所有
        """
        tools = self.list_tools()
        
        if tool_names:
            tools = [t for t in tools if t.name in tool_names]
        
        return [t.to_openai_schema() for t in tools]
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用工具（自动查找 server）

        使用服务器级别的锁，防止同一 MCP server 的并行调用导致 stdio 污染

        Args:
            name: 工具名称
            arguments: 工具参数
        """
        server_name = self._tool_map.get(name)
        if not server_name:
            raise ValueError(f"工具 '{name}' 不存在")

        client = self._clients.get(server_name)
        if not client or not client.is_connected:
            raise RuntimeError(f"Server '{server_name}' 未连接")

        # stdio MCP shares one process stream, so keep it serialized.
        # Remote HTTP transports can handle concurrent tool calls.
        lock = self._server_locks.get(server_name)
        if client.config.transport == TransportType.STDIO and lock:
            async with lock:
                return await client.call_tool(name, arguments)
        return await client.call_tool(name, arguments)
    
    async def call_tool_on_server(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用指定 server 的工具

        使用服务器级别的锁，防止同一 MCP server 的并行调用导致 stdio 污染

        Args:
            server_name: MCP Server 名称
            tool_name: 工具名称
            arguments: 工具参数
        """
        client = self._clients.get(server_name)
        if not client:
            raise ValueError(f"Server '{server_name}' 不存在或未连接")

        if not client.is_connected:
            raise RuntimeError(f"Server '{server_name}' 未连接")

        # stdio MCP shares one process stream, so keep it serialized.
        # Remote HTTP transports can handle concurrent tool calls.
        lock = self._server_locks.get(server_name)
        if client.config.transport == TransportType.STDIO and lock:
            async with lock:
                return await client.call_tool(tool_name, arguments)
        return await client.call_tool(tool_name, arguments)
    
    async def __aenter__(self):
        await self.connect_all()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect_all()
