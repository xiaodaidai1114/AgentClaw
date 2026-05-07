"""
MCP 配置模块

支持三种传输方式：
- stdio: 本地进程通信（npx/uvx）
- sse: Server-Sent Events
- streamable_http: HTTP Streamable
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class TransportType(str, Enum):
    """MCP 传输类型"""
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


@dataclass
class MCPServerConfig:
    """
    单个 MCP Server 配置
    
    支持三种传输方式：
    
    1. stdio（本地进程）:
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    
    2. sse（HTTP SSE）:
        {
            "transport": "sse",
            "url": "http://localhost:3000/sse"
        }
    
    3. streamable_http（HTTP Streamable）:
        {
            "transport": "streamable_http",
            "url": "http://localhost:3000/mcp"
        }
    """
    name: str
    transport: TransportType = TransportType.STDIO
    transport_auto: bool = False
    
    # stdio 配置
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    
    # HTTP 配置（sse / streamable_http）
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    sse_read_timeout: float = 300.0
    
    disabled: bool = False
    
    @classmethod
    def from_dict(cls, name: str, data: dict) -> MCPServerConfig:
        """从字典创建配置"""
        # 自动检测传输类型
        transport_value = data.get("transport")
        transport_auto = transport_value is None and "url" in data
        transport_str = transport_value or "stdio"
        if transport_auto:
            # URL 配置未显式指定 transport 时，先走 SSE，再回退到 streamable_http
            transport_str = "sse"
        
        transport = TransportType(transport_str)
        
        return cls(
            name=name,
            transport=transport,
            transport_auto=transport_auto,
            # stdio
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            # http
            url=data.get("url"),
            headers=data.get("headers", {}),
            timeout=data.get("timeout", 30.0),
            sse_read_timeout=data.get("sse_read_timeout", 300.0),
            disabled=data.get("disabled", False),
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        result = {"disabled": self.disabled}
        
        if self.transport == TransportType.STDIO:
            result["command"] = self.command
            result["args"] = self.args
            if self.env:
                result["env"] = self.env
        else:
            if not self.transport_auto:
                result["transport"] = self.transport.value
            result["url"] = self.url
            if self.headers:
                result["headers"] = self.headers
            if self.timeout != 30.0:
                result["timeout"] = self.timeout
            if self.sse_read_timeout != 300.0:
                result["sse_read_timeout"] = self.sse_read_timeout
        
        return result


@dataclass
class MCPConfig:
    """MCP 配置管理"""
    servers: Dict[str, MCPServerConfig] = field(default_factory=dict)
    
    @classmethod
    def from_file(cls, path: str | Path) -> MCPConfig:
        """从 JSON 文件加载配置"""
        path = Path(path)
        if not path.exists():
            logger.warning(f"MCP 配置文件不存在: {path}")
            return cls()
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error(f"MCP 配置文件格式错误: {e}")
            return cls()
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")
            return cls()
    
    @classmethod
    def from_dict(cls, data: dict) -> MCPConfig:
        """从字典创建配置"""
        servers = {}
        mcp_servers = data.get("mcpServers", {})
        
        for name, server_data in mcp_servers.items():
            servers[name] = MCPServerConfig.from_dict(name, server_data)
        
        return cls(servers=servers)
    
    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """获取所有启用的 Server"""
        return [s for s in self.servers.values() if not s.disabled]
    
    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """获取指定 Server 配置"""
        return self.servers.get(name)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "mcpServers": {
                name: s.to_dict()
                for name, s in self.servers.items()
            }
        }
    
    def save(self, path: str | Path) -> None:
        """保存配置到文件"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"MCP 配置已保存: {path}")


def check_command_available(command: str) -> tuple[bool, str]:
    """
    检查命令是否可用
    
    Returns:
        (是否可用, 错误信息或版本信息)
    """
    import shutil
    import subprocess
    
    # 检查命令是否存在
    if not shutil.which(command):
        install_hints = {
            "npx": "请安装 Node.js: https://nodejs.org/",
            "uvx": "请安装 uv: pip install uv 或 https://docs.astral.sh/uv/getting-started/installation/",
            "node": "请安装 Node.js: https://nodejs.org/",
            "python": "请安装 Python: https://www.python.org/",
        }
        hint = install_hints.get(command, f"请确保 {command} 已安装并在 PATH 中")
        return False, hint
    
    # 尝试获取版本
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = result.stdout.strip() or result.stderr.strip()
        return True, version
    except Exception:
        return True, "版本未知"
