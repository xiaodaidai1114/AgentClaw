"""Tool call preprocessing for harness-managed agentic runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional
import copy
import json
import uuid


ToolRiskLevel = Literal["low", "medium", "high", "critical"]
ToolCallStatus = Literal["pending", "invalid", "running", "succeeded", "failed", "rejected"]

HARNESS_RISK_LEVEL_FIELD = "__harness_risk_level"
HARNESS_RISK_LEVEL_DESCRIPTION = (
    "Model-assessed risk for this specific tool call. "
    "The harness applies final_risk=max(inherent tool risk, this judgment). "
    "Criteria: low=read-only inspection, local listing, pure calculation, or information retrieval with no side effects; "
    "medium=commands/code execution, local file or config changes, package installs, network/API calls, or reversible actions that may affect runtime state; "
    "high=destructive or irreversible operations, broad deletes/overwrites, secret or credential exposure, auth/permission/deployment changes, production/external data mutation, sudo/privilege escalation, external messages/payments, or unclear blast radius. "
    "Shell and Python have inherent medium risk even when the requested command looks read-only."
)
HARNESS_RISK_LEVEL_SCHEMA = {
    "type": "string",
    "enum": ["low", "medium", "high"],
    "default": "low",
    "description": HARNESS_RISK_LEVEL_DESCRIPTION,
}

_RISK_RANK: dict[ToolRiskLevel, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_RISK_ALIASES: dict[str, ToolRiskLevel] = {
    "none": "low",
    "minimal": "low",
    "safe": "low",
    "moderate": "medium",
    "med": "medium",
    "dangerous": "high",
    "destructive": "high",
    "critical": "critical",
}
_INHERENT_TOOL_RISK: dict[str, ToolRiskLevel] = {
    "shell": "medium",
    "python": "medium",
    "javascript": "medium",
}
_HIGH_RISK_TOOL_NAMES = {
    "write_file", "write_code", "update_code", "replace_in_file", "replace_in_files",
    "delete_file", "rename_path", "apply_patch", "install_package", "execute_sudo_command",
}


@dataclass
class ToolCallEnvelope:
    """A model tool-call intent normalized for execution.

    The model supplies only name + arguments (+ provider id when available).
    Harness fills runtime fields such as status, risk, validation errors, and
    confirmation requirements.
    """

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: Any = None
    status: ToolCallStatus = "pending"
    risk_level: ToolRiskLevel = "low"
    tool_risk_level: ToolRiskLevel = "low"
    model_risk_level: ToolRiskLevel = "low"
    requires_confirmation: bool = False
    validation_errors: list[str] = field(default_factory=list)
    source_round: int = 0
    original: Any = None

    @property
    def valid(self) -> bool:
        return self.status != "invalid" and not self.validation_errors

    @property
    def arguments_json(self) -> str:
        return json.dumps(self.arguments, ensure_ascii=False)


def preprocess_tool_call(
    tool_call: Any,
    *,
    source_round: int = 0,
    allowed_tool_names: set[str] | None = None,
    tool_schema: dict[str, Any] | None = None,
) -> ToolCallEnvelope:
    """Normalize and minimally validate a model-produced tool call before execution."""
    call_id = str(getattr(tool_call, "id", "") or "").strip() or f"call-{uuid.uuid4().hex}"
    name = str(getattr(tool_call, "name", "") or "").strip()
    raw_arguments = getattr(tool_call, "arguments", None)
    arguments, errors = _parse_arguments(raw_arguments)
    model_risk_level, arguments = _extract_model_risk_level(arguments)
    tool_risk_level, tool_requires_confirmation = _assess_tool_risk(name, arguments)
    risk_level = max_tool_risk_level(tool_risk_level, model_risk_level)
    requires_confirmation = tool_requires_confirmation or _risk_rank(risk_level) >= _risk_rank("high")
    status: ToolCallStatus = "pending"
    if not name:
        errors.append("Tool name is empty")
    elif allowed_tool_names is not None and name not in allowed_tool_names:
        errors.append(f"Tool '{name}' is not available in this run")
    errors.extend(_validate_required_arguments(arguments, tool_schema))
    if errors:
        status = "invalid"
    return ToolCallEnvelope(
        id=call_id,
        name=name,
        arguments=arguments,
        raw_arguments=raw_arguments,
        status=status,
        risk_level=risk_level,
        tool_risk_level=tool_risk_level,
        model_risk_level=model_risk_level,
        requires_confirmation=requires_confirmation,
        validation_errors=errors,
        source_round=source_round,
        original=tool_call,
    )


def _parse_arguments(raw_arguments: Any) -> tuple[dict[str, Any], list[str]]:
    if raw_arguments is None or raw_arguments == "":
        return {}, []
    if isinstance(raw_arguments, dict):
        return dict(raw_arguments), []
    if isinstance(raw_arguments, str):
        stripped = raw_arguments.strip()
        if not stripped:
            return {}, []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return {}, [f"Tool arguments are not valid JSON: {exc.msg}"]
        if isinstance(parsed, dict):
            return parsed, []
        return {}, ["Tool arguments JSON must be an object"]
    return {}, [f"Tool arguments must be an object or JSON object string, got {type(raw_arguments).__name__}"]


def augment_tool_schemas_with_harness_risk(tool_schemas: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Add harness-only model risk metadata to tool schemas without mutating inputs."""
    if not tool_schemas:
        return tool_schemas

    augmented: list[dict[str, Any]] = []
    for schema in tool_schemas:
        copied = copy.deepcopy(schema)
        if not isinstance(copied, dict):
            augmented.append(copied)
            continue
        function = copied.get("function")
        if not isinstance(function, dict):
            augmented.append(copied)
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}, "required": []}
            function["parameters"] = parameters
        parameters.setdefault("type", "object")
        properties = parameters.get("properties")
        if not isinstance(properties, dict):
            properties = {}
            parameters["properties"] = properties
        required = parameters.get("required")
        if not isinstance(required, list):
            parameters["required"] = []
        else:
            parameters["required"] = [item for item in required if item != HARNESS_RISK_LEVEL_FIELD]
        properties[HARNESS_RISK_LEVEL_FIELD] = copy.deepcopy(HARNESS_RISK_LEVEL_SCHEMA)
        augmented.append(copied)
    return augmented


