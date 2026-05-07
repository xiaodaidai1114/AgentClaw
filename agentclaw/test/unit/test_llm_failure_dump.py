from pathlib import Path

import pytest

from agentclaw.model import manager as manager_module


pytestmark = pytest.mark.unit


def test_llm_failure_payload_dump_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD", raising=False)
    monkeypatch.setenv("AGENTCLAW_LLM_FAILURE_DUMP_DIR", str(tmp_path))

    dumped = manager_module._maybe_dump_llm_failure_payload(
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_headers": {"Authorization": "Bearer secret-token"},
        },
        model_id="model-1",
        channel="openai",
    )

    assert dumped is None
    assert list(tmp_path.iterdir()) == []


def test_llm_failure_payload_dump_requires_opt_in_and_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD", "1")
    monkeypatch.setenv("AGENTCLAW_LLM_FAILURE_DUMP_DIR", str(tmp_path))

    dumped = manager_module._maybe_dump_llm_failure_payload(
        {
            "model": "test-model",
            "api_key": "sk-secret",
            "extra_headers": {"Authorization": "Bearer secret-token", "X-Trace": "trace-1"},
            "extra_body": {"password": "plain", "safe": "ok"},
        },
        model_id="model-1",
        channel="openai",
    )

    assert dumped is not None
    dump_path = Path(dumped)
    assert dump_path.exists()
    assert dump_path.parent == tmp_path
    assert dump_path.stat().st_mode & 0o777 == 0o600
    payload = dump_path.read_text(encoding="utf-8")
    assert "sk-secret" not in payload
    assert "secret-token" not in payload
    assert "plain" not in payload
    assert '"api_key": "***REDACTED***"' in payload
    assert '"Authorization": "***REDACTED***"' in payload
    assert '"password": "***REDACTED***"' in payload
    assert '"safe": "ok"' in payload
