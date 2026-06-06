from agentclaw.api.services.safety_guard_service import DEFAULT_SAFE_GUARD_PROMPT


def test_default_safety_guard_prompt_is_concise_and_fixed():
    assert "Describe what oss-safeguard should do" not in DEFAULT_SAFE_GUARD_PROMPT
    assert "Clarify key terms and context" not in DEFAULT_SAFE_GUARD_PROMPT
    assert "Describe behaviors or content" not in DEFAULT_SAFE_GUARD_PROMPT
    assert "Be permissive" in DEFAULT_SAFE_GUARD_PROMPT
    assert "clear, direct, actionable" in DEFAULT_SAFE_GUARD_PROMPT
    assert "Ambiguous" in DEFAULT_SAFE_GUARD_PROMPT
    assert "roleplay" in DEFAULT_SAFE_GUARD_PROMPT
    assert "{RULES}" in DEFAULT_SAFE_GUARD_PROMPT
    assert "{INPUT}" in DEFAULT_SAFE_GUARD_PROMPT
    assert DEFAULT_SAFE_GUARD_PROMPT.rstrip().endswith("Answer (0 or 1):")
    assert len(DEFAULT_SAFE_GUARD_PROMPT) < 900
