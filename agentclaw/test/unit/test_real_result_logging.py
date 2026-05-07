from agentclaw.test.real.test_real_environment_api import _sanitize_for_log


def test_real_result_log_sanitizes_secret_fields_without_hiding_token_counts():
    payload = {
        "admin_token": "secret-admin-token",
        "nested": {
            "api_key": "secret-api-key",
            "password": "secret-password",
            "prompt_tokens": 73,
            "completion_tokens": 20,
            "total_tokens": 93,
            "max_tokens": 64,
        },
    }

    sanitized = _sanitize_for_log(payload)

    assert sanitized["admin_token"] == "***"
    assert sanitized["nested"]["api_key"] == "***"
    assert sanitized["nested"]["password"] == "***"
    assert sanitized["nested"]["prompt_tokens"] == 73
    assert sanitized["nested"]["completion_tokens"] == 20
    assert sanitized["nested"]["total_tokens"] == 93
    assert sanitized["nested"]["max_tokens"] == 64


def test_real_result_log_truncates_long_strings():
    payload = {"completion": "x" * 9000}

    sanitized = _sanitize_for_log(payload)

    assert len(sanitized["completion"]) < 8050
    assert sanitized["completion"].endswith("...<truncated>")