def normalize_tool_risk_level(value: Any, *, default: ToolRiskLevel = "low") -> ToolRiskLevel:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return default
    if normalized in _RISK_RANK:
        return normalized  # type: ignore[return-value]
    return _RISK_ALIASES.get(normalized, default)


def max_tool_risk_level(*levels: Any) -> ToolRiskLevel:
    normalized_levels = [normalize_tool_risk_level(level) for level in levels if level is not None]
    if not normalized_levels:
        return "low"
    return max(normalized_levels, key=_risk_rank)


def _risk_rank(level: Any) -> int:
    return _RISK_RANK.get(normalize_tool_risk_level(level), _RISK_RANK["low"])


def _extract_model_risk_level(arguments: dict[str, Any]) -> tuple[ToolRiskLevel, dict[str, Any]]:
    cleaned = dict(arguments or {})
    raw_model_risk = cleaned.pop(HARNESS_RISK_LEVEL_FIELD, None)
    return normalize_tool_risk_level(raw_model_risk), cleaned


def _validate_required_arguments(arguments: dict[str, Any], tool_schema: dict[str, Any] | None) -> list[str]:
    if not tool_schema:
        return []
    function = tool_schema.get("function", {}) if isinstance(tool_schema, dict) else {}
    parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
    if not isinstance(parameters, dict):
        return []

    errors: list[str] = []
    required = parameters.get("required", [])
    if isinstance(required, list):
        missing = [str(key) for key in required if str(key) not in arguments]
        if missing:
            errors.append(f"Missing required tool argument(s): {', '.join(missing)}")

    properties = parameters.get("properties", {})
    if isinstance(properties, dict):
        for key, value in arguments.items():
            property_schema = properties.get(key)
            if isinstance(property_schema, dict):
                errors.extend(_validate_argument_schema(key, value, property_schema))
    return errors


def _validate_argument_schema(path: str, value: Any, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        expected_types = [str(item) for item in expected_type]
    elif isinstance(expected_type, str):
        expected_types = [expected_type]
    else:
        expected_types = []

    if expected_types and not any(_matches_json_type(value, expected_type) for expected_type in expected_types):
        errors.append(f"Tool argument '{path}' must be {', '.join(expected_types)}, got {type(value).__name__}")
        return errors

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"Tool argument '{path}' must be one of {enum_values!r}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [str(key) for key in required if str(key) not in value]
            if missing:
                errors.append(f"Missing required tool argument(s) in '{path}': {', '.join(missing)}")
        if isinstance(properties, dict):
            for child_key, child_value in value.items():
                child_schema = properties.get(child_key)
                if isinstance(child_schema, dict):
                    errors.extend(_validate_argument_schema(f"{path}.{child_key}", child_value, child_schema))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_argument_schema(f"{path}[{index}]", item, item_schema))
    return errors


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


def _assess_tool_risk(tool_name: str, arguments: dict[str, Any]) -> tuple[ToolRiskLevel, bool]:
    name = (tool_name or "").strip().lower()
    if name in _HIGH_RISK_TOOL_NAMES:
        return "high", True
    inherent_risk = _INHERENT_TOOL_RISK.get(name, "low")
    if inherent_risk == "medium":
        command_text = " ".join(str(value).lower() for value in arguments.values() if isinstance(value, str))
        destructive_markers = ("rm ", "rm-", "rm -", "sudo", "docker run", "systemctl", "chmod", "chown", "mkfs")
        if any(marker in command_text for marker in destructive_markers):
            return "high", True
    return inherent_risk, False


def _assess_risk(tool_name: str, arguments: dict[str, Any]) -> tuple[ToolRiskLevel, bool]:
    """Backward-compatible wrapper for callers that need final tool-inherent risk."""
    return _assess_tool_risk(tool_name, arguments)
