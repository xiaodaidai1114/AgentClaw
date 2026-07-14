"""
skill-tools 自动重连 + 长运行工具超时提升的单元测试。

背景：agent 用 shell/python 运行 workflow 做冒烟测试时，阻塞执行超过旧 30s/120s
超时 → MCPClient.disconnect() → _connected=False，此后 call_tool 直接抛"未连接"，
没有自动重连，导致一次超时废掉后续所有 shell/python 调用、agent 卡死。

修复：1) 长运行工具超时 120→240s；2) call_tool 在 _connected=False 时自动 connect() 重连。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# 超时常量
# ------------------------------------------------------------------

def test_long_running_timeout_raised_to_240(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_MCP_TOOL_TIMEOUT", raising=False)
    from agentclaw.mcp.client import (
        _LONG_RUNNING_MCP_TOOL_TIMEOUT,
        _get_mcp_tool_timeout,
    )

    assert _LONG_RUNNING_MCP_TOOL_TIMEOUT == 240.0
    assert _get_mcp_tool_timeout("shell") == 240.0
    assert _get_mcp_tool_timeout("python") == 240.0
    assert _get_mcp_tool_timeout("javascript") == 240.0


def test_default_timeout_still_30_for_short_tools(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_MCP_TOOL_TIMEOUT", raising=False)
    from agentclaw.mcp.client import _get_mcp_tool_timeout

    # 非长运行工具仍保持 30s
    assert _get_mcp_tool_timeout("read_file") == 30.0
    assert _get_mcp_tool_timeout("list_files") == 30.0


def test_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("AGENTCLAW_MCP_TOOL_TIMEOUT", "180")
    from agentclaw.mcp.client import _get_mcp_tool_timeout

    # 环境变量优先级最高
    assert _get_mcp_tool_timeout("shell") == 180.0
    assert _get_mcp_tool_timeout("read_file") == 180.0


# ------------------------------------------------------------------
# 自动重连
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_auto_reconnects_when_disconnected():
    """_connected=False 时 call_tool 自动调 connect 重连后继续执行"""
    from agentclaw.mcp.client import MCPClient

    client = MCPClient.__new__(MCPClient)
    client.name = "skill-tools"
    client._connected = False
    client._tools = {}
    client._connected_transport = None
    client._session = None
    client._transport_context = None

    reconnect_count = 0

    async def fake_connect(*args, **kwargs):
        nonlocal reconnect_count
        reconnect_count += 1
        client._connected = True
        client._tools = {"shell": MagicMock()}

    client.connect = fake_connect

    fake_result = MagicMock()
    fake_result.content = [MagicMock(text="shell output ok")]
    client._session = MagicMock()
    client._session.call_tool = AsyncMock(return_value=fake_result)

    result = await client.call_tool("shell", {"command": "echo hi"})

    assert reconnect_count == 1  # 触发了一次自动重连
    assert "shell output ok" in result


@pytest.mark.asyncio
async def test_call_tool_raises_reconnect_failure_when_connect_fails():
    """connect 重连失败时抛清晰错误，而非让 agent 卡在'未连接'循环"""
    from agentclaw.mcp.client import MCPClient

    client = MCPClient.__new__(MCPClient)
    client.name = "skill-tools"
    client._connected = False
    client._tools = {}
    client._connected_transport = None
    client._session = None
    client._transport_context = None
    client.connect = AsyncMock(side_effect=RuntimeError("spawn subprocess failed"))

    with pytest.raises(RuntimeError, match="自动重连失败"):
        await client.call_tool("shell", {})
