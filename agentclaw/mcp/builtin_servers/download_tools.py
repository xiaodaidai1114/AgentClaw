"""Built-in MCP server: download-tools."""
import os
from pathlib import Path
from typing import List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentclaw.database.manager import DatabaseManager, RedisConfig
from agentclaw.logger.config import get_logger
from agentclaw.mcp.download_limits import (
    normalize_download_ttl,
    validate_download_file_size,
)

logger = get_logger(__name__)

class DownloadToolsServer:
    """
    Download Tools MCP Server

    为本地文件生成临时下载 URL（通过 Redis 存储）。
    前端/用户可通过 /api/download/{token} 访问文件。

    需要 Redis（通过环境变量 REDIS_URL 配置，默认 redis://localhost:6379/0）。

    工具：
    - create_download_url: 为本地文件生成临时下载链接
    - get_file_url: 根据文件 ID 生成短期签名下载 URL

    Usage:
        python -m agentclaw.mcp.builtin_servers download-tools --working-dir .
    """

    def __init__(self, working_dir: Optional[str] = None):
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self._server = Server("download-tools")
        self._setup_handlers()

    @staticmethod
    def _get_redis_client():
        return DatabaseManager.create_sync_redis_client(RedisConfig.from_env())
    
    def _setup_handlers(self):
        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="create_download_url",
                    description=(
                        "为本地文件生成一个临时下载 URL。"
                        "用户可通过该 URL 在浏览器中下载/查看文件（图片、PDF、文档等）。"
                        "链接默认 1 小时后过期。"
                        "注意：相对路径基于服务端工作目录解析。"
                        "返回的 URL 可能是相对路径（例如 /api/download/<token>）。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "本地文件路径（绝对路径或相对于工作目录的路径）",
                            },
                            "filename": {
                                "type": "string",
                                "description": "下载时显示的文件名（可选，默认使用原文件名）",
                            },
                            "ttl": {
                                "type": "integer",
                                "description": "链接有效期（秒），默认 3600（1小时）",
                                "default": 3600,
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="get_file_url",
                    description=(
                        "根据文件 ID 生成短期签名下载 URL。"
                        "文件必须已通过统一文件存储保存（上传的文件或知识库文档）。"
                        "返回的 URL 格式为 /api/files/{file_id}?token=...，默认 1 小时有效。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_id": {
                                "type": "string",
                                "description": "文件 ID（来自 files 表）",
                            },
                        },
                        "required": ["file_id"],
                    },
                ),
            ]
        
        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            if name == "create_download_url":
                result = await self._create_download_url(arguments)
            elif name == "get_file_url":
                result = await self._get_file_url(arguments)
            else:
                result = f"[ERROR] Unknown tool: {name}"
            return [TextContent(type="text", text=result)]
    
    async def _create_download_url(self, args: dict) -> str:
        import base64
        import mimetypes
        import uuid
        
        file_path_str = args.get("path", "")
        if not file_path_str:
            return "[ERROR] 'path' is required"
        
        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = self.working_dir / file_path
        
        # 安全校验：resolve 后必须在工作目录内，防止路径遍历（../../etc/passwd）
        try:
            resolved = file_path.resolve()
            working_resolved = self.working_dir.resolve()
            try:
                resolved.relative_to(working_resolved)
            except ValueError:
                return f"[ERROR] Access denied: file must be within working directory ({working_resolved})"
        except Exception:
            return "[ERROR] Invalid file path"
        
        if not file_path.exists():
            return f"[ERROR] File not found: {file_path}"
        if not file_path.is_file():
            return f"[ERROR] Not a file: {file_path}"

        size_error = validate_download_file_size(file_path)
        if size_error:
            return size_error
        
        try:
            content = file_path.read_bytes()
        except Exception as e:
            return f"[ERROR] Failed to read file: {e}"
        
        filename = args.get("filename") or file_path.name
        ttl = normalize_download_ttl(args.get("ttl", 3600))
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        token = uuid.uuid4().hex
        
        try:
            r = self._get_redis_client()
            key = f"download:{token}"
            r.hset(key, mapping={
                "content": base64.b64encode(content).decode("ascii"),
                "filename": filename,
                "content_type": content_type,
            })
            r.expire(key, ttl)
        except Exception as e:
            return f"[ERROR] Redis error: {e}"
        
        base_url = os.getenv("DOWNLOAD_BASE_URL", "/api/download")
        url = f"{base_url}/{token}"
        
        return (
            f"Download URL created:\n"
            f"  URL: {url}\n"
            f"  File: {filename}\n"
            f"  Resolved Path: {resolved}\n"
            f"  Working Dir: {working_resolved}\n"
            f"  Type: {content_type}\n"
            f"  Size: {len(content)} bytes\n"
            f"  Expires in: {ttl}s"
        )
    
    async def _get_file_url(self, args: dict) -> str:
        file_id = args.get("file_id", "").strip()
        if not file_id:
            return "[ERROR] 'file_id' is required"

        from agentclaw.database.file_storage import get_file_storage

        file_storage = get_file_storage()
        if not file_storage:
            return "[ERROR] FileStorage 未初始化"

        stored = await file_storage.find_by_id(file_id)
        if not stored:
            return f"[ERROR] 文件不存在: {file_id}"

        from agentclaw.api.files.signing import get_signed_file_url

        url = get_signed_file_url(file_id)
        return (
            f"File URL:\n"
            f"  URL: {url}\n"
            f"  File: {stored.original_name}\n"
            f"  Type: {stored.mime_type}\n"
            f"  Size: {stored.size} bytes"
        )

    async def run(self):
        logger.info(f"[download-tools] Starting MCP server (stdio)")
        logger.info(f"[download-tools] Working dir: {self.working_dir}")
        
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )
