from pathlib import Path

import pytest
from mcp.types import ListToolsRequest

from agentclaw.mcp.builtin_servers.skill_tools import SkillToolsServer


pytestmark = pytest.mark.unit


async def _read_file_tool(server: SkillToolsServer):
    result = await server._server.request_handlers[ListToolsRequest](ListToolsRequest())
    for tool in result.root.tools:
        if tool.name == "read_file":
            return tool
    raise AssertionError("read_file tool not registered")


@pytest.mark.asyncio
async def test_read_file_schema_guides_models_to_use_tool_for_file_inspection(tmp_path: Path):
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    tool = await _read_file_tool(server)

    assert "Preferred tool for reading existing local files" in tool.description
    assert "python" in tool.description.lower()
    assert "shell" in tool.description.lower()
    assert "paths" in tool.inputSchema["properties"]
    assert tool.inputSchema["type"] == "object"
    assert not {"oneOf", "anyOf", "allOf", "enum", "not"} & set(tool.inputSchema)


@pytest.mark.asyncio
async def test_read_file_accepts_multiple_paths_in_one_call(tmp_path: Path):
    (tmp_path / "first.txt").write_text("alpha\nbeta", encoding="utf-8")
    (tmp_path / "second.txt").write_text("gamma", encoding="utf-8")
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    output = await server._read_file({"paths": ["first.txt", "second.txt"]})

    assert "===== first.txt =====" in output
    assert "1| alpha" in output
    assert "2| beta" in output
    assert "===== second.txt =====" in output
    assert "1| gamma" in output


@pytest.mark.asyncio
async def test_read_file_ignores_empty_paths_when_path_is_present(tmp_path: Path):
    (tmp_path / "report.txt").write_text("single path content", encoding="utf-8")
    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    output = await server._read_file(
        {
            "path": "report.txt",
            "paths": [],
            "prompt": "",
            "skill_name": "",
            "line_start": 1,
        }
    )

    assert "[Error] 'paths' must be a non-empty list of file paths" not in output
    assert "1| single path content" in output
