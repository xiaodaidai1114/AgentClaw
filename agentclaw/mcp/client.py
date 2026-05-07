"""
MCP Client - 单个 MCP Server 连接管理

支持三种传输方式：
- stdio: 本地进程通信
- sse: Server-Sent Events
- streamable_http: HTTP Streamable
"""

from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from agentclaw.logger.config import get_logger
from agentclaw.mcp.config import MCPServerConfig, TransportType, check_command_available
logger = get_logger(__name__)

_MCP_PROXY_ENV = "AGENTCLAW_MCP_PROXY"
_MCP_PROXY_BYPASS_HOSTS = ("localhost", "127.0.0.1", "::1")
_DEFAULT_MCP_TOOL_TIMEOUT = 300.0


def _get_mcp_tool_timeout() -> float:
    raw = os.getenv("AGENTCLAW_MCP_TOOL_TIMEOUT", "").strip()
    if not raw:
        return _DEFAULT_MCP_TOOL_TIMEOUT
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MCP_TOOL_TIMEOUT
    return parsed if parsed > 0 else _DEFAULT_MCP_TOOL_TIMEOUT


def _is_local_mcp_url(url: Optional[str]) -> bool:
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").strip("[]").lower()
    return hostname in _MCP_PROXY_BYPASS_HOSTS


def _get_mcp_proxy(url: Optional[str]) -> Optional[str]:
    proxy = os.getenv(_MCP_PROXY_ENV, "").strip()
    if not proxy or _is_local_mcp_url(url):
        return None
    return proxy


def _is_mcp_remote_token(token: str) -> bool:
    name = PurePath(token).name.lower()
    return name in {"mcp-remote", "mcp-remote.cmd", "mcp-remote.exe"}


def _uses_mcp_remote(command: Optional[str], args: List[str]) -> bool:
    if _is_mcp_remote_token(command or ""):
        return True
    return any(_is_mcp_remote_token(token) for token in args)


def _extract_mcp_remote_target(command: Optional[str], args: List[str]) -> Optional[str]:
    tokens = list(args)
    if _is_mcp_remote_token(command or ""):
        pass
    else:
        index = next((i for i, token in enumerate(tokens) if _is_mcp_remote_token(token)), None)
        if index is None:
            return None
        tokens = tokens[index + 1:]

    for token in tokens:
        if token and not token.startswith("-"):
            return token
    return None


def _merge_no_proxy(existing: Optional[str]) -> str:
    values = [item.strip() for item in (existing or "").split(",") if item.strip()]
    seen = {item.lower() for item in values}
    for host in _MCP_PROXY_BYPASS_HOSTS:
        if host not in seen:
            values.append(host)
            seen.add(host)
    return ",".join(values)


