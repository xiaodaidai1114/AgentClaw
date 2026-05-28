import json
from types import SimpleNamespace

from agentclaw.api.services.settings_service import SettingsService
from agentclaw.config import AgentClawConfig, ProjectConfig


class FakeLLMManager:
    def __init__(self):
        self.reloaded_paths = []

    def reload_models_config(self, config_path=None):
        self.reloaded_paths.append(str(config_path))


def _service(tmp_path, manager=None):
    workflow = SimpleNamespace(_llm_manager=manager or FakeLLMManager())

    class Registry:
        @classmethod
        def list_all(cls):
            return [workflow]

    AgentClawConfig._instance = AgentClawConfig(
        project=ProjectConfig(
            project_dir=tmp_path,
            models_config=tmp_path / "models.json",
        )
    )
    return SettingsService(registry=Registry), workflow._llm_manager


def test_settings_models_config_masks_api_keys(tmp_path):
    (tmp_path / "models.json").write_text(
        json.dumps(
            {
                "default": "primary",
                "vision": "vision",
                "models": [
                    {
                        "id": "primary",
                        "channel": "openai",
                        "model": "gpt-4.1",
                        "api_key": "sk-secret",
                        "base_url": "https://api.example/v1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service, _ = _service(tmp_path)

    payload = service.get_models_config()

    assert payload["path"].endswith("models.json")
    assert payload["default"] == "primary"
    assert payload["vision"] == "vision"
    assert payload["models"][0]["api_key"] == "***"
    assert payload["models"][0]["api_key_set"] is True
    assert "sk-secret" not in json.dumps(payload, ensure_ascii=False)


def test_settings_models_config_displays_legacy_vision_type_as_chat_supporting_vision(tmp_path):
    (tmp_path / "models.json").write_text(
        json.dumps(
            {
                "vision": "legacy_vision",
                "models": [
                    {
                        "id": "legacy_vision",
                        "type": "vision",
                        "model": "legacy-vision-model",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service, _ = _service(tmp_path)

    payload = service.get_models_config()

    assert payload["models"][0]["type"] == "chat"
    assert payload["models"][0]["supports_vision"] is True


def test_settings_models_config_rejects_embedding_as_default_model(tmp_path):
    (tmp_path / "models.json").write_text(
        json.dumps({"models": []}),
        encoding="utf-8",
    )
    service, _ = _service(tmp_path)

    try:
        service.update_models_config(
            {
                "default": "embedding",
                "models": [
                    {"id": "embedding", "type": "embedding", "model": "text-embedding-3-large"},
                ],
            }
        )
    except ValueError as exc:
        assert "default" in str(exc)
    else:
        raise AssertionError("embedding default model should be rejected")


def test_settings_models_config_preserves_masked_secret_and_hot_reloads(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "primary",
                "models": [
                    {
                        "id": "primary",
                        "channel": "openai",
                        "model": "old-model",
                        "api_key": "sk-existing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service, manager = _service(tmp_path)

    updated = service.update_models_config(
        {
            "default": "new",
            "fallback": "primary",
            "models": [
                {
                    "id": "primary",
                    "channel": "openai",
                    "model": "new-model",
                    "api_key": "***",
                    "temperature": 0.2,
                },
                {
                    "id": "new",
                    "channel": "anthropic",
                    "model": "claude",
                    "api_key": "sk-new",
                    "type": "chat",
                },
            ],
        }
    )

    raw = json.loads(models_path.read_text(encoding="utf-8"))
    assert raw["default"] == "new"
    assert raw["fallback"] == "primary"
    assert raw["models"][0]["api_key"] == "sk-existing"
    assert raw["models"][0]["model"] == "new-model"
    assert raw["models"][1]["api_key"] == "sk-new"
    assert manager.reloaded_paths == [str(models_path)]
    assert updated["models"][0]["api_key"] == "***"
    assert updated["models"][1]["api_key"] == "***"


def test_settings_models_config_preserves_existing_secret_when_payload_omits_api_key(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "primary",
                "models": [
                    {
                        "id": "primary",
                        "channel": "openai",
                        "model": "old-model",
                        "api_key": "sk-existing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service, _ = _service(tmp_path)

    service.update_models_config(
        {
            "default": "primary",
            "models": [
                {
                    "id": "primary",
                    "channel": "openai",
                    "model": "new-model",
                },
            ],
        }
    )

    raw = json.loads(models_path.read_text(encoding="utf-8"))
    assert raw["models"][0]["api_key"] == "sk-existing"


def test_settings_models_config_preserves_audio_defaults(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(json.dumps({"models": []}), encoding="utf-8")
    service, _ = _service(tmp_path)

    updated = service.update_models_config(
        {
            "default": "chat",
            "speech2text": "asr",
            "tts": "voice",
            "tts_voice": "alloy",
            "models": [
                {"id": "chat", "channel": "openai", "type": "chat", "model": "gpt"},
                {"id": "asr", "channel": "openai", "type": "speech2text", "model": "whisper-1"},
                {"id": "voice", "channel": "openai", "type": "tts", "model": "tts-1", "voice": "alloy"},
            ],
        }
    )

    raw = json.loads(models_path.read_text(encoding="utf-8"))
    assert raw["speech2text"] == "asr"
    assert raw["tts"] == "voice"
    assert raw["tts_voice"] == "alloy"
    assert updated["speech2text"] == "asr"
    assert updated["tts"] == "voice"
    assert updated["tts_voice"] == "alloy"
