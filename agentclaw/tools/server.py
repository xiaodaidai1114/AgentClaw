"""
企业工具 MCP Server（stdio）

把 tools/specs/*.yaml 定义的所有异构工具（python/http/cli）暴露为一个
MCP server，供 AgentClaw 的所有 agent 通过 mcp.json 配置自动使用。

mcp.json 配置示例：
{
  "mcpServers": {
    "enterprise-tools": {
      "command": "python",
      "args": ["-m", "agentclaw.tools.server", "--specs-dir", "tools/specs"]
    }
  }
}

启动：python -m agentclaw.tools.server --specs-dir tools/specs
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

from mcp import Tool  # type: ignore
from mcp.server import Server  # type: ignore
from mcp.server.stdio import stdio_server  # type: ignore
from mcp.types import TextContent  # type: ignore

from .executor import ToolExecutor
from .loader import load_specs


def build_server(specs_dir: Path) -> Server:
    """加载 specs 并构建 MCP server"""
    specs = load_specs(specs_dir)
    executor = ToolExecutor(specs)
    server = Server("enterprise-tools")

    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return [s.to_mcp_tool() for s in executor.list_specs()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        result = await executor.execute(name, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="企业工具 MCP server")
    parser.add_argument(
        "--specs-dir",
        default="tools/specs",
        help="工具定义目录（默认 tools/specs）",
    )
    args = parser.parse_args(argv)

    specs_dir = Path(args.specs_dir).resolve()
    if not specs_dir.exists():
        # 找不到目录，stderr 提示但仍启动（空工具集）
        print(f"[enterprise-tools] 警告: specs 目录不存在: {specs_dir}", file=sys.stderr)

    server = build_server(specs_dir)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
