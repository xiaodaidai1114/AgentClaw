"""Standard tool result envelope used by the agent harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


ToolDisplayMode = Literal["collapsed", "expanded", "artifact"]


@dataclass
class ToolResultEnvelope:
    """Normalized result for a single tool call.

    model_content is the compact content appended back to the model context.
    raw_output is retained for trace/UI use and should not be blindly injected.
    """

    call_id: str
    tool_name: str
    success: bool
    summary: str
    model_content: str
    status: str = "success"
    raw_input: Optional[str] = None
    model_arguments: str = "{}"
    raw_output: Any = None
    error: Optional[str] = None
    diagnostic: Optional[str] = None
    retryable: bool = False
    display_mode: ToolDisplayMode = "collapsed"
    risk_level: str = "low"
    tool_risk_level: str = "low"
    model_risk_level: str = "low"
    requires_confirmation: bool = False

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "result": self.raw_output if self.raw_output is not None else self.model_content,
            "status": self.status,
            "tool_call_id": self.call_id,
            "tool_arguments": self.model_arguments or self.raw_input,
            "raw_tool_arguments": self.raw_input,
            "summary": self.summary,
            "success": self.success,
            "error": self.error,
            "diagnostic": self.diagnostic,
            "retryable": self.retryable,
            "risk_level": self.risk_level,
            "tool_risk_level": self.tool_risk_level,
            "model_risk_level": self.model_risk_level,
            "requires_confirmation": self.requires_confirmation,
        }
