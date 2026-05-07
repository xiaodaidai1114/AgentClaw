import os
from pathlib import Path

import pytest

from agentclaw.mcp.token_manager import MCPTokenManager


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_mcp_token_manager(monkeypatch):
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    monkeypatch.delenv("AGENTCLAW_PROJECT_DIR", raising=False)
    MCPTokenManager._instance = None
    yield
    MCPTokenManager._instance = None


def test_generated_mcp_token_is_persisted_to_project_env(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8000\n# MCP_TOKEN=your-mcp-token\n", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("agentclaw.mcp.token_manager.secrets.token_urlsafe", lambda _size: "generated-token")

    token = MCPTokenManager.get_instance().token

    assert token == "mcp-generated-token"
    assert "MCP_TOKEN=mcp-generated-token" in env_file.read_text(encoding="utf-8")
    assert os.environ["MCP_TOKEN"] == "mcp-generated-token"


def test_mcp_token_manager_reuses_project_env_token_when_env_not_loaded(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MCP_TOKEN=mcp-existing-token\n", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))

    token = MCPTokenManager.get_instance().token

    assert token == "mcp-existing-token"
    assert env_file.read_text(encoding="utf-8") == "MCP_TOKEN=mcp-existing-token\n"


def test_placeholder_mcp_token_env_is_treated_as_missing(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MCP_TOKEN=your-mcp-token\n", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_TOKEN", "your-mcp-token")
    monkeypatch.setattr("agentclaw.mcp.token_manager.secrets.token_urlsafe", lambda _size: "real-token")

    token = MCPTokenManager.get_instance().token

    assert token == "mcp-real-token"
    assert os.environ["MCP_TOKEN"] == "mcp-real-token"
    assert env_file.read_text(encoding="utf-8") == "MCP_TOKEN=mcp-real-token\n"
