import json
from pathlib import Path

import pytest

from agentclaw.mcp.builtin_servers.skill_tools import SkillToolsServer
from agentclaw.skills import get_builtin_skills_dir


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_agentclaw_api_skill_read_substitutes_internal_relay_url(tmp_path, monkeypatch):
    public_url = "http://127.0.0.1:8000"
    internal_url = "http://127.0.0.1:45555"
    relay_dir = tmp_path / ".agentclaw"
    relay_dir.mkdir()
    (relay_dir / "relay.json").write_text(
        json.dumps(
            {
                "url": public_url,
                "internal_url": internal_url,
                "project_dir": str(tmp_path.resolve()),
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))

    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    content = await server._read_skill_file(
        {"skill_name": "agentclaw_api", "file_name": "SKILL.md"}
    )

    assert f"{internal_url}/_internal/api/workflow/run" in content
    assert f"{public_url}/_internal/api/workflow/run" not in content


@pytest.mark.asyncio
async def test_agentclaw_api_references_substitute_internal_relay_url(tmp_path, monkeypatch):
    public_url = "http://127.0.0.1:8000"
    internal_url = "http://127.0.0.1:45555"
    relay_dir = tmp_path / ".agentclaw"
    relay_dir.mkdir()
    (relay_dir / "relay.json").write_text(
        json.dumps(
            {
                "url": public_url,
                "internal_url": internal_url,
                "project_dir": str(tmp_path.resolve()),
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))

    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    content = await server._read_skill_file(
        {"skill_name": "agentclaw_api", "file_name": "references/workflow.md"}
    )

    assert f"{internal_url}/_internal" in content
    assert f"{public_url}/_internal" not in content


@pytest.mark.asyncio
async def test_agent_creator_skill_internal_examples_use_internal_relay_url(tmp_path, monkeypatch):
    public_url = "http://127.0.0.1:8000"
    internal_url = "http://127.0.0.1:45555"
    relay_dir = tmp_path / ".agentclaw"
    relay_dir.mkdir()
    (relay_dir / "relay.json").write_text(
        json.dumps(
            {
                "url": public_url,
                "internal_url": internal_url,
                "project_dir": str(tmp_path.resolve()),
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))

    server = SkillToolsServer(working_dir=str(tmp_path), project_dir=str(tmp_path))

    content = await server._read_skill_file(
        {"skill_name": "agent_creator", "file_name": "SKILL.md"}
    )

    assert f"{internal_url}/_internal/api/workflow/run" in content
    assert f"{public_url}/_internal/api/workflow/run" not in content


def test_agentclaw_api_reference_files_name_internal_relay_entrypoint():
    api_skill_dir = get_builtin_skills_dir() / "agentclaw_api"
    references = sorted((api_skill_dir / "references").glob("*.md"))

    assert references
    for reference in references:
        content = reference.read_text(encoding="utf-8")
        assert "本机 internal relay" in content, reference
        assert "`internal_url`" in content, reference
        assert "{BASE_URL}/_internal" in content, reference


def test_user_api_reference_documents_internal_agent_entrypoint():
    docs = [
        Path("agentclaw/docs/zh/api_reference.md"),
        Path("agentclaw/docs/en/api_reference.md"),
    ]

    for doc in docs:
        content = doc.read_text(encoding="utf-8")
        assert ".agentclaw/relay.json" in content, doc
        assert "`internal_url`" in content, doc
        assert "{internal_url}/_internal" in content, doc
