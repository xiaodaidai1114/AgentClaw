from __future__ import annotations

import json

from agentclaw.api.services.settings_service import SettingsService
from agentclaw.config import AgentClawConfig, ProjectConfig


def _service(tmp_path):
    AgentClawConfig._instance = AgentClawConfig(
        project=ProjectConfig(project_dir=tmp_path),
    )
    return SettingsService()


def test_maintenance_settings_default_to_permanent_retention(tmp_path):
    service = _service(tmp_path)

    payload = service.get_maintenance()

    assert payload == {
        "log_retention_days": 0,
        "checkpointer_retention_days": 0,
    }


def test_maintenance_settings_persist_independent_log_and_checkpointer_retention(tmp_path):
    service = _service(tmp_path)

    payload = service.update_maintenance(
        {
            "log_retention_days": 7,
            "checkpointer_retention_days": 30,
        }
    )

    assert payload["log_retention_days"] == 7
    assert payload["checkpointer_retention_days"] == 30
    saved = json.loads((tmp_path / ".agentclaw" / "settings.maintenance.json").read_text(encoding="utf-8"))
    assert saved == {
        "log_retention_days": 7,
        "checkpointer_retention_days": 30,
    }
    assert service._config.maintenance.log_retention_days == 7
    assert service._config.maintenance.checkpointer_retention_days == 30


def test_maintenance_settings_normalize_invalid_values_to_zero(tmp_path):
    service = _service(tmp_path)

    payload = service.update_maintenance(
        {
            "log_retention_days": -1,
            "checkpointer_retention_days": "bad",
        }
    )

    assert payload == {
        "log_retention_days": 0,
        "checkpointer_retention_days": 0,
    }
