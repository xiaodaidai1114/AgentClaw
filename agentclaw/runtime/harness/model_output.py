"""Model output post-processing for harness-managed turns."""

from __future__ import annotations

import html
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssistantTurnOutput:
    """Structured view of one model response."""

    text: str = ""
    reasoning: str = ""
    tool_calls: list[Any] = field(default_factory=list)
    has_valid_text: bool = False
    has_tool_calls: bool = False
    malformed: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def combined_content(self) -> str:
        parts = [part for part in (self.reasoning, self.text) if part]
        return "\n".join(parts)


@dataclass
class ParsedTextToolCall:
    """Tool call parsed from provider-specific text fallback formats."""

    id: str
    name: str
    arguments: str


def _parse_textual_tool_calls(text: str) -> tuple[str, list[ParsedTextToolCall]]:
    """Parse provider-specific textual tool-call fallbacks from model content."""
    if not text or "<invoke" not in text:
        return text, []

    tool_calls: list[ParsedTextToolCall] = []

    block_pattern = re.compile(
        r"<(?:[\w.-]+:)?tool_call\b[^>]*>(.*?)</(?:[\w.-]+:)?tool_call>",
        flags=re.DOTALL | re.IGNORECASE,
    )
    invoke_pattern = re.compile(
        r"<invoke\b[^>]*\bname\s*=\s*(['\"])(?P<name>[^'\"]+)\1[^>]*>(?P<body>.*?)</invoke>",
        flags=re.DOTALL | re.IGNORECASE,
    )
    parameter_pattern = re.compile(
        r"<parameter\b[^>]*\bname\s*=\s*(['\"])(?P<name>[^'\"]+)\1[^>]*>(?P<value>.*?)</parameter>",
        flags=re.DOTALL | re.IGNORECASE,
    )

    def parse_invokes(source: str) -> None:
        for match in invoke_pattern.finditer(source):
            tool_name = html.unescape(match.group("name")).strip()
            if not tool_name:
                continue
            arguments: dict[str, str] = {}
            for parameter in parameter_pattern.finditer(match.group("body")):
                param_name = html.unescape(parameter.group("name")).strip()
                if not param_name:
                    continue
                param_value = html.unescape(parameter.group("value")).strip()
                arguments[param_name] = param_value
            tool_calls.append(
                ParsedTextToolCall(
                    id=f"text_call_{uuid.uuid4().hex}",
                    name=tool_name,
                    arguments=json.dumps(arguments, ensure_ascii=False),
                )
            )

    matched_blocks = list(block_pattern.finditer(text))
    for block in matched_blocks:
        parse_invokes(block.group(1))

    if not matched_blocks:
        parse_invokes(text)

    if not tool_calls:
        return text, []

    cleaned = block_pattern.sub("", text)
    if not matched_blocks:
        cleaned = invoke_pattern.sub("", cleaned)
    return cleaned.strip(), tool_calls


def postprocess_model_output(response: Any = None, *, chunks: list[str] | None = None) -> AssistantTurnOutput:
    """Normalize model response into text/reasoning/tool-call channels."""
    text = "".join(chunks or [])
    if not text and isinstance(response, str):
        text = response
    if not text and response is not None and hasattr(response, "content"):
        content = getattr(response, "content", "")
        text = content if isinstance(content, str) else str(content or "")
    reasoning = ""
    if response is not None and hasattr(response, "reasoning"):
        reasoning_value = getattr(response, "reasoning", "")
        reasoning = reasoning_value if isinstance(reasoning_value, str) else str(reasoning_value or "")
    tool_calls = []
    if response is not None and hasattr(response, "tool_calls"):
        raw_tool_calls = getattr(response, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = [tool for tool in raw_tool_calls if getattr(tool, "name", None) and str(getattr(tool, "name", "")).strip()]
    text_tool_calls: list[ParsedTextToolCall] = []
    if not tool_calls and text:
        text, text_tool_calls = _parse_textual_tool_calls(text)
        tool_calls.extend(text_tool_calls)
    warnings = []
    malformed = False
    if response is not None and getattr(response, "tool_calls", None) and not tool_calls:
        malformed = True
        warnings.append("Model returned tool calls without valid tool names")
    if text_tool_calls:
        warnings.append("Parsed provider textual tool-call fallback")
    return AssistantTurnOutput(
        text=text,
        reasoning=reasoning,
        tool_calls=tool_calls,
        has_valid_text=bool(text.strip()),
        has_tool_calls=bool(tool_calls),
        malformed=malformed,
        warnings=warnings,
    )
