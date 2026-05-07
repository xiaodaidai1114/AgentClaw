"""
Conversation schemas
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCallDetail(BaseModel):
    """Structured tool call information."""
    id: str = Field(..., description="Tool call ID")
    name: str = Field(..., description="Tool name")
    arguments: str = Field("", description="Tool arguments (JSON string)")
    result: str = Field("", description="Tool execution result")
    status: str = Field("succeeded", description="succeeded | failed | cancelled | timeout")
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    timestamp: int = Field(0, description="Unix timestamp in milliseconds")


class ConversationMessage(BaseModel):
    """A single message in a conversation."""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: int = Field(..., description="Unix timestamp in milliseconds")
    toolCalls: Optional[List[ToolCallDetail]] = None
    nodeSteps: Optional[List[Any]] = None
    sourcesExpanded: Optional[bool] = None
    stepsExpanded: Optional[bool] = None
    prompt_tokens: Optional[int] = Field(None, description="Input tokens for this message")
    completion_tokens: Optional[int] = Field(None, description="Output tokens for this message")


class ConversationInfo(BaseModel):
    """Conversation record."""
    id: str
    workflow_id: str
    title: str = "New conversation"
    messages: List[ConversationMessage] = []
    source: Optional[str] = "admin"
    owner_id: Optional[str] = Field(None, description="Reserved owner identity for future multi-user editions")
    user_id: Optional[str] = Field(None, description="Reserved user identity for future multi-user editions")
    tenant_id: Optional[str] = Field(None, description="Reserved tenant identity for future multi-user editions")
    created_at: int = 0
    updated_at: int = 0


class ConversationListResponse(BaseModel):
    """Conversation list response."""
    conversations: List[ConversationInfo] = []


class CreateConversationRequest(BaseModel):
    """Create conversation request."""
    workflow_id: str
    title: Optional[str] = None
    source: Optional[str] = "admin"
    share_token: Optional[str] = None
    owner_id: Optional[str] = Field(None, description="Reserved owner identity for future multi-user editions")
    user_id: Optional[str] = Field(None, description="Reserved user identity for future multi-user editions")
    tenant_id: Optional[str] = Field(None, description="Reserved tenant identity for future multi-user editions")


class UpdateConversationRequest(BaseModel):
    """Update conversation request."""
    title: Optional[str] = None
    messages: Optional[List[Any]] = None


class DeleteConversationResponse(BaseModel):
    """Delete conversation response."""
    success: bool = True
    error: Optional[str] = None


class FeedbackRequest(BaseModel):
    """Message feedback request (like/dislike)."""
    message_index: int = Field(..., description="Message index in conversation")
    feedback: Optional[str] = Field(None, description="like, dislike, or null to cancel")


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    success: bool = True
    error: Optional[str] = None


class FeedbackListResponse(BaseModel):
    """Feedback list response."""
    feedbacks: Dict[int, str] = Field(default_factory=dict, description="Map of message_index to feedback")
