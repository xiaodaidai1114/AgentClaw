"""
SSE (Server-Sent Events) schema definitions.

Documents all event types emitted during streaming workflow execution.
These models are for documentation purposes and can be used for validation.

Event flow:
  workflow_started
  ├── node_started
  │   ├── message (streaming tokens)
  │   ├── reasoning (thinking content)
  │   ├── tool_start (tool call begins)
  │   ├── tool (tool call completed)
  │   ├── confirm_request (user confirmation needed)
  │   └── context_compression_started (when token threshold exceeded)
  │       └── context_compression_finished
  ├── node_finished
  ├── message_end
  └── workflow_finished
  error (on failure, can occur at any point)
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# === Base ===

class SSEEventBase(BaseModel):
    """Base fields present in all SSE events."""
    event: str = Field(..., description="Event type identifier")
    task_id: str = Field(..., description="Unique task ID for this execution")
    created_at: int = Field(0, description="Unix timestamp (seconds)")


# === Workflow lifecycle ===

class WorkflowStartedData(BaseModel):
    id: str = Field(..., description="Workflow run ID")
    workflow_id: str
    conversation_id: Optional[str] = None
    created_at: int = 0


class WorkflowStartedEvent(SSEEventBase):
    """Emitted when workflow execution begins."""
    event: str = "workflow_started"
    workflow_run_id: str = ""
    data: WorkflowStartedData = Field(default_factory=WorkflowStartedData)


class WorkflowFinishedData(BaseModel):
    id: str = ""
    workflow_id: str = ""
    conversation_id: Optional[str] = None
    status: str = Field("succeeded", description="succeeded | failed | cancelled | interrupted")
    outputs: Dict[str, Any] = Field(default_factory=dict)
    elapsed_time: float = 0.0
    total_tokens: int = 0
    total_steps: int = 0
    error: Optional[str] = None
    created_at: int = 0
    finished_at: int = 0


class WorkflowFinishedEvent(SSEEventBase):
    """Emitted when workflow execution completes (success, failure, or cancellation)."""
    event: str = "workflow_finished"
    workflow_run_id: str = ""
    data: WorkflowFinishedData = Field(default_factory=WorkflowFinishedData)


# === Node lifecycle ===

class NodeStartedData(BaseModel):
    id: str = Field(..., description="Node run ID (workflow_run_id-index)")
    node_id: str = Field(..., description="Node name")
    node_type: str = Field("llm", description="Node type: llm, function, human, etc.")
    title: str = ""
    index: int = 0
    inputs: Dict[str, Any] = Field(default_factory=dict, description="State snapshot at node start (excluding __ keys)")
    parallel_group_id: Optional[str] = Field(None, description="Non-null when node runs in parallel with others in the same group")
    created_at: int = 0


class NodeStartedEvent(SSEEventBase):
    """Emitted when a node begins execution."""
    event: str = "node_started"
    workflow_run_id: str = ""
    data: NodeStartedData = Field(default_factory=NodeStartedData)


class NodeFinishedData(BaseModel):
    id: str = ""
    node_id: str = ""
    status: str = Field("succeeded", description="succeeded | failed | interrupted")
    outputs: Dict[str, Any] = Field(default_factory=dict)
    elapsed_time: float = 0.0
    error: Optional[str] = None
    parallel_group_id: Optional[str] = Field(None, description="Matches node_started parallel_group_id")
    created_at: int = 0


class NodeFinishedEvent(SSEEventBase):
    """Emitted when a node completes execution."""
    event: str = "node_finished"
    workflow_run_id: str = ""
    data: NodeFinishedData = Field(default_factory=NodeFinishedData)


# === Streaming content ===

class MessageEvent(SSEEventBase):
    """Emitted for each streaming token from LLM output."""
    event: str = "message"
    message_id: str = ""
    conversation_id: Optional[str] = None
    answer: str = Field("", description="Token content")
    node_id: Optional[str] = None


class ReasoningEvent(SSEEventBase):
    """Emitted for reasoning/thinking content (e.g., o1, DeepSeek-R1)."""
    event: str = "reasoning"
    message_id: str = ""
    conversation_id: Optional[str] = None
    content: str = Field("", description="Reasoning content")
    node_id: Optional[str] = None


class MessageEndUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency: float = 0.0


class MessageEndMetadata(BaseModel):
    usage: MessageEndUsage = Field(default_factory=MessageEndUsage)


class MessageEndEvent(SSEEventBase):
    """Emitted when LLM message generation is complete."""
    event: str = "message_end"
    id: str = Field("", description="Message ID")
    conversation_id: Optional[str] = None
    metadata: MessageEndMetadata = Field(default_factory=MessageEndMetadata)


# === Tool calls ===

class ToolCallFunction(BaseModel):
    name: str = ""
    arguments: str = Field("", description="JSON string of tool arguments")


class ToolCallInfo(BaseModel):
    id: str = ""
    type: str = "function"
    function: ToolCallFunction = Field(default_factory=ToolCallFunction)


class ToolStartEvent(SSEEventBase):
    """Emitted when a tool call begins (before execution)."""
    event: str = "tool_start"
    message_id: str = ""
    conversation_id: Optional[str] = None
    tool_call: ToolCallInfo = Field(default_factory=ToolCallInfo)
    batch_id: Optional[str] = Field(None, description="Concurrent batch id, e.g. round-1")
    node_id: Optional[str] = None


class ToolEvent(SSEEventBase):
    """Emitted when a tool call completes."""
    event: str = "tool"
    message_id: str = ""
    conversation_id: Optional[str] = None
    tool_call: ToolCallInfo = Field(default_factory=ToolCallInfo)
    tool_result: str = Field("", description="Tool execution result")
    status: str = Field("succeeded", description="succeeded | failed | cancelled | timeout | unknown")
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    batch_id: Optional[str] = Field(None, description="Concurrent batch id, e.g. round-1")
    node_id: Optional[str] = None


# === User interaction ===

class ConfirmRequestEvent(SSEEventBase):
    """Emitted when the agent requests user confirmation for a dangerous operation."""
    event: str = "confirm_request"
    message_id: str = ""
    conversation_id: Optional[str] = None
    confirm_id: str = Field(..., description="Confirmation ID, use with POST /api/confirm/{confirm_id}")
    action: str = Field(..., description="Action description")
    description: str = Field(..., description="Detailed description of the operation")
    require_sudo: bool = Field(False, description="Whether sudo password is required")
    node_id: Optional[str] = None


# === Context Compression ===

class ContextCompressionStartedData(BaseModel):
    """Data for context_compression_started event."""
    original_tokens: int = Field(..., description="Token count before compression")
    created_at: int = 0


class ContextCompressionStartedEvent(SSEEventBase):
    """Emitted when context compression starts."""
    event: str = "context_compression_started"
    workflow_run_id: str = ""
    conversation_id: Optional[str] = None
    data: ContextCompressionStartedData = Field(default_factory=ContextCompressionStartedData)


class ContextCompressionFinishedData(BaseModel):
    """Data for context_compression_finished event."""
    compressed_tokens: int = Field(..., description="Token count after compression")
    compressed_message_count: int = Field(..., description="Number of messages after compression")
    original_message_count: int = Field(..., description="Number of messages before compression")
    created_at: int = 0


class ContextCompressionFinishedEvent(SSEEventBase):
    """Emitted when context compression completes."""
    event: str = "context_compression_finished"
    workflow_run_id: str = ""
    conversation_id: Optional[str] = None
    data: ContextCompressionFinishedData = Field(default_factory=ContextCompressionFinishedData)


# === Error ===

class ErrorEvent(SSEEventBase):
    """Emitted on execution error."""
    event: str = "error"
    message_id: Optional[str] = None
    status: int = 500
    code: str = "workflow_error"
    message: str = ""
