"""
MCP Server - 将工作流发布为 MCP Server

支持：
- SSE 传输
- Streamable HTTP 传输
- 工作流聚合（多个工作流聚合到一个 MCP 端点）
- 框架本地函数 / ToolKit 工具发布为 MCP 工具
"""

from __future__ import annotations
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow
    from agentclaw.node.toolkit import ToolKit, Tool

logger = get_logger(__name__)

_MCP_TOKEN_PLACEHOLDERS = {
    "your-mcp-token",
    "your_mcp_token",
    "changeme",
    "change-me",
}


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _is_placeholder_mcp_token(value: str) -> bool:
    return _strip_env_quotes(value).strip().lower() in _MCP_TOKEN_PLACEHOLDERS


def _get_project_dir() -> Optional[Path]:
    raw_project_dir = os.getenv("AGENTCLAW_PROJECT_DIR", "").strip()
    if not raw_project_dir:
        return None
    return Path(raw_project_dir).expanduser().resolve()


def _read_project_env_mcp_token(project_dir: Optional[Path]) -> str:
    if project_dir is None:
        return ""

    env_file = project_dir / ".env"
    if not env_file.exists():
        return ""

    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() != "MCP_TOKEN":
            continue
        token = _strip_env_quotes(value)
        if token and not _is_placeholder_mcp_token(token):
            return token
    return ""


def _persist_generated_mcp_token(project_dir: Optional[Path], token: str) -> Optional[Path]:
    if project_dir is None:
        return None

    env_file = project_dir / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    written = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        uncommented = stripped[1:].strip() if stripped.startswith("#") else stripped
        if "=" not in uncommented:
            continue

        key = uncommented.split("=", 1)[0].strip()
        if key != "MCP_TOKEN":
            continue

        lines[index] = f"MCP_TOKEN={token}"
        written = True
        break

    if not written:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# AgentClaw MCP 自动生成")
        lines.append(f"MCP_TOKEN={token}")

    env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return env_file


@dataclass
class MCPPublishedTool:
    """Framework-local function/tool exposed through AgentClaw MCP routes."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Any]
    server: Optional[str] = None

    async def call(self, arguments: Dict[str, Any]) -> Any:
        result = self.handler(arguments)
        if hasattr(result, "__await__"):
            result = await result
        return result

    def to_openai_schema(self) -> Dict[str, Any]:
        """Return an OpenAI-compatible function tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }


def _tool_to_input_schema(tool: "Tool") -> Dict[str, Any]:
    required = getattr(tool, "_required_params", None)
    if required is None:
        required = [
            name
            for name, schema in (tool.parameters or {}).items()
            if schema.get("required", False) or "default" not in schema
        ]

    return {
        "type": "object",
        "properties": tool.parameters or {},
        "required": list(required),
    }


def _format_mcp_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


class MCPTokenManager:
    """MCP Token 管理器（单例）"""
    
    _instance: Optional["MCPTokenManager"] = None
    
    def __init__(self):
        self._token: Optional[str] = None
        self._initialized = False
    
    @classmethod
    def get_instance(cls) -> "MCPTokenManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def token(self) -> str:
        """获取 MCP Token"""
        if not self._initialized:
            self._init_token()
        return self._token
    
    def _init_token(self) -> None:
        """初始化 Token"""
        project_dir = _get_project_dir()
        self._token = os.getenv("MCP_TOKEN", "").strip()
        if self._token and _is_placeholder_mcp_token(self._token):
            self._token = ""

        if not self._token:
            self._token = _read_project_env_mcp_token(project_dir)
            if self._token:
                os.environ["MCP_TOKEN"] = self._token
        
        if not self._token:
            # 自动生成 Token
            self._token = f"mcp-{secrets.token_urlsafe(32)}"
            os.environ["MCP_TOKEN"] = self._token
            env_file: Optional[Path] = None
            persist_error: Optional[OSError] = None
            if project_dir is not None:
                try:
                    env_file = _persist_generated_mcp_token(project_dir, self._token)
                except OSError as exc:
                    persist_error = exc
            from agentclaw.api.auth.utils import mask_secret

            if env_file is not None:
                logger.warning(
                    f"⚠️ MCP_TOKEN 未设置，已自动生成并写入 .env: {mask_secret(self._token)}\n"
                    f"   保存位置: {env_file}"
                )
            elif persist_error is not None:
                logger.warning(
                    f"⚠️ MCP_TOKEN 未设置，已自动生成: {mask_secret(self._token)}\n"
                    f"   写入项目 .env 失败: {persist_error}"
                )
            else:
                logger.warning(
                    f"⚠️ MCP_TOKEN 未设置，已自动生成: {mask_secret(self._token)}\n"
                    f"   未找到 AGENTCLAW_PROJECT_DIR，建议在项目 .env 中设置 MCP_TOKEN 以保持稳定"
                )
        
        self._initialized = True
    
    def verify(self, token: str) -> bool:
        """验证 Token"""
        if not token:
            return False
        return secrets.compare_digest(token, self.token)


