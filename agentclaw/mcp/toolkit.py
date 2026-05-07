"""
MCP ToolKit - 工作流集成组件

将 MCP Server 工具集成到 Workflow 中
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger
from agentclaw.mcp.config import MCPConfig
from agentclaw.mcp.manager import MCPManager

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


class MCPToolKit(BaseComponent):
    """
    MCP 工具集成组件
    
    将 MCP Server 的工具集成到 Workflow 中，
    与 ToolKit 接口兼容，可直接用于 LLMNode
    
    Example:
        # 方式1: 从配置文件加载
        mcp_toolkit = MCPToolKit.from_config("mcp.json")
        workflow.use(mcp_toolkit)
        
        # 方式2: 直接配置
        mcp_toolkit = MCPToolKit({
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                }
            }
        })
        workflow.use(mcp_toolkit)
        
        # 在 LLMNode 中使用
        workflow.add_node(LLMNode(
            id="agent",
            tools=["read_file", "write_file"],  # MCP 工具名
            tool_choice="auto"
        ))
    """
    
    def __init__(
        self,
        config: Optional[Union[dict, MCPConfig, str, Path]] = None,
        auto_connect: bool = True,
    ):
        """
        Args:
            config: MCP 配置（字典、MCPConfig、或配置文件路径）
            auto_connect: 是否在 on_init 时自动连接
        """
        self._manager: Optional[MCPManager] = None
        self._auto_connect = auto_connect
        self._workflow_id: Optional[str] = None
        self._connected = False
        
        # 解析配置
        if config is None:
            self._config = MCPConfig()
        elif isinstance(config, (str, Path)):
            self._config = MCPConfig.from_file(config)
        elif isinstance(config, dict):
            self._config = MCPConfig.from_dict(config)
        else:
            self._config = config
    
    @classmethod
    def from_config(cls, path: Union[str, Path], **kwargs) -> MCPToolKit:
        """从配置文件创建"""
        return cls(config=path, **kwargs)
    
    def on_init(self, workflow: Workflow) -> None:
        """组件初始化"""
        self._workflow_id = workflow.id
        self._manager = MCPManager(self._config)
        
        servers = self._config.get_enabled_servers()
        server_details = []
        for server in servers:
            if server.url:
                server_details.append(f"{server.name}({server.transport.value}:{server.url})")
            else:
                command = " ".join([server.command or "", *server.args]).strip()
                server_details.append(f"{server.name}(stdio:{command})")
        logger.info(
            f"MCPToolKit 初始化: workflow={workflow.id}, "
            f"servers={len(servers)}, 外部MCP={server_details}"
        )
    
    async def connect(
        self,
        connect_timeout: Optional[float] = None,
    ) -> Dict[str, Optional[str]]:
        """
        连接所有 MCP Server
        
        Returns:
            {server_name: error_message or None}
        """
        if not self._manager:
            raise RuntimeError("MCPToolKit 未初始化，请先调用 workflow.use()")
        
        results = await self._manager.connect_all(connect_timeout=connect_timeout)
        self._connected = (
            not results
            or any(e is None for e in results.values())
            or bool(self._manager.list_servers())
        )
        if self._manager:
            connected_servers = self._manager.list_servers()
            tools_by_server = {
                server_name: [tool.name for tool in self._manager.list_tools(server_name)]
                for server_name in connected_servers
            }
            logger.info(
                "MCPToolKit 工具加载完成: workflow=%s, connected_servers=%s, tools_by_server=%s",
                self._workflow_id,
                connected_servers,
                tools_by_server,
            )
        return results
    
    async def disconnect(self) -> None:
        """断开所有连接"""
        if self._manager:
            await self._manager.disconnect_all()
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        if not self._connected and self._manager and self._manager.list_servers():
            self._connected = True
        return self._connected

    @property
    def is_connecting(self) -> bool:
        return bool(self._manager and self._manager.has_pending_connections())
    
    def list_tools(self) -> List[str]:
        """列出所有可用工具名"""
        if not self._manager:
            return []
        return [t.name for t in self._manager.list_tools()]
    
    def get_tools_schema(self) -> List[dict]:
        """获取 OpenAI function calling 格式的工具列表"""
        if not self._manager:
            return []
        return self._manager.get_tools_schema()
    
    def get_schemas(self, tool_names: List[str]) -> List[dict]:
        """获取指定工具的 schema"""
        if not self._manager:
            return []
        return self._manager.get_tools_schema(tool_names)
    
    async def execute(
        self, 
        name: str, 
        arguments: Union[str, dict],
        state: dict = None,
    ) -> Any:
        """
        执行工具（LLMNode 调用的接口）
        
        Args:
            name: 工具名称
            arguments: 工具参数
            state: 当前状态（可选）
        
        Returns:
            工具执行结果
        """
        return await self.call(name, arguments)
    
    async def call(self, name: str, arguments: Union[str, dict]) -> Any:
        """
        调用工具（自动查找 server）
        
        Args:
            name: 工具名称
            arguments: 参数（字符串会被解析为 JSON）
        """
        if not self._manager:
            raise RuntimeError("MCPToolKit 未初始化")
        
        if not self._connected:
            # 自动连接
            await self.connect()
        
        # 解析参数
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"input": arguments}
        
        logger.info(f"调用 MCP 工具: {name}")
        return await self._manager.call_tool(name, arguments)
    
    async def call_with_server(self, server: str, name: str, arguments: Union[str, dict]) -> Any:
        """
        调用指定 server 的工具
        
        Args:
            server: MCP Server 名称
            name: 工具名称
            arguments: 参数
        """
        if not self._manager:
            raise RuntimeError("MCPToolKit 未初始化")
        
        if not self._connected:
            await self.connect()
        
        # 解析参数
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"input": arguments}
        
        logger.info(f"调用 MCP 工具: {server}/{name}")
        return await self._manager.call_tool_on_server(server, name, arguments)
    
    def get_tool(self, name: str):
        """获取工具定义"""
        if not self._manager:
            return None
        return self._manager.get_tool(name)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
