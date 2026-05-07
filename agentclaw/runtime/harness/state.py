"""Runtime state tracked by the agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import time

from agentclaw.runtime.harness.decisions import ContinueDecision
from agentclaw.runtime.harness.tool_result import ToolResultEnvelope


@dataclass
class RuntimeSnapshot:
    """Stable runtime inputs captured at the start of one harness run."""

    run_id: str
    node_id: str
    workflow_id: Optional[str]
    thread_id: Optional[str]
    model_id: Optional[str]
    started_at: float = field(default_factory=time.time)
    enabled_tools: list[str] = field(default_factory=list)
    context_tokens: int = 0


@dataclass
class HarnessTurnState:
    """State for one model/tool turn inside a harness run."""

    turn_index: int
    assistant_text: str = ""
    reasoning_text: str = ""
    tool_call_count: int = 0
    tool_result_count: int = 0
    feedback_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    continue_decision: Optional[ContinueDecision] = None


@dataclass
class HarnessRunState:
    """State for one agentic LLM node run."""

    run_id: str
    node_id: str
    workflow_id: Optional[str]
    thread_id: Optional[str]
    model_id: Optional[str]
    messages: list[dict[str, Any]]
    snapshot: RuntimeSnapshot | None = None
    turns: list[HarnessTurnState] = field(default_factory=list)
    turn_count: int = 0
    assistant_text: str = ""
    reasoning_text: str = ""
    tool_results: list[ToolResultEnvelope] = field(default_factory=list)
    context_tokens: int = 0
    consecutive_empty_responses: int = 0
    pending_continue_rounds: int = 0
    missing_tool_continuation_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    decisions: list[ContinueDecision] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    continue_decision: Optional[ContinueDecision] = None

    def __post_init__(self) -> None:
        if self.snapshot is None:
            self.snapshot = RuntimeSnapshot(
                run_id=self.run_id,
                node_id=self.node_id,
                workflow_id=self.workflow_id,
                thread_id=self.thread_id,
                model_id=self.model_id,
            )

    def begin_turn(self, turn_index: int) -> HarnessTurnState:
        turn = HarnessTurnState(turn_index=turn_index)
        self.turns.append(turn)
        self.turn_count = len(self.turns)
        return turn

    def current_turn(self) -> HarnessTurnState | None:
        return self.turns[-1] if self.turns else None

    def record_event(self, name: str, **metadata: Any) -> dict[str, Any]:
        event = {"name": name, "metadata": metadata, "turn_index": self.current_turn().turn_index if self.current_turn() else None}
        self.events.append(event)
        return event

    def decide(self, action: str, reason: str, **metadata: Any) -> ContinueDecision:
        decision = ContinueDecision(action=action, reason=reason, metadata=metadata)  # type: ignore[arg-type]
        self.continue_decision = decision
        self.decisions.append(decision)
        current_turn = self.current_turn()
        if current_turn is not None:
            current_turn.continue_decision = decision
        return decision
