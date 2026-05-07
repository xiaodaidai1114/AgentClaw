"""Explicit control-flow decisions produced by the agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ContinueAction = Literal[
    "continue",
    "finish",
    "compact_then_continue",
    "summarize_tools_then_continue",
    "fallback_then_retry",
    "abort",
]


@dataclass
class ContinueDecision:
    """A harness decision explaining what should happen after a turn."""

    action: ContinueAction
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
