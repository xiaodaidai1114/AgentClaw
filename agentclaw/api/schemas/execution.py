"""
Workflow execution request/response schemas
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class WorkflowRunRequest(BaseModel):
    """Workflow execution request (Dify-compatible format)"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "workflow_id": "my_agent",
                "user": "Hello",
                "user_id": "user_001",
                "response_mode": "streaming",
                "conversation_id": "session_001",
                "inputs": {"locale": "zh-CN"}
            }
        }
    )

    workflow_id: str = Field(..., description="Workflow ID to execute")
    user: Optional[str] = Field(
        None,
        description=(
            "User text input string. Used as chat input and HumanNode continuation payload."
        ),
    )
    user_id: Optional[str] = Field(None, description="Caller identifier for tracking")
    response_mode: str = Field("blocking", description="Response mode: blocking or streaming")
    conversation_id: Optional[str] = Field(None, description="Conversation/thread ID for multi-turn")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Workflow input data")
    tool_confirmation_required: bool = Field(False, description="Whether high-risk tools require explicit user confirmation before execution")
    tool_confirmation_level: str = Field("off", description="Tool risk level requiring user confirmation: off, high, medium, or low")


class UsageInfo(BaseModel):
    """Token usage information"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency: Optional[float] = None


class WorkflowRunMetadata(BaseModel):
    """Metadata for workflow execution result"""
    usage: UsageInfo = Field(default_factory=UsageInfo)
    trace_id: Optional[str] = None
    interrupted: bool = False
    status: str = "completed"
    confirmation_required: bool = False
    confirmation: Optional[Dict[str, Any]] = None


class WorkflowRunResponse(BaseModel):
    """Workflow execution response (blocking mode, Dify-compatible)"""
    event: str = "message"
    task_id: str
    id: str
    message_id: str
    conversation_id: Optional[str] = None
    mode: str = "workflow"
    answer: str = ""
    metadata: WorkflowRunMetadata = Field(default_factory=WorkflowRunMetadata)
    created_at: int = 0


class WorkflowRunError(BaseModel):
    """Workflow execution error response"""
    event: str = "error"
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    status: int = 500
    code: str = "WORKFLOW_EXECUTION_ERROR"
    message: str = ""


class ContextCompressRequest(BaseModel):
    """Context compression request"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "workflow_id": "my_agent",
                "conversation_id": "session_001",
            }
        }
    )

    workflow_id: str = Field(..., description="Workflow ID")
    conversation_id: str = Field(..., description="Conversation/session ID (thread_id)")


class ContextCompressResponse(BaseModel):
    """Context compression response"""
    success: bool = True
    workflow_id: str
    conversation_id: str
    compressed: bool = False
    original_count: int = 0
    compressed_count: int = 0
    compressed_message_count: int = 0
    summary_length: int = 0
    summary: str = ""
    has_system: bool = False
    has_welcome: bool = False
    used_llm: bool = False
    context_tokens: int = 0
    memory_updated: bool = False
    memory_path: str = ""


class ConfirmActionRequest(BaseModel):
    """Confirm or reject a dangerous operation"""
    approved: bool = Field(..., description="Whether the operation is approved")
    sudo_password: Optional[str] = Field(None, description="Sudo password (only required if require_sudo=true)")
    request_id: Optional[str] = Field(None, description="Optional client-side request ID for synchronous confirmation adapters")


class ConfirmActionResponse(BaseModel):
    """Confirm action response"""
    success: bool
    confirm_id: str
    approved: bool
    require_sudo: bool = Field(False, description="Whether sudo password was required")
    sudo_received: bool = Field(False, description="Whether sudo password was received (only if require_sudo=true)")
    status: str = Field("resolved", description="Confirmation status: resolved / not_found")
    message: str = ""
