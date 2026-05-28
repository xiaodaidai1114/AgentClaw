from pathlib import Path

import pytest

from agentclaw.env_config import (
    build_data_dir_env_vars,
    render_env_file,
    visible_env_var_names,
)


pytestmark = pytest.mark.unit


def test_render_env_file_uncomments_user_overrides():
    content = render_env_file(
        {
            "PORT": "9000",
            "ADMIN_TOKEN": "adm-test-token",
            "AGENTCLAW_FILE_LOCK_TIMEOUT": "9",
        }
    )

    assert "PORT=9000" in content
    assert "ADMIN_TOKEN=adm-test-token" in content
    assert "AGENTCLAW_FILE_LOCK_TIMEOUT=9" in content
    assert "# ADMIN_TOKEN=adm-test-token" not in content


def test_render_env_file_keeps_hidden_values_out_without_override():
    content = render_env_file()

    assert "AGENTCLAW_FILE_LOCK_TIMEOUT" not in content
    assert "AgentClaw_SERVER_BASE_URL" not in content
    assert "OPENAI_API_KEY=" not in content
    assert "ANTHROPIC_API_KEY=" not in content


def test_visible_env_var_names_include_public_security_limits():
    names = visible_env_var_names()

    assert "AGENTCLAW_MAX_REQUEST_BODY_BYTES" in names
    assert "AGENTCLAW_ENABLE_ADMIN_API" in names
    assert "AGENTCLAW_ENABLE_DASHBOARD" in names
    assert "AGENTCLAW_ENABLE_API_DOCS" in names
    assert "AGENTCLAW_PUBLIC_AUDIO_ALLOWED_MIME_TYPES" in names
    assert "AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT" in names
    assert "AGENTCLAW_PUBLIC_MAX_INPUT_BYTES" in names
    assert "AGENTCLAW_PUBLIC_MAX_MESSAGE_LENGTH" in names
    assert "AGENTCLAW_PUBLIC_TOOL_POLICY" in names
    assert "AGENTCLAW_PUBLIC_RATE_LIMIT_BACKEND" in names
    assert "AGENTCLAW_PUBLIC_USER_TTL_SECONDS" in names
    assert "DOWNLOAD_MAX_FILE_SIZE_MB" in names
    assert "DOWNLOAD_MAX_TTL_SECONDS" in names


def test_build_data_dir_env_vars_resolves_relative_paths(tmp_path: Path):
    env_vars = build_data_dir_env_vars(".agentclaw-data", project_dir=tmp_path)
    root = (tmp_path / ".agentclaw-data").resolve()

    assert env_vars["AGENTCLAW_DATA_DIR"] == str(root)
    assert env_vars["AGENTCLAW_LOG_FILE"] == str(root / "logs" / "agentclaw.log")
    assert "AGENTCLAW_FEISHU_LOG_FILE" not in env_vars
    assert env_vars["UPLOAD_DIR"] == str(root / "storage")
    assert env_vars["KNOWLEDGEBASE_STORAGE_DIR"] == str(root / "knowledgebase")
    assert env_vars["AGENTCLAW_DOCKER_STORAGE_TYPE"] == "bind"
    assert env_vars["AGENTCLAW_DOCKER_PGDATA_DIR"] == str(root / "docker" / "postgres")
