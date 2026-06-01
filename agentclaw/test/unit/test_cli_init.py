from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from agentclaw import cli


pytestmark = pytest.mark.unit


def test_init_project_copies_docker_compose(tmp_path: Path):
    cli._init_project(tmp_path, silent=True)

    compose_path = tmp_path / "docker-compose.yml"
    bundled_compose = (Path(cli.__file__).parent / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose_path.exists()
    assert compose_path.read_text(encoding="utf-8") == bundled_compose


def test_init_project_does_not_overwrite_existing_docker_compose(tmp_path: Path):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("name: custom\n", encoding="utf-8")

    cli._init_project(tmp_path, silent=True)

    assert compose_path.read_text(encoding="utf-8") == "name: custom\n"


def test_up_project_initialization_can_defer_env_creation_for_runtime_secret_prompt(tmp_path: Path, monkeypatch):
    cli._init_project(tmp_path, silent=True, create_env=False)

    assert not (tmp_path / ".env").exists()

    answers = iter(["admin-custom", "workflow-custom", "mcp-custom"])
    monkeypatch.setattr(cli.click, "prompt", lambda *args, **kwargs: next(answers))

    env_vars = cli._prompt_runtime_secrets(tmp_path)

    assert env_vars == {
        "ADMIN_TOKEN": "admin-custom",
        "WORKFLOW_API_KEY": "workflow-custom",
        "MCP_TOKEN": "mcp-custom",
    }


def test_default_env_content_keeps_template_defaults_with_runtime_overrides():
    content = cli._build_default_env_content(
        overrides={
            "ADMIN_TOKEN": "admin-custom",
            "WORKFLOW_API_KEY": "workflow-custom",
            "MCP_TOKEN": "mcp-custom",
            "PG_HOST": "127.0.0.1",
            "ADMINER_PORT": "18080",
        }
    )

    assert "ADMIN_TOKEN=admin-custom" in content
    assert "WORKFLOW_API_KEY=workflow-custom" in content
    assert "MCP_TOKEN=mcp-custom" in content
    assert "PG_HOST=127.0.0.1" in content
    assert "ADMINER_PORT=18080" in content
    assert "WORKFLOW_TIMEOUT=300" in content
    assert "# AgentClaw 环境配置" in content


def test_docker_daemon_permission_error_is_reported(monkeypatch):
    def fake_run(command, **kwargs):
        assert command == ["docker", "ps"]
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="permission denied while trying to connect to the docker API at unix:///var/run/docker.sock",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    ok, message = cli._docker_daemon_accessible()

    assert ok is False
    assert "当前用户无法访问 Docker daemon" in message
    assert "usermod -aG docker" in message
    assert "不建议使用 sudo agentclaw up" in message


def test_up_reports_docker_daemon_error_before_compose(tmp_path: Path, monkeypatch):
    (tmp_path / "server.py").write_text("workflow = None\n", encoding="utf-8")

    monkeypatch.setattr(cli, "_prompt_data_dir_env_vars", lambda project_path, mode: {})
    monkeypatch.setattr(cli, "_docker_available", lambda: True)
    monkeypatch.setattr(
        cli,
        "_docker_daemon_accessible",
        lambda: (False, "当前用户无法访问 Docker daemon。请将当前用户加入 docker 组后重新登录。"),
    )
    monkeypatch.setattr(cli, "_start_infra", lambda *args, **kwargs: pytest.fail("should not start compose"))
    monkeypatch.setattr(cli, "_start_agentclaw_server", lambda *args, **kwargs: pytest.fail("should not start server"))

    result = CliRunner().invoke(
        cli.cli,
        ["up", "--mode", "docker", "--vector-backend", "milvus", "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Docker daemon 不可访问" in result.output
    assert "当前用户无法访问 Docker daemon" in result.output