def _build_stdio_proxy_settings(
    config: MCPServerConfig,
    env: Dict[str, str],
) -> tuple[List[str], Dict[str, str]]:
    args = list(config.args)
    if not _uses_mcp_remote(config.command, args):
        return args, env

    target_url = _extract_mcp_remote_target(config.command, args)
    proxy = _get_mcp_proxy(target_url)
    if not proxy:
        return args, env

    next_env = dict(env)
    if "--enable-proxy" not in args:
        args.append("--enable-proxy")
    no_proxy = _merge_no_proxy(next_env.get("NO_PROXY") or next_env.get("no_proxy"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        next_env[key] = proxy
    next_env["NO_PROXY"] = no_proxy
    next_env["no_proxy"] = no_proxy
    return args, next_env


def _create_remote_mcp_http_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: Any = None,
    auth: Any = None,
):
    import httpx

    kwargs: dict[str, Any] = {"follow_redirects": True}
    kwargs["timeout"] = timeout or httpx.Timeout(30.0, read=300.0)
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth

    proxy = _get_mcp_proxy(url)
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["trust_env"] = False
        logger.info(f"MCP Server 远程连接启用代理: {url}")

    return httpx.AsyncClient(**kwargs)


def _get_transport_attempts(config: MCPServerConfig) -> List[TransportType]:
    if config.transport_auto and config.url:
        return [TransportType.SSE, TransportType.STREAMABLE_HTTP]
    return [config.transport]


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str
    
    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        import copy
        schema = copy.deepcopy(self.input_schema) if self.input_schema else {}

        # 递归修复 schema 以符合 JSON Schema draft 2020-12
        def fix_schema(obj, is_root=False):
            if isinstance(obj, dict):
                # 1. 确保 type=object 有 additionalProperties
                if obj.get("type") == "object" and "additionalProperties" not in obj:
                    obj["additionalProperties"] = False

                # 1.5. 确保 type=object 有 required（Claude API 要求）
                if obj.get("type") == "object" and "required" not in obj:
                    obj["required"] = []

                # 2. 转换 exclusiveMinimum/exclusiveMaximum 从数值到布尔值
                if "exclusiveMinimum" in obj and isinstance(obj["exclusiveMinimum"], (int, float)):
                    obj["minimum"] = obj.pop("exclusiveMinimum")
                if "exclusiveMaximum" in obj and isinstance(obj["exclusiveMaximum"], (int, float)):
                    obj["maximum"] = obj.pop("exclusiveMaximum")

                # 3. 移除根级别的 title（Claude API 不接受）
                if is_root and "title" in obj:
                    obj.pop("title")

                # 4. 修复 required 字段：移除不存在于 properties 中的字段
                if "required" in obj and "properties" in obj:
                    valid_props = set(obj["properties"].keys())
                    obj["required"] = [r for r in obj["required"] if r in valid_props]
                    # 保留空数组，不要删除（Claude API 要求）

                # 5. 如果 properties 为空但没有 required，添加空 required
                if "properties" in obj and not obj["properties"] and "required" not in obj:
                    obj["required"] = []

                # 递归处理子字段
                for value in obj.values():
                    fix_schema(value, is_root=False)
            elif isinstance(obj, list):
                for item in obj:
                    fix_schema(item, is_root=False)

        fix_schema(schema, is_root=True)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


class MCPClient:
    """
    MCP Server 客户端
    
    支持三种传输方式：stdio, sse, streamable_http
    """
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.name = config.name
        self._session = None
        self._transport_context = None
        self._tools: Dict[str, MCPTool] = {}
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _close_contexts(self) -> None:
        """
        关闭当前 session 和 transport 上下文（无论 connected 状态）

        这个方法用于连接失败后的清理，避免残留的异步任务影响后续重试。
        """
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except BaseException:
                # 连接失败或取消时，mcp SDK 可能抛出 cancel scope 相关异常
                pass
            finally:
                self._session = None

        if self._transport_context:
            try:
                await self._transport_context.__aexit__(None, None, None)
            except BaseException:
                pass
            finally:
                self._transport_context = None
    
    async def connect(
        self,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        connect_timeout: Optional[float] = None,
    ) -> None:
        """
        连接到 MCP Server

        Args:
            max_retries: 最大重试次数（默认 3 次）
            retry_delay: 重试延迟（秒，默认 0.5 秒）
        """
        if self._connected:
            return

        try:
            from mcp import ClientSession
        except ImportError:
            raise ImportError(
                "需要安装 mcp SDK: pip install mcp\n"
                "或: pip install 'agentclaw[mcp]'"
            )

        last_error = None
        transports = _get_transport_attempts(self.config)
        effective_retries = max_retries
        transport_timeout = None
        if self.config.transport_auto and connect_timeout is not None:
            effective_retries = 1
            transport_timeout = max(connect_timeout / len(transports), 0.1)

        for transport in transports:
            for attempt in range(effective_retries):
                try:
                    # 每次重试都重新建立 transport + session，避免复用坏状态
                    await self._close_contexts()
                    logger.debug(
                        f"MCP Server '{self.name}' 开始初始化（transport={transport.value}, "
                        f"尝试 {attempt + 1}/{effective_retries}）"
                    )
                    await self._open_transport_session(
                        transport,
                        ClientSession,
                        transport_timeout=transport_timeout,
                    )
                    logger.debug(f"MCP Server '{self.name}' 初始化成功")

                    self._connected = True
                    logger.info(f"MCP Server '{self.name}' 连接成功，工具数: {len(self._tools)}")
                    return
                except asyncio.CancelledError as e:
                    # anyio/mcp 在流关闭时可能注入内部取消（带 cancel scope 文案）
                    # 这类取消不是用户主动取消，应转换为普通连接失败，避免取消整条工作流。
                    cancel_msg = str(e)
                    task = asyncio.current_task()
                    is_internal_cancel = (
                        "cancel scope" in cancel_msg and
                        "async_generator_athrow" in cancel_msg
                    )

                    if task and task.cancelling() and not is_internal_cancel:
                        logger.warning(f"MCP Server '{self.name}' 初始化被外部取消")
                        try:
                            await asyncio.shield(self._close_contexts())
                        except BaseException:
                            pass
                        raise

                    # 清除任务上的取消标记，避免将内部取消继续向上冒泡成工作流取消
                    if is_internal_cancel and task and hasattr(task, "uncancel"):
                        while task.cancelling():
                            task.uncancel()

                    self._connected = False
                    self._tools.clear()
                    # 在当前任务内做尽力清理，避免在其它任务关闭 cancel scope 引发串扰
                    try:
                        await self._close_contexts()
                    except asyncio.CancelledError:
                        if task and hasattr(task, "uncancel"):
                            while task.cancelling():
                                task.uncancel()
                        self._session = None
                        self._transport_context = None
                    except BaseException:
                        self._session = None
                        self._transport_context = None

                    raise RuntimeError(
                        f"MCP Server '{self.name}' 初始化被内部取消: {e}"
                    ) from e
                except Exception as e:
                    if isinstance(e, asyncio.TimeoutError) and transport_timeout is not None:
                        e = TimeoutError(
                            f"{transport.value} connect timed out after {transport_timeout:.2f}s"
                        )
                    last_error = e
                    await self._close_contexts()
                    if attempt < effective_retries - 1:
                        logger.debug(
                            f"MCP Server '{self.name}' 初始化失败（尝试 {attempt + 1}/{effective_retries}），"
                            f"{retry_delay}秒后重试: {e}"
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        if transport != transports[-1]:
                            logger.info(
                                f"MCP Server '{self.name}' 使用 {transport.value} 连接失败，"
                                "尝试回退到下一种 HTTP 传输方式"
                            )
                        else:
                            logger.error(
                                f"MCP Server '{self.name}' 初始化失败（已重试 {effective_retries} 次）: {e}"
                            )

        raise RuntimeError(
            f"MCP Server '{self.name}' 初始化失败（已重试 {effective_retries} 次）: {last_error}"
        )

    async def _open_transport_session(
        self,
        transport: TransportType,
        ClientSession,
        *,
        transport_timeout: Optional[float] = None,
    ) -> None:
        async def _establish() -> None:
            if transport == TransportType.STDIO:
                read, write = await self._connect_stdio()
            elif transport == TransportType.SSE:
                read, write = await self._connect_sse()
            elif transport == TransportType.STREAMABLE_HTTP:
                read, write = await self._connect_streamable_http()
            else:
                raise ValueError(f"不支持的传输类型: {transport}")

            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            await self._refresh_tools()

        if transport_timeout is not None:
            await asyncio.wait_for(_establish(), timeout=transport_timeout)
        else:
            await _establish()
    
    async def _connect_stdio(self):
        """stdio 传输连接"""
        from mcp.client.stdio import stdio_client, StdioServerParameters
        
        # 检查命令是否可用
        available, msg = check_command_available(self.config.command)
        if not available:
            raise RuntimeError(f"MCP Server '{self.name}' 启动失败: {msg}")
        
        # 准备环境变量
        env = {**os.environ, **self.config.env}
        args, env = _build_stdio_proxy_settings(self.config, env)
        
        server_params = StdioServerParameters(
            command=self.config.command,
            args=args,
            env=env,
        )
        
        logger.info(
            f"连接 MCP Server (stdio): {self.name} "
            f"({self.config.command} {' '.join(self.config.args)})"
        )
        
        self._transport_context = stdio_client(server_params)
        read, write = await self._transport_context.__aenter__()
        return read, write
    
    async def _connect_sse(self):
        """SSE 传输连接"""
        from mcp.client.sse import sse_client
        
        if not self.config.url:
            raise ValueError(f"MCP Server '{self.name}' 缺少 url 配置")
        
        logger.info(f"连接 MCP Server (sse): {self.name} ({self.config.url})")
        
        self._transport_context = sse_client(
            url=self.config.url,
            headers=self.config.headers or None,
            timeout=self.config.timeout,
            sse_read_timeout=self.config.sse_read_timeout,
            httpx_client_factory=lambda headers, timeout, auth: _create_remote_mcp_http_client(
                self.config.url,
                headers=headers,
                timeout=timeout,
                auth=auth,
            ),
        )
        read, write = await self._transport_context.__aenter__()
        return read, write
    
    async def _connect_streamable_http(self):
        """Streamable HTTP 传输连接"""
        from mcp.client.streamable_http import streamablehttp_client
        
        if not self.config.url:
            raise ValueError(f"MCP Server '{self.name}' 缺少 url 配置")
        
        logger.info(f"连接 MCP Server (streamable_http): {self.name} ({self.config.url})")
        
        self._transport_context = streamablehttp_client(
            url=self.config.url,
            headers=self.config.headers or None,
            timeout=self.config.timeout,
            sse_read_timeout=self.config.sse_read_timeout,
            httpx_client_factory=lambda headers, timeout, auth: _create_remote_mcp_http_client(
                self.config.url,
                headers=headers,
                timeout=timeout,
                auth=auth,
            ),
        )
        # streamablehttp_client 返回 (read, write, get_session_id)
        result = await self._transport_context.__aenter__()
        read, write = result[0], result[1]
        return read, write
    
    async def disconnect(self) -> None:
        """断开连接"""
        if not self._connected and not self._session and not self._transport_context:
            return
        
        # 标记为已断开，防止重复调用
        self._connected = False
        self._tools.clear()

        await self._close_contexts()
        
        logger.debug(f"MCP Server '{self.name}' 已断开")
    
    async def _refresh_tools(self) -> None:
        """刷新工具列表"""
        if not self._session:
            return
        
        result = await self._session.list_tools()
        self._tools.clear()
        
        for tool in result.tools:
            # 获取 input_schema
            input_schema = {}
            if hasattr(tool, "inputSchema"):
                input_schema = tool.inputSchema
            elif hasattr(tool, "input_schema"):
                input_schema = tool.input_schema
            
            self._tools[tool.name] = MCPTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=input_schema,
                server_name=self.name,
            )
    
    def list_tools(self) -> List[MCPTool]:
        """获取所有工具"""
        return list(self._tools.values())
    
    def get_tool(self, name: str) -> Optional[MCPTool]:
        """获取指定工具"""
        return self._tools.get(name)
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self._connected:
            raise RuntimeError(f"MCP Server '{self.name}' 未连接")
        
        if name not in self._tools:
            raise ValueError(f"工具 '{name}' 不存在于 Server '{self.name}'")
        
        logger.info(f"调用 MCP 工具: {self.name}/{name}")
        
        timeout = _get_mcp_tool_timeout()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"MCP tool '{self.name}/{name}' timed out after {timeout:g}s"
            ) from exc
        
        # 处理结果
        if hasattr(result, "content") and result.content:
            texts = []
            for item in result.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
            return "\n".join(texts) if texts else str(result)
        
        return str(result)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
