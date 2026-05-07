"""Tests for Windows UI element inspection in computer-tools."""

from __future__ import annotations

import json
from importlib import import_module
from types import SimpleNamespace

import pytest

from agentclaw.model.manager import LLMResponse
from agentclaw.mcp.builtin_servers.computer_tools import ComputerToolsServer
from agentclaw.node.llm import LLMNode
from agentclaw.graph.context import WorkflowContext

llm_module = import_module("agentclaw.node.llm")


def _tool_names(server: ComputerToolsServer) -> set[str]:
    return {tool.name for tool in server._build_tools()}


def test_windows_elements_tool_is_registered_only_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    linux_server = ComputerToolsServer()
    assert "get_windows_elements" not in _tool_names(linux_server)

    monkeypatch.setattr("sys.platform", "win32")
    windows_server = ComputerToolsServer()
    tools = {tool.name: tool for tool in windows_server._build_tools()}

    tool = tools["get_windows_elements"]
    assert "pywinauto" in tool.description.lower()
    assert "operating system" in tool.description.lower()
    assert tool.inputSchema["properties"]["max_depth"]["default"] == 3
    assert tool.inputSchema["properties"]["max_windows"]["default"] == 20


@pytest.mark.asyncio
async def test_windows_elements_returns_clear_error_on_non_windows() -> None:
    server = ComputerToolsServer()
    server._platform = "linux"

    result = await server._get_windows_elements({})

    assert result.startswith("[ERROR]")
    assert "Windows only" in result


class _FakeRect:
    left = 10
    top = 20
    right = 210
    bottom = 120


class _FakeControl:
    def __init__(self, title: str, *, children: list["_FakeControl"] | None = None):
        self._title = title
        self._children = children or []
        self.element_info = SimpleNamespace(
            automation_id=f"auto-{title}",
            control_id=7,
            class_name="FakeClass",
            handle=1234,
            name=title,
            process_id=4321,
        )

    def window_text(self) -> str:
        return self._title

    def friendly_class_name(self) -> str:
        return "FakeFriendlyClass"

    def rectangle(self) -> _FakeRect:
        return _FakeRect()

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def children(self) -> list["_FakeControl"]:
        return self._children


class _FakeDesktop:
    def __init__(self, backend: str):
        self.backend = backend

    def windows(self, visible_only: bool = True) -> list[_FakeControl]:
        return [
            _FakeControl(
                "Main Window",
                children=[
                    _FakeControl("OK"),
                    _FakeControl("Cancel"),
                ],
            ),
            _FakeControl("Second Window"),
        ]


@pytest.mark.asyncio
async def test_windows_elements_collects_pywinauto_tree_and_respects_limits(monkeypatch) -> None:
    server = ComputerToolsServer()
    server._platform = "win32"
    monkeypatch.setattr(server, "_load_pywinauto_desktop", lambda: _FakeDesktop)

    result = await server._get_windows_elements(
        {
            "backend": "uia",
            "max_depth": 2,
            "max_windows": 1,
            "include_children": True,
        }
    )
    payload = json.loads(result)

    assert payload["status"] == "success"
    assert payload["platform"] == "win32"
    assert payload["backend"] == "uia"
    assert payload["window_count"] == 1
    assert payload["truncated"] is True
    assert payload["windows"][0]["title"] == "Main Window"
    assert payload["windows"][0]["children"][0]["title"] == "OK"
    assert payload["windows"][0]["rectangle"] == {
        "left": 10,
        "top": 20,
        "right": 210,
        "bottom": 120,
        "width": 200,
        "height": 100,
    }


def test_screenshot_vision_client_uses_first_vision_model_when_top_level_vision_missing(tmp_path, monkeypatch) -> None:
    models_config = tmp_path / "models.json"
    models_config.write_text(
        json.dumps(
            {
                "default": "chat",
                "models": [
                    {
                        "id": "chat",
                        "model": "chat-model",
                        "api_key": "chat-key",
                        "base_url": "https://chat.example/v1",
                        "type": "chat",
                    },
                    {
                        "id": "vision-model",
                        "model": "vl-model",
                        "api_key": "vision-key",
                        "base_url": "https://vision.example/v1",
                        "type": "vision",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    created = {}

    class _FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None):
            created["api_key"] = api_key
            created["base_url"] = base_url
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: None))

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    server = ComputerToolsServer(working_dir=str(tmp_path), models_config=str(models_config))

    client = server._get_vl_client()

    assert client is not None
    assert client["model"] == "vl-model"
    assert created == {"api_key": "vision-key", "base_url": "https://vision.example/v1"}


class _FakeLLMManager:
    async def invoke(self, messages, **kwargs):
        return LLMResponse(content="ok")


@pytest.mark.asyncio
async def test_llmnode_passes_models_config_to_computer_tools(monkeypatch, tmp_path) -> None:
    models_config = str((tmp_path / "models.json").resolve())
    captured = {}

    def fake_runtime_paths(**_kwargs):
        return SimpleNamespace(
            skills_dir=None,
            skill_tools_working_dir=str(tmp_path),
            coding_tools_project_dir=str(tmp_path),
            models_config=models_config,
        )

    def fake_get_builtin_server_config(server_name, **kwargs):
        if server_name == "computer-tools":
            captured["computer_kwargs"] = kwargs
        return {
            "command": "python",
            "args": ["-m", "fake"],
            "env": {},
            "disabled": True,
        }

    class _FakeMCPManager:
        def get_tools_schema(self):
            return []

    async def fake_get_or_create(self, *, cache_key, server_name, server_config):
        return _FakeMCPManager()

    monkeypatch.setattr(llm_module, "resolve_runtime_path_context", fake_runtime_paths)
    monkeypatch.setattr("agentclaw.mcp.builtin_servers.registry.get_builtin_server_config", fake_get_builtin_server_config)
    monkeypatch.setattr("agentclaw.mcp.builtin_servers.get_builtin_server_config", fake_get_builtin_server_config)
    monkeypatch.setattr(LLMNode, "_get_or_create_builtin_mcp_manager", fake_get_or_create)
    monkeypatch.setattr("sys.platform", "win32")

    node = LLMNode(
        id="agent",
        system_prompt="system",
        user_prompt="{user_input}",
        agent_style="standard",
        enable_builtin_tools=True,
        output_to_user=False,
        stream=False,
        save_to_context=False,
    )
    context = WorkflowContext(
        llm_manager=_FakeLLMManager(),
        user_input_field="user_input",
        workflow_id="wf",
    )

    await node._do_execute({"user_input": "hello"}, context)

    assert captured["computer_kwargs"]["working_dir"] == str(tmp_path)
    assert captured["computer_kwargs"]["models_config"] == models_config
