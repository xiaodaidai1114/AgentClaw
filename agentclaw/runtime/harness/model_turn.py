"""Model turn handling primitives for the agent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agentclaw.runtime.harness.decisions import ContinueDecision
from agentclaw.runtime.harness.model_output import AssistantTurnOutput


@dataclass
class ModelTurnResult:
    """Harness-normalized result of one model response."""

    output: Optional[AssistantTurnOutput] = None
    is_empty: bool = False
    should_abort: bool = False
    retries: int = 0
    decision: Optional[ContinueDecision] = None
