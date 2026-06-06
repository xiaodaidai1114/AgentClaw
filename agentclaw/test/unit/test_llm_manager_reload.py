import json
from datetime import datetime, timedelta

from agentclaw.model.manager import LLMManager


def _write_models(path, default="primary", fallback="backup", fast="quick"):
    path.write_text(
        json.dumps(
            {
                "default": default,
                "fallback": fallback,
                "fast": fast,
                "models": [
                    {"id": "primary", "model": "primary-model"},
                    {"id": "backup", "model": "backup-model"},
                    {"id": "quick", "model": "quick-model"},
                    {"id": "override-default", "model": "override-default-model"},
                    {"id": "override-fallback", "model": "override-fallback-model"},
                    {"id": "override-fast", "model": "override-fast-model"},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_llm_manager_reload_preserves_constructor_model_overrides(tmp_path):
    models_path = tmp_path / "models.json"
    _write_models(models_path)
    manager = LLMManager(
        default="override-default",
        fallback="override-fallback",
        fast="override-fast",
        config_path=str(models_path),
    )

    _write_models(models_path, default="changed-default", fallback="changed-fallback", fast="changed-fast")
    manager.reload_models_config(str(models_path))

    assert manager.default_id == "override-default"
    assert manager.fallback_id == "override-fallback"
    assert manager.fast_id == "override-fast"


def test_llm_manager_uses_supports_vision_flag_for_vision_model(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "chat",
                "models": [
                    {"id": "chat", "type": "chat", "model": "chat-model"},
                    {"id": "vision_chat", "type": "chat", "supports_vision": True, "model": "vision-chat-model"},
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = LLMManager(config_path=str(models_path))

    assert manager.get_vision_model_id() == "vision_chat"
    assert manager.get_model("vision_chat").model_type == "chat"
    assert manager.get_model("vision_chat").supports_vision is True


def test_llm_manager_treats_legacy_vision_type_as_chat_with_vision_support(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "chat",
                "models": [
                    {"id": "legacy_vision", "type": "vision", "model": "legacy-vision-model"},
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = LLMManager(config_path=str(models_path))

    assert manager.get_model("legacy_vision").model_type == "chat"
    assert manager.get_model("legacy_vision").supports_vision is True
    assert manager.get_vision_model_id() == "legacy_vision"


def test_llm_manager_fallback_sequence_skips_non_chat_models(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "primary",
                "models": [
                    {"id": "primary", "type": "chat", "model": "primary-model"},
                    {"id": "embedding", "type": "embedding", "model": "embedding-model"},
                    {"id": "rerank", "type": "rerank", "model": "rerank-model"},
                    {"id": "backup", "type": "chat", "model": "backup-model"},
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = LLMManager(config_path=str(models_path))

    assert manager._get_fallback_model_id("primary") == "backup"
    assert manager._get_fallback_model_id("backup") is None


def test_llm_manager_ignores_active_non_chat_fallback_state(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "primary",
                "fallback": "embedding",
                "models": [
                    {"id": "primary", "type": "chat", "model": "primary-model"},
                    {"id": "embedding", "type": "embedding", "model": "embedding-model"},
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = LLMManager(config_path=str(models_path))
    manager._fallback_state.is_fallback = True
    manager._fallback_state.fallback_until = datetime.now() + timedelta(seconds=60)
    manager._current_model_id = "embedding"

    _client, config = manager._get_current_client()

    assert config.id == "primary"
    assert manager._fallback_state.is_fallback is False


def test_llm_manager_loads_safe_guard_model_and_rules(tmp_path):
    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
                {
                    "default": "primary",
                    "safe_guard": "guard",
                    "safe_guard_rules": "block unsafe content",
                    "models": [
                        {"id": "primary", "type": "chat", "model": "primary-model"},
                    {"id": "guard", "type": "chat", "model": "guard-model"},
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = LLMManager(config_path=str(models_path))

    assert manager.safe_guard_id == "guard"
    assert manager.safe_guard_rules == "block unsafe content"
