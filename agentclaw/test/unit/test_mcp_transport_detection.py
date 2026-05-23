from pathlib import Path
from types import SimpleNamespace

import asyncio
import pytest

from agentclaw.mcp.config import MCPServerConfig
from agentclaw.mcp.config import MCPConfig, TransportType
from agentclaw.mcp.client import MCPClient, MCPTool, _get_mcp_tool_timeout
from agentclaw.mcp.manager import MCPManager


pytestmark = pytest.mark.unit


class FakeMCPClient:
    def __init__(self, config):
        self.name = config.name
        self._connected = False
        self.connected_transport = TransportType.STREAMABLE_HTTP

    @property
    def is_connected(self):
        return self._connected

    async def connect(self, connect_timeout=None):
        self._connected = True

    def list_tools(self):
        return []


class TrackingMCPClient:
    def __init__(self, config, *, delay=0.01):
        self.config = config
        self.name = config.name
        self._connected = True
        self.connected_transport = config.transport
        self.delay = delay
        self.active_calls = 0
        self.max_active_calls = 0
        self._tools = [
            MCPTool(name="search_web", description="", input_schema={}, server_name=config.name),
        ]

    @property
    def is_connected(self):
        return self._connected

    def list_tools(self):
        return self._tools

    def get_tool(self, name):
        return self._tools[0] if name == "search_web" else None

    async def call_tool(self, name, arguments):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(self.delay)
            return "ok"
        finally:
            self.active_calls -= 1


@pytest.mark.asyncio
async def test_manager_records_auto_detected_transport_after_success(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "search": {
              "url": "https://example.com/mcp"
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr("agentclaw.mcp.manager.MCPClient", FakeMCPClient)

    manager = MCPManager(MCPConfig.from_file(config_path))
    await manager.connect("search")

    assert '"transport": "streamable_http"' in config_path.read_text(encoding="utf-8")


def test_mcp_tool_timeout_defaults_to_30_seconds_for_regular_tools(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_MCP_TOOL_TIMEOUT", raising=False)

    assert _get_mcp_tool_timeout("search_web") == 30.0


def test_mcp_tool_timeout_keeps_long_default_for_execution_tools(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_MCP_TOOL_TIMEOUT", raising=False)

    assert _get_mcp_tool_timeout("python") == 120.0
    assert _get_mcp_tool_timeout("shell") == 120.0
    assert _get_mcp_tool_timeout("javascript") == 120.0
    assert _get_mcp_tool_timeout("execute_sudo_command") == 120.0


def test_mcp_tool_timeout_env_overrides_all_tool_defaults(monkeypatch):
    monkeypatch.setenv("AGENTCLAW_MCP_TOOL_TIMEOUT", "7")

    assert _get_mcp_tool_timeout("search_web") == 7.0
    assert _get_mcp_tool_timeout("python") == 7.0


@pytest.mark.asyncio
async def test_mcp_client_disconnects_after_tool_timeout(monkeypatch):
    async def never_returns(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setenv("AGENTCLAW_MCP_TOOL_TIMEOUT", "0.01")
    client = MCPClient(MCPServerConfig(name="search", transport=TransportType.STREAMABLE_HTTP))
    client._connected = True
    client._tools["search_web"] = MCPTool(
        name="search_web",
        description="",
        input_schema={},
        server_name="search",
    )
    client._session = SimpleNamespace(
        call_tool=never_returns,
        __aexit__=lambda *args: None,
    )

    with pytest.raises(TimeoutError):
        await client.call_tool("search_web", {})

    assert client.is_connected is False


@pytest.mark.asyncio
async def test_remote_mcp_server_calls_are_not_serialized_by_manager_lock():
    config = MCPConfig.from_dict({
        "mcpServers": {
            "search": {
                "transport": "streamable_http",
                "url": "https://example.com/mcp",
            }
        }
    })
    manager = MCPManager(config)
    client = TrackingMCPClient(config.get_server("search"))
    manager._clients["search"] = client
    manager._tool_map["search_web"] = "search"
    manager._server_locks["search"] = asyncio.Lock()

    await asyncio.gather(
        manager.call_tool("search_web", {"query": "a"}),
        manager.call_tool("search_web", {"query": "b"}),
    )

    assert client.max_active_calls == 2


@pytest.mark.asyncio
async def test_stdio_mcp_server_calls_remain_serialized_by_manager_lock():
    config = MCPConfig.from_dict({
        "mcpServers": {
            "local": {
                "command": "example-mcp",
            }
        }
    })
    manager = MCPManager(config)
    client = TrackingMCPClient(config.get_server("local"))
    manager._clients["local"] = client
    manager._tool_map["search_web"] = "local"
    manager._server_locks["local"] = asyncio.Lock()

    await asyncio.gather(
        manager.call_tool("search_web", {"query": "a"}),
        manager.call_tool("search_web", {"query": "b"}),
    )

    assert client.max_active_calls == 1
