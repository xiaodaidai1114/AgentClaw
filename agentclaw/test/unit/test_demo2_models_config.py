import json
from pathlib import Path


def test_demo2_models_config_does_not_point_fast_or_fallback_to_deprecated_grok():
    config = json.loads(Path("demo2/models.json").read_text(encoding="utf-8"))

    assert config.get("fallback") != "grok-4.1-fast"
    assert config.get("fast") != "grok-4.1-fast"
    assert all(model.get("id") != "grok-4.1-fast" for model in config.get("models", []))
