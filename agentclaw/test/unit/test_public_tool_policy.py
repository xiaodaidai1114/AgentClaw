from __future__ import annotations

import pytest


pytestmark = pytest.mark.unit


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_public_tool_policy_defaults_to_allow(monkeypatch):
    from agentclaw.node.llm import apply_public_tool_policy

    monkeypatch.delenv("AGENTCLAW_PUBLIC_TOOL_POLICY", raising=False)

    schemas = [_schema("local_tool"), _schema("shell")]
    filtered = apply_public_tool_policy(
        schemas,
        public_mode=True,
        builtin_tool_names={"shell"},
    )

    assert filtered == schemas


def test_public_tool_policy_can_block_builtin_tools(monkeypatch):
    from agentclaw.node.llm import apply_public_tool_policy

    monkeypatch.setenv("AGENTCLAW_PUBLIC_TOOL_POLICY", "block_builtin")

    filtered = apply_public_tool_policy(
        [_schema("local_tool"), _schema("shell"), _schema("browser_navigate")],
        public_mode=True,
        builtin_tool_names={"shell", "browser_navigate"},
    )

    assert [item["function"]["name"] for item in filtered] == ["local_tool"]


def test_public_tool_policy_can_allow_named_builtin_tools(monkeypatch):
    from agentclaw.node.llm import apply_public_tool_policy

    monkeypatch.setenv("AGENTCLAW_PUBLIC_TOOL_POLICY", "block_builtin")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_ALLOWED_BUILTIN_TOOLS", "search_web")

    filtered = apply_public_tool_policy(
        [_schema("local_tool"), _schema("shell"), _schema("search_web")],
        public_mode=True,
        builtin_tool_names={"shell", "search_web"},
    )

    assert [item["function"]["name"] for item in filtered] == ["local_tool", "search_web"]


def test_public_tool_policy_can_block_all_tools(monkeypatch):
    from agentclaw.node.llm import apply_public_tool_policy

    monkeypatch.setenv("AGENTCLAW_PUBLIC_TOOL_POLICY", "block_all")

    filtered = apply_public_tool_policy(
        [_schema("local_tool"), _schema("shell")],
        public_mode=True,
        builtin_tool_names={"shell"},
    )

    assert filtered == []


def test_public_tool_policy_does_not_affect_admin_context(monkeypatch):
    from agentclaw.node.llm import apply_public_tool_policy

    monkeypatch.setenv("AGENTCLAW_PUBLIC_TOOL_POLICY", "block_all")
    schemas = [_schema("local_tool"), _schema("shell")]

    filtered = apply_public_tool_policy(
        schemas,
        public_mode=False,
        builtin_tool_names={"shell"},
    )

    assert filtered == schemas