class MCPServerRegistry:
    """MCP Server 注册表（管理工作流和框架本地工具到 MCP 端点的映射）"""
    
    _instance: Optional["MCPServerRegistry"] = None
    
    def __init__(self):
        # 独立端点：workflow_id -> Workflow
        self._workflows: Dict[str, "Workflow"] = {}
        # 聚合端点：mcp_server_name -> List[Workflow]
        self._aggregated: Dict[str, List["Workflow"]] = {}
        # 独立端点：tool_name -> MCPPublishedTool
        self._tools: Dict[str, MCPPublishedTool] = {}
        # 聚合端点：mcp_server_name -> {tool_name: MCPPublishedTool}
        self._aggregated_tools: Dict[str, Dict[str, MCPPublishedTool]] = {}
    
    @classmethod
    def get_instance(cls) -> "MCPServerRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, workflow: "Workflow") -> None:
        """注册工作流到 MCP Server"""
        if not workflow.publish_as_mcp:
            return
        
        # 检查并发出警告
        self._check_and_warn(workflow)
        
        if workflow.mcp_server:
            # 聚合模式
            if workflow.mcp_server not in self._aggregated:
                self._aggregated[workflow.mcp_server] = []
            self._aggregated[workflow.mcp_server].append(workflow)
            logger.info(f"工作流 '{workflow.id}' 已注册到 MCP 聚合端点: /mcp/{workflow.mcp_server}")
        else:
            # 独立模式
            self._workflows[workflow.id] = workflow
            logger.info(f"工作流 '{workflow.id}' 已注册为独立 MCP 端点: /mcp/{workflow.id}")

    def register_tool(
        self,
        tool: MCPPublishedTool,
        *,
        server: Optional[str] = None,
        overwrite: bool = False,
    ) -> None:
        """注册框架本地函数/ToolKit 工具到 MCP Server。"""
        tool.server = server

        if server:
            bucket = self._aggregated_tools.setdefault(server, {})
            if tool.name in bucket and not overwrite:
                raise ValueError(f"MCP tool '{tool.name}' already registered in server '{server}'")
            bucket[tool.name] = tool
            logger.info(f"MCP 工具 '{tool.name}' 已注册到聚合端点: /mcp/{server}")
            return

        if tool.name in self._tools and not overwrite:
            raise ValueError(f"MCP tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        logger.info(f"MCP 工具 '{tool.name}' 已注册为独立端点: /mcp/{tool.name}")

    def register_toolkit(
        self,
        toolkit: "ToolKit",
        *,
        server: Optional[str] = None,
        overwrite: bool = False,
    ) -> None:
        """将 ToolKit 中的所有工具发布为 MCP 工具。"""
        for tool_name in toolkit.list_tools():
            tool_def = toolkit.get_tool(tool_name)
            if tool_def is None:
                continue

            async def call_tool(arguments: Dict[str, Any], *, _tool_name: str = tool_name) -> Any:
                return await toolkit.call(_tool_name, arguments or {})

            self.register_tool(
                MCPPublishedTool(
                    name=tool_def.name,
                    description=tool_def.description,
                    input_schema=_tool_to_input_schema(tool_def),
                    handler=call_tool,
                    server=server,
                ),
                server=server,
                overwrite=overwrite,
            )
    
    def _check_and_warn(self, workflow: "Workflow") -> None:
        """检查工作流配置并发出警告"""
        warnings = []
        
        if not workflow.desc:
            warnings.append("未设置 desc（MCP 工具描述）")
        
        # 检查是否定义了输入参数
        if not workflow._input_schema:
            warnings.append("未定义 inputs（MCP 输入参数将为空）")
        
        if warnings:
            logger.warning(
                f"⚠️ 工作流 '{workflow.id}' 发布 MCP 时存在以下问题:\n"
                + "\n".join(f"   - {w}" for w in warnings)
            )
    
    def get_workflow(self, workflow_id: str) -> Optional["Workflow"]:
        """获取独立端点的工作流"""
        return self._workflows.get(workflow_id)
    
    def get_aggregated_workflows(self, mcp_server: str) -> List["Workflow"]:
        """获取聚合端点的工作流列表"""
        return self._aggregated.get(mcp_server, [])

    def get_endpoint_items(self, endpoint_name: str) -> tuple[List["Workflow"], List[MCPPublishedTool]]:
        """获取指定 MCP 端点下的工作流和框架本地工具。"""
        workflows: List["Workflow"] = []
        if endpoint_name in self._workflows:
            workflows.append(self._workflows[endpoint_name])
        workflows.extend(self._aggregated.get(endpoint_name, []))

        tools: List[MCPPublishedTool] = []
        if endpoint_name in self._tools:
            tools.append(self._tools[endpoint_name])
        tools.extend(self._aggregated_tools.get(endpoint_name, {}).values())

        return workflows, tools

    def get_published_tool_groups(self) -> List[tuple[str, List[MCPPublishedTool]]]:
        """获取框架内发布的 MCP 工具分组（不包含 workflow 发布项）。"""
        groups: List[tuple[str, List[MCPPublishedTool]]] = []
        for tool_name, tool in self._tools.items():
            groups.append((tool_name, [tool]))
        for server_name, tools in self._aggregated_tools.items():
            groups.append((server_name, list(tools.values())))
        return groups
    
    def list_endpoints(self) -> Dict[str, Any]:
        """列出所有 MCP 端点"""
        independent = list(self._workflows.keys())
        independent.extend(name for name in self._tools if name not in self._workflows)

        aggregated_names = list(self._aggregated.keys())
        for name in self._aggregated_tools:
            if name not in self._aggregated:
                aggregated_names.append(name)

        endpoints = {
            "independent": independent,
            "aggregated": {
                name: [
                    *[wf.id for wf in self._aggregated.get(name, [])],
                    *list(self._aggregated_tools.get(name, {}).keys()),
                ]
                for name in aggregated_names
            },
        }
        return endpoints
    
    def get_all_mcp_server_names(self) -> List[str]:
        """获取所有 MCP Server 名称（独立 + 聚合）"""
        names = list(self._workflows.keys())
        names.extend(name for name in self._tools if name not in names)
        for name in self._aggregated:
            if name not in names:
                names.append(name)
        for name in self._aggregated_tools:
            if name not in names:
                names.append(name)
        return names


def get_mcp_input_schema(workflow: "Workflow") -> Dict[str, Any]:
    """从工作流生成 MCP 工具的输入 Schema"""
    
    # 使用 _input_schema
    if workflow._input_schema:
        return workflow._input_schema.to_json_schema()
    
    # 默认添加 user_input
    return {
        "type": "object",
        "properties": {
            "user_input": {
                "type": "string",
                "description": "用户输入",
            }
        },
        "required": ["user_input"],
    }


def _python_type_to_json_type(type_str: str) -> str:
    """Python 类型转 JSON Schema 类型"""
    type_map = {
        "str": "string",
        "string": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "list": "array",
        "array": "array",
        "dict": "object",
        "object": "object",
    }
    return type_map.get(type_str.lower(), "string")


async def handle_mcp_tool_call(
    workflow: "Workflow",
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    处理 MCP 工具调用
    
    Args:
        workflow: 工作流实例
        arguments: 工具参数
    
    Returns:
        工具执行结果
    """
    try:
        result = await workflow.run(
            inputs=arguments,
            stream=False,
        )
        
        state = result.get("state", {})
        
        # 提取 answer
        answer = ""
        messages = state.get("__messages__") or []
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                answer = msg.get("content", "")
                break
            elif hasattr(msg, "content") and hasattr(msg, "type") and msg.type == "ai":
                answer = msg.content
                break
        
        # 返回结果
        return {
            "success": True,
            "answer": answer,
            "state": {k: v for k, v in state.items() if not k.startswith("__")},
        }
        
    except Exception as e:
        logger.error(f"MCP 工具调用失败: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def handle_mcp_published_tool_call(
    tool: MCPPublishedTool,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """处理框架本地 MCP 工具调用。"""
    try:
        result = await tool.call(arguments or {})
        return {
            "success": True,
            "answer": _format_mcp_result(result),
            "raw_result": result,
        }
    except Exception as e:
        logger.error(f"MCP 工具调用失败: {tool.name}: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def publish_mcp_toolkit(
    toolkit: "ToolKit",
    *,
    server: Optional[str] = None,
    overwrite: bool = False,
) -> "ToolKit":
    """Publish every tool in a ToolKit through AgentClaw's built-in MCP routes."""
    from agentclaw.node.toolkit import ToolKit

    if not isinstance(toolkit, ToolKit):
        raise TypeError(f"publish_mcp_toolkit expects ToolKit, got {type(toolkit).__name__}")

    MCPServerRegistry.get_instance().register_toolkit(
        toolkit,
        server=server,
        overwrite=overwrite,
    )
    return toolkit


def publish_mcp_tool(
    func: Optional[Callable] = None,
    *,
    server: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    params: Optional[Dict[str, Dict[str, Any]]] = None,
    timeout: int = 30,
    overwrite: bool = False,
) -> Callable:
    """Publish a single function through AgentClaw's built-in MCP routes."""
    from agentclaw.node.toolkit import ToolKit

    def decorator(fn: Callable) -> Callable:
        toolkit = ToolKit()
        registered = toolkit.tool(
            fn,
            name=name,
            description=description,
            params=params,
            timeout=timeout,
        )
        publish_mcp_toolkit(toolkit, server=server, overwrite=overwrite)
        return registered

    if func is not None:
        return decorator(func)
    return decorator
