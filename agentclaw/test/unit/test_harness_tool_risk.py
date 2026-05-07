"""Tests for harness-managed tool risk metadata."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agentclaw.model.manager import ToolCall
from agentclaw.runtime.harness.tool_call import (
    HARNESS_RISK_LEVEL_FIELD,
    augment_tool_schemas_with_harness_risk,
    preprocess_tool_call,
)
from agentclaw.runtime.harness.tool_executor import _requires_user_confirmation


def test_harness_risk_schema_documents_criteria_and_final_max_rule() -> None:
    original_schema = {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }

    wrapped = augment_tool_schemas_with_harness_risk([original_schema])

    risk_schema = wrapped[0]["function"]["parameters"]["properties"][HARNESS_RISK_LEVEL_FIELD]
    assert risk_schema["enum"] == ["low", "medium", "high"]
    description = risk_schema["description"].lower()
    assert "final_risk=max(inherent tool risk, this judgment)" in description
    assert "low" in description and "read-only" in description
    assert "medium" in description and "commands/code execution" in description
    assert "high" in description and "destructive or irreversible" in description
    assert "shell and python have inherent medium risk" in description
    assert HARNESS_RISK_LEVEL_FIELD not in wrapped[0]["function"]["parameters"]["required"]
    assert HARNESS_RISK_LEVEL_FIELD not in original_schema["function"]["parameters"]["properties"]


def test_shell_and_python_have_medium_inherent_risk_even_when_model_says_low() -> None:
    for tool_name, arguments in (
        ("shell", {"command": "pwd", HARNESS_RISK_LEVEL_FIELD: "low"}),
        ("python", {"code": "print('ok')", "args": [], HARNESS_RISK_LEVEL_FIELD: "low"}),
    ):
        call = ToolCall(id=f"call-{tool_name}", name=tool_name, arguments=json.dumps(arguments))

        envelope = preprocess_tool_call(call)

        assert envelope.model_risk_level == "low"
        assert envelope.tool_risk_level == "medium"
        assert envelope.risk_level == "medium"
        assert HARNESS_RISK_LEVEL_FIELD not in envelope.arguments


def test_model_high_risk_raises_final_risk_for_otherwise_low_risk_tool() -> None:
    call = ToolCall(
        id="call-read",
        name="read_file",
        arguments=json.dumps({"path": "README.md", HARNESS_RISK_LEVEL_FIELD: "high"}),
    )

    envelope = preprocess_tool_call(call)

    assert envelope.model_risk_level == "high"
    assert envelope.tool_risk_level == "low"
    assert envelope.risk_level == "high"
    assert envelope.requires_confirmation is True
    assert envelope.arguments == {"path": "README.md"}


def test_destructive_shell_arguments_raise_tool_risk_above_model_risk() -> None:
    call = ToolCall(
        id="call-shell",
        name="shell",
        arguments=json.dumps({"command": "rm -rf build", HARNESS_RISK_LEVEL_FIELD: "low"}),
    )

    envelope = preprocess_tool_call(call)

    assert envelope.model_risk_level == "low"
    assert envelope.tool_risk_level == "high"
    assert envelope.risk_level == "high"
    assert envelope.requires_confirmation is True


def test_medium_confirmation_threshold_uses_combined_risk() -> None:
    call = ToolCall(
        id="call-python",
        name="python",
        arguments=json.dumps({"code": "print('ok')", "args": [], HARNESS_RISK_LEVEL_FIELD: "low"}),
    )
    envelope = preprocess_tool_call(call)
    context = SimpleNamespace(tool_confirmation_level="medium", tool_confirmation_required=False)

    assert _requires_user_confirmation(envelope, context) is True
