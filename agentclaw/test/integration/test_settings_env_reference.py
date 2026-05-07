from pathlib import Path

import pytest

from agentclaw.api.services.settings_service import get_settings_env_reference
from agentclaw.env_config import render_env_file


pytestmark = pytest.mark.integration


def test_env_reference_matches_rendered_security_limit_variables(tmp_path: Path):
    payload = get_settings_env_reference(tmp_path)
    variables = {
        variable["name"]: variable
        for section in payload["sections"]
        for variable in section["variables"]
    }
    rendered = render_env_file()

    for name in (
        "AGENTCLAW_MAX_REQUEST_BODY_BYTES",
        "DOWNLOAD_MAX_FILE_SIZE_MB",
        "DOWNLOAD_MAX_TTL_SECONDS",
    ):
        assert name in variables
        assert name in rendered

    assert variables["AGENTCLAW_MAX_REQUEST_BODY_BYTES"]["restart_required"] is True


def test_hidden_docker_port_variables_are_restart_scoped(tmp_path: Path):
    from agentclaw.api.services import settings_service

    payload = get_settings_env_reference(tmp_path)
    specs = {
        variable["name"]: variable
        for section in payload["sections"]
        for variable in section["variables"]
    }

    for name in (
        "MINIO_API_PORT",
        "MINIO_CONSOLE_PORT",
        "MILVUS_PORT",
        "MILVUS_HTTP_PORT",
        "ADMINER_PORT",
    ):
        assert settings_service._env_apply_scope(name) == "restart"
        assert name not in specs


def test_env_reference_masks_secret_values_from_project_env(tmp_path: Path, monkeypatch):
    secret = "adm-super-secret"
    (tmp_path / ".env").write_text(
        f"ADMIN_TOKEN={secret}\nWORKFLOW_API_KEY=sk-super-secret\nPORT=8123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_TOKEN", secret)

    payload = get_settings_env_reference(tmp_path)
    variables = {
        variable["name"]: variable
        for section in payload["sections"]
        for variable in section["variables"]
    }

    assert variables["ADMIN_TOKEN"]["value"] == "***"
    assert variables["ADMIN_TOKEN"]["raw_value"] == "***"
    assert variables["WORKFLOW_API_KEY"]["raw_value"] == "***"
    assert variables["PORT"]["raw_value"] == "8123"
    assert secret not in str(payload)
