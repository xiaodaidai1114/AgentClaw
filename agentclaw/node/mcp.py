"""
MCPNode - MCP 工具节点

将 MCP 工具作为工作流节点直接使用
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING

from agentclaw.node.base import BaseNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


@dataclass
class MCPNode(BaseNode):
    """
    MCP 工具节点
    
    将 MCP Server 的工具直接作为工作流节点使用，
    无需 LLM 介入，直接调用指定工具。
    
    Args:
        id: 节点唯一标识
        server: MCP Server 名称（mcp.json 中的 key）
        tool: 工具名称
        output: 输出参数名（必填，结果存储到 state[output]）
        arguments: 工具参数，支持模板字符串 {key} 从 state 获取值
        input_mapping: 输入映射 {参数名: state键名}
    
    Example:
        # fetch server 的 fetch 工具
        workflow.add_node(MCPNode(
            id="fetch_page",
            server="fetch",
            tool="fetch",
            output="page_content",  # 结果存到 state["page_content"]
            arguments={"url": "{target_url}"},
        ))
        
        # 12306 server 的 get-tickets 工具
        workflow.add_node(MCPNode(
            id="query_tickets",
            server="12306",
            tool="get-tickets",
            output="ticket_list",
            arguments={
                "date": "{query_date}",
                "fromStation": "{from_code}",
                "toStation": "{to_code}",
            },
        ))
        
        # 使用 input_mapping 映射参数
        workflow.add_node(MCPNode(
            id="get_codes",
            server="12306",
            tool="get-station-code-of-citys",
            output="station_codes",
            input_mapping={"citys": "city_names"},  # arguments["citys"] = state["city_names"]
        ))
    """
    
    # MCP Server 名称（mcp.json 中的 key）
    server: str = ""
    
    # 工具名称
    tool: str = ""
    
    # 输出参数名（必填）
    output: str = ""
    
    # 工具参数（支持模板字符串）
    arguments: Dict[str, Any] = field(default_factory=dict)
    
    # 输入映射：{参数名: state键名}
    input_mapping: Optional[Dict[str, str]] = None
    
    def __post_init__(self):
        if not self.server:
            raise ValueError(f"MCPNode '{self.id}' 必须指定 server（MCP Server 名称）")
        if not self.tool:
            raise ValueError(f"MCPNode '{self.id}' 必须指定 tool（工具名称）")
        if not self.output:
            raise ValueError(f"MCPNode '{self.id}' 必须指定 output（输出参数名）")
    
    def _resolve_arguments(self, state: dict) -> Dict[str, Any]:
        """解析参数，支持模板字符串"""
        import re
        
        resolved = {}
        
        # 先应用 input_mapping
        if self.input_mapping:
            for arg_key, state_key in self.input_mapping.items():
                if state_key in state:
                    resolved[arg_key] = state[state_key]
        
        # 再处理 arguments（会覆盖 input_mapping 的同名参数）
        for key, value in self.arguments.items():
            if isinstance(value, str) and "{" in value and "}" in value:
                # 模板字符串替换
                def replace(match):
                    k = match.group(1)
                    v = state.get(k, match.group(0))
                    return str(v) if v is not None else ""
                resolved[key] = re.sub(r"\{(\w+)\}", replace, value)
            else:
                resolved[key] = value
        
        return resolved
    
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """执行 MCP 工具"""
        # 获取 MCP toolkit
        toolkit = getattr(context, "toolkit", None)
        if not toolkit:
            raise RuntimeError(
                f"MCPNode '{self.id}' 需要 MCP toolkit，"
                "请确保工作流目录下有 mcp.json 配置文件"
            )
        
        # 检查是否是 MCPToolKit
        from agentclaw.mcp.toolkit import MCPToolKit
        if not isinstance(toolkit, MCPToolKit):
            raise RuntimeError(
                f"MCPNode '{self.id}' 需要 MCPToolKit，"
                f"当前 toolkit 类型: {type(toolkit).__name__}"
            )
        
        # 解析参数
        arguments = self._resolve_arguments(state)
        
        logger.info(f"MCPNode '{self.id}' 调用: {self.server}/{self.tool}")
        logger.debug(f"参数: {arguments}")
        
        # 调用工具（指定 server）
        result = await toolkit.call_with_server(self.server, self.tool, arguments)
        
        # 存储结果到指定的 output 参数
        state[self.output] = result
        
        # 输出到用户
        if self.output_to_user:
            from agentclaw.runtime.streaming import output
            result_str = str(result)
            await output(result_str[:500] if len(result_str) > 500 else result_str)
        
        return state


@dataclass  
class MCPPipelineNode(BaseNode):
    """
    MCP 工具管道节点
    
    按顺序执行多个 MCP 工具，前一个工具的输出可以作为后一个工具的输入。
    
    Args:
        id: 节点唯一标识
        steps: 执行步骤列表，每个步骤包含 server, tool, output, arguments
        stop_on_error: 是否在任一步骤失败时停止
    
    Example:
        workflow.add_node(MCPPipelineNode(
            id="train_query",
            steps=[
                {
                    "server": "12306",
                    "tool": "get-current-date",
                    "output": "query_date",
                },
                {
                    "server": "12306",
                    "tool": "get-station-code-of-citys",
                    "arguments": {"citys": "{from_city}|{to_city}"},
                    "output": "station_codes",
                },
                {
                    "server": "12306",
                    "tool": "get-tickets",
                    "arguments": {
                        "date": "{query_date}",
                        "fromStation": "{from_code}",
                        "toStation": "{to_code}",
                    },
                    "output": "tickets",
                },
            ],
        ))
    """
    
    # 执行步骤列表
    steps: List[Dict[str, Any]] = field(default_factory=list)
    
    # 是否在任一步骤失败时停止
    stop_on_error: bool = True
    
    def __post_init__(self):
        if not self.steps:
            raise ValueError(f"MCPPipelineNode '{self.id}' 必须指定 steps")
        
        for i, step in enumerate(self.steps):
            if "server" not in step:
                raise ValueError(f"MCPPipelineNode '{self.id}' 步骤 {i} 缺少 server")
            if "tool" not in step:
                raise ValueError(f"MCPPipelineNode '{self.id}' 步骤 {i} 缺少 tool")
            if "output" not in step:
                raise ValueError(f"MCPPipelineNode '{self.id}' 步骤 {i} 缺少 output")
    
    def _resolve_arguments(self, arguments: Dict[str, Any], state: dict) -> Dict[str, Any]:
        """解析参数"""
        import re
        
        resolved = {}
        for key, value in arguments.items():
            if isinstance(value, str) and "{" in value and "}" in value:
                def replace(match):
                    k = match.group(1)
                    v = state.get(k, match.group(0))
                    return str(v) if v is not None else ""
                resolved[key] = re.sub(r"\{(\w+)\}", replace, value)
            else:
                resolved[key] = value
        
        return resolved
    
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """按顺序执行所有步骤"""
        toolkit = getattr(context, "toolkit", None)
        if not toolkit:
            raise RuntimeError(f"MCPPipelineNode '{self.id}' 需要 MCP toolkit")
        
        from agentclaw.mcp.toolkit import MCPToolKit
        if not isinstance(toolkit, MCPToolKit):
            raise RuntimeError(f"MCPPipelineNode '{self.id}' 需要 MCPToolKit")
        
        for i, step in enumerate(self.steps):
            server = step["server"]
            tool_name = step["tool"]
            output_key = step["output"]
            arguments = step.get("arguments", {})
            
            logger.info(f"MCPPipelineNode '{self.id}' 步骤 {i+1}/{len(self.steps)}: {server}/{tool_name}")
            
            try:
                # 解析参数
                resolved_args = self._resolve_arguments(arguments, state)
                
                # 调用工具
                result = await toolkit.call_with_server(server, tool_name, resolved_args)
                
                # 存储结果
                state[output_key] = result
                
            except Exception as e:
                logger.error(f"MCPPipelineNode '{self.id}' 步骤 {i+1} 失败: {e}")
                if self.stop_on_error:
                    raise
                state[output_key] = f"ERROR: {e}"
        
        return state
