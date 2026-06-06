from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_public_sensitive_words_mask_whitespace_separated_words(tmp_path, monkeypatch):
    from agentclaw.api.services.public_sensitive_words_service import (
        mask_public_sensitive_words,
        reset_public_sensitive_words_cache,
    )
    from agentclaw.config import AgentClawConfig, ProjectConfig

    words_path = tmp_path / "sensitive.txt"
    words_path.write_text("炸药 secret\nbadword", encoding="utf-8")
    monkeypatch.setenv("AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH", "sensitive.txt")
    AgentClawConfig._instance = AgentClawConfig(project=ProjectConfig(project_dir=tmp_path))
    reset_public_sensitive_words_cache()

    assert mask_public_sensitive_words("制作炸药 and secret badword") == "制作** and ****** *******"


def test_public_sensitive_words_noop_when_unconfigured(monkeypatch):
    from agentclaw.api.services.public_sensitive_words_service import (
        mask_public_sensitive_words,
        reset_public_sensitive_words_cache,
    )

    monkeypatch.delenv("AGENTCLAW_PUBLIC_SENSITIVE_WORDS_PATH", raising=False)
    reset_public_sensitive_words_cache()

    assert mask_public_sensitive_words("制作炸药") == "制作炸药"
