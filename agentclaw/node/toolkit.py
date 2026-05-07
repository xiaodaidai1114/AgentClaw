"""
ToolKit - 工具集组件

支持：
- 装饰器注册工具 (@toolkit.tool)
- 从 docstring / 类型注解 / 手动注入 提取参数描述
- 生成 OpenAI function calling schema
- 工具调用执行
- 审批控制

Example:
    toolkit = ToolKit()
    
    # 方式1：从 docstring 自动提取参数描述
    @toolkit.tool
    async def search(query: str, limit: int = 10) -> list:
        '''
        搜索数据库
        
        Args:
            query: 搜索关键词
            limit: 返回数量限制
        '''
        ...
    
    # 方式2：手动注入参数描述
    @toolkit.tool(params={
        "query": {"description": "搜索关键词"},
        "limit": {"description": "返回数量限制"}
    })
    async def search(query: str, limit: int = 10) -> list:
        '''搜索数据库'''
        ...
    
    # 方式3：使用 Annotated 类型
    @toolkit.tool
    async def search(
        query: Annotated[str, "搜索关键词"],
        limit: Annotated[int, "返回数量限制"] = 10
    ) -> list:
        '''搜索数据库'''
        ...
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union, get_type_hints, get_origin, get_args
import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


# ============ 参数解析工具函数 ============

def _parse_docstring_args(docstring: str) -> Dict[str, str]:
    """
    从 docstring 解析参数描述（支持 Google style）
    
    Example:
        Args:
            query: 搜索关键词
            limit: 返回数量限制
    """
    if not docstring:
        return {}
    
    params = {}
    in_args_section = False
    
    for line in docstring.split("\n"):
        line = line.strip()
        
        # 检测 Args 部分开始
        if line.lower() in ("args:", "arguments:", "parameters:", "params:"):
            in_args_section = True
            continue
        
        # 检测其他部分开始（退出 Args）
        if in_args_section and line.endswith(":") and ":" not in line[:-1]:
            in_args_section = False
            continue
        
        # 解析参数描述
        if in_args_section and ":" in line:
            match = re.match(r"(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)", line)
            if match:
                param_name, description = match.groups()
                params[param_name] = description.strip()
    
    return params


def _python_type_to_json_type(py_type: Any) -> str:
    """Python 类型转 JSON Schema 类型"""
    if py_type is None or py_type is type(None):
        return "null"
    
    origin = get_origin(py_type)
    
    # 处理 Optional, Union
    if origin is Union:
        args = get_args(py_type)
        for arg in args:
            if arg is not type(None):
                return _python_type_to_json_type(arg)
    
    # 处理 Annotated
    if hasattr(py_type, "__metadata__"):
        return _python_type_to_json_type(get_args(py_type)[0])
    
    # 基本类型映射
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    
    return type_map.get(py_type, "string")


def _get_annotated_description(annotation: Any) -> Optional[str]:
    """从 Annotated 类型提取描述"""
    if hasattr(annotation, "__metadata__"):
        for meta in annotation.__metadata__:
            if isinstance(meta, str):
                return meta
    return None


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 格式
    
    # 调用方式（二选一）
    endpoint: Optional[str] = None  # HTTP 端点
    handler: Optional[Callable] = None  # 本地函数
    
    # 控制选项
    require_approval: bool = False  # 是否需要人工审批
    timeout: int = 30  # 超时时间（秒）
    
    # HTTP 配置
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    
    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        # 获取必需参数
        required = getattr(self, "_required_params", None)
        if required is None:
            # 兼容旧格式
            required = [
                k for k, v in self.parameters.items()
                if v.get("required", False) or "default" not in v
            ]
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": required,
                },
            },
        }


class ToolKit(BaseComponent):
    """
    工具集管理器
    
    管理工作流可用的工具，支持装饰器注册和 HTTP 调用
    
    Example:
        toolkit = ToolKit()
        
        @toolkit.tool
        async def search(query: str, limit: int = 10) -> list:
            '''
            搜索数据库
            
            Args:
                query: 搜索关键词
                limit: 返回数量限制
            '''
            return await db.search(query, limit)
        
        workflow.use(toolkit)
    """
    
    def __init__(
        self,
        tools: Optional[List[Union[dict, Tool]]] = None,
        # HTTP 客户端配置
        http_timeout: int = 30,
        http_headers: Optional[Dict[str, str]] = None,
    ):
        self.http_timeout = http_timeout
        self.http_headers = http_headers or {}
        
        # 注册工具
        self._tools: Dict[str, Tool] = {}
        if tools:
            for t in tools:
                self.register(t)
        
        self._workflow_id: Optional[str] = None
    
    def on_init(self, workflow: Workflow) -> None:
        """组件初始化"""
        self._workflow_id = workflow.id
        logger.info(f"ToolKit 初始化完成: workflow={workflow.id}, tools={len(self._tools)}")
    
    def tool(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        params: Optional[Dict[str, Dict[str, Any]]] = None,
        require_approval: bool = False,
        timeout: int = 30,
    ) -> Callable:
        """
        装饰器：注册函数为工具
        
        参数描述提取优先级：
        1. params 手动注入
        2. Annotated 类型注解
        3. docstring Args 部分
        
        Example:
            @toolkit.tool
            async def search(query: str) -> list:
                '''搜索数据库
                
                Args:
                    query: 搜索关键词
                '''
                ...
            
            @toolkit.tool(params={"query": {"description": "关键词"}})
            async def search(query: str) -> list:
                ...
        """
        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            
            # 提取函数描述（第一行非空 docstring）
            doc = fn.__doc__ or ""
            tool_desc = description
            if not tool_desc:
                for line in doc.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("Args"):
                        tool_desc = line
                        break
                tool_desc = tool_desc or ""
            
            # 解析参数
            sig = inspect.signature(fn)
            docstring_args = _parse_docstring_args(doc)
            
            # 尝试获取类型注解
            try:
                hints = get_type_hints(fn, include_extras=True)
            except Exception:
                hints = {}
            
            parameters = {}
            required_params = []
            
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                
                # 获取类型
                annotation = hints.get(param_name, param.annotation)
                if annotation == inspect.Parameter.empty:
                    annotation = str  # 默认 string
                
                param_type = _python_type_to_json_type(annotation)
                
                # 获取描述（优先级：手动注入 > Annotated > docstring）
                param_desc = ""
                if params and param_name in params:
                    param_desc = params[param_name].get("description", "")
                if not param_desc:
                    param_desc = _get_annotated_description(annotation) or ""
                if not param_desc:
                    param_desc = docstring_args.get(param_name, "")
                
                # 构建参数 schema
                param_schema = {"type": param_type}
                if param_desc:
                    param_schema["description"] = param_desc
                
                # 处理默认值
                if param.default != inspect.Parameter.empty:
                    param_schema["default"] = param.default
                else:
                    required_params.append(param_name)
                
                # 合并手动注入的额外属性
                if params and param_name in params:
                    for k, v in params[param_name].items():
                        if k != "description":
                            param_schema[k] = v
                
                parameters[param_name] = param_schema
            
            # 创建并注册工具
            tool_def = Tool(
                name=tool_name,
                description=tool_desc,
                parameters=parameters,
                handler=fn,
                require_approval=require_approval,
                timeout=timeout,
            )
            tool_def._required_params = required_params
            
            self._tools[tool_name] = tool_def
            logger.debug(f"注册工具: {tool_name}")
            
            # 保留原函数，附加工具定义
            fn._tool_definition = tool_def
            return fn
        
        # 支持 @toolkit.tool 和 @toolkit.tool(...) 两种用法
        if func is not None:
            return decorator(func)
        return decorator
    
    def register(self, tool: Union[dict, Tool, Callable]) -> None:
        """
        注册工具
        
        Args:
            tool: 工具定义（dict、Tool 实例或带 _tool_definition 的函数）
        """
        # 如果是函数，检查是否有 _tool_definition
        if callable(tool) and hasattr(tool, "_tool_definition"):
            self._tools[tool._tool_definition.name] = tool._tool_definition
            return
        
        if isinstance(tool, dict):
            tool = Tool(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=tool.get("parameters", {}),
                endpoint=tool.get("endpoint"),
                handler=tool.get("handler"),
                require_approval=tool.get("require_approval", False),
                timeout=tool.get("timeout", 30),
                method=tool.get("method", "POST"),
                headers=tool.get("headers", {}),
            )
        
        self._tools[tool.name] = tool
        logger.debug(f"注册工具: {tool.name}")
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)
    
    def list_tools(self) -> List[str]:
        """列出所有工具名"""
        return list(self._tools.keys())
    
    def get_tools_schema(self) -> List[dict]:
        """
        获取 OpenAI function calling 格式的工具列表
        
        用于 LLM 调用
        """
        return [tool.to_openai_schema() for tool in self._tools.values()]
    
    def get_schemas(self, tool_names: List[str]) -> List[dict]:
        """
        获取指定工具的 OpenAI function calling 格式 schema
        
        Args:
            tool_names: 工具名称列表
        
        Returns:
            工具 schema 列表
        """
        schemas = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                schemas.append(tool.to_openai_schema())
            else:
                logger.warning(f"工具 '{name}' 不存在")
        return schemas
    
    async def execute(self, name: str, arguments: Union[str, dict], state: dict = None) -> Any:
        """
        执行工具（LLMNode 调用的接口）
        
        Args:
            name: 工具名称
            arguments: 工具参数
            state: 当前状态（可选，用于上下文）
        
        Returns:
            工具执行结果
        """
        return await self.call(name, arguments)
    
    async def call(
        self, 
        name: str, 
        params: Union[str, dict],
    ) -> Any:
        """
        调用工具
        
        Args:
            name: 工具名称
            params: 参数（字符串会被解析为 JSON）
        
        Returns:
            工具执行结果
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"工具 '{name}' 不存在")
        
        # 解析参数
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {"input": params}
        
        # 处理嵌套的 input 字段（某些 LLM 会把所有参数放在 input 字段中）
        if isinstance(params, dict) and len(params) == 1 and "input" in params:
            input_val = params["input"]
            if isinstance(input_val, str):
                try:
                    parsed = json.loads(input_val)
                    if isinstance(parsed, dict):
                        params = parsed
                except json.JSONDecodeError:
                    pass  # 保持原样
        
        logger.info(f"调用工具: {name}, params={params}")
        
        # 执行调用
        try:
            if tool.handler:
                result = await self._call_handler(tool, params)
            elif tool.endpoint:
                result = await self._call_http(tool, params)
            else:
                raise ValueError(f"工具 '{name}' 未配置 handler 或 endpoint")
            
            logger.info(f"工具 {name} 执行成功")
            return result
            
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}")
            raise
    
    async def _call_handler(self, tool: Tool, params: dict) -> Any:
        """调用本地函数"""
        if asyncio.iscoroutinefunction(tool.handler):
            return await asyncio.wait_for(
                tool.handler(**params),
                timeout=tool.timeout,
            )
        else:
            return tool.handler(**params)
    
    async def _call_http(self, tool: Tool, params: dict) -> Any:
        """调用 HTTP 端点"""
        try:
            import httpx
        except ImportError:
            raise ImportError("需要安装 httpx: pip install httpx")
        
        headers = {**self.http_headers, **tool.headers}
        
        async with httpx.AsyncClient(timeout=tool.timeout) as client:
            if tool.method.upper() == "GET":
                response = await client.get(
                    tool.endpoint,
                    params=params,
                    headers=headers,
                )
            else:
                response = await client.request(
                    tool.method.upper(),
                    tool.endpoint,
                    json=params,
                    headers=headers,
                )
            
            response.raise_for_status()
            
            # 尝试解析 JSON
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
    
    async def call_with_approval_check(
        self,
        name: str,
        params: dict,
        approved: bool = False,
    ) -> dict:
        """
        带审批检查的工具调用
        
        Args:
            name: 工具名称
            params: 参数
            approved: 是否已批准
        
        Returns:
            包含 result 或 pending_approval 的字典
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"工具 '{name}' 不存在")
        
        if tool.require_approval and not approved:
            return {
                "status": "pending_approval",
                "tool": name,
                "params": params,
                "message": f"工具 '{name}' 需要人工审批",
            }
        
        result = await self.call(name, params)
        return {
            "status": "success",
            "tool": name,
            "result": result,
        }


def tool(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    params: Optional[Dict[str, Dict[str, Any]]] = None,
    require_approval: bool = False,
    timeout: int = 30,
) -> Callable:
    """
    全局装饰器：将函数标记为工具（需配合 ToolKit.register 使用）
    
    参数描述提取优先级：
    1. params 手动注入
    2. Annotated 类型注解
    3. docstring Args 部分
    
    Example:
        @tool
        async def search(query: str, limit: int = 10) -> list:
            '''
            搜索数据库
            
            Args:
                query: 搜索关键词
                limit: 返回数量限制
            '''
            ...
        
        # 注册到 ToolKit
        toolkit = ToolKit()
        toolkit.register(search)
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        
        # 提取函数描述
        doc = fn.__doc__ or ""
        tool_desc = description or doc.split("\n")[0].strip()
        
        # 解析参数
        sig = inspect.signature(fn)
        docstring_args = _parse_docstring_args(doc)
        
        try:
            hints = get_type_hints(fn, include_extras=True)
        except Exception:
            hints = {}
        
        parameters = {}
        required_params = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            
            annotation = hints.get(param_name, param.annotation)
            if annotation == inspect.Parameter.empty:
                annotation = str
            
            param_type = _python_type_to_json_type(annotation)
            
            # 获取描述
            param_desc = ""
            if params and param_name in params:
                param_desc = params[param_name].get("description", "")
            if not param_desc:
                param_desc = _get_annotated_description(annotation) or ""
            if not param_desc:
                param_desc = docstring_args.get(param_name, "")
            
            param_schema = {"type": param_type}
            if param_desc:
                param_schema["description"] = param_desc
            
            if param.default != inspect.Parameter.empty:
                param_schema["default"] = param.default
            else:
                required_params.append(param_name)
            
            if params and param_name in params:
                for k, v in params[param_name].items():
                    if k != "description":
                        param_schema[k] = v
            
            parameters[param_name] = param_schema
        
        # 附加工具定义到函数
        tool_def = Tool(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            handler=fn,
            require_approval=require_approval,
            timeout=timeout,
        )
        tool_def._required_params = required_params
        fn._tool_definition = tool_def
        
        return fn
    
    if func is not None:
        return decorator(func)
    return decorator
