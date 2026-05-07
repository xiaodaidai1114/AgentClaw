"""
API 数据模型（Pydantic Schemas）
"""

from agentclaw.api.schemas.common import (
    SuccessResponse,
    ErrorResponse,
    PaginatedResponse,
    ErrorCode,
    error_response,
)
from agentclaw.api.schemas.execution import (
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowRunError,
    WorkflowRunMetadata,
    UsageInfo,
    ConfirmActionRequest,
    ConfirmActionResponse,
)
from agentclaw.api.schemas.workflow import (
    WorkflowNode,
    WorkflowEdge,
    WorkflowInfo,
    WorkflowStructure,
    WorkflowStats,
    WorkflowListResponse,
    WorkflowDetailResponse,
)
from agentclaw.api.schemas.trace import (
    TraceRecord,
    NodeLog,
    LLMLog,
    TraceDetail,
    TraceListResponse,
    TraceTimelineEvent,
    TraceTimelineResponse,
)
from agentclaw.api.schemas.prompt import (
    PromptInfo,
    PromptHistory,
    PromptListResponse,
    PromptUpdateRequest,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptHistoryResponse,
    PromptRollbackRequest,
)
from agentclaw.api.schemas.model import (
    ModelInfo,
    ModelStats,
    FallbackState,
    ModelListResponse,
    ModelUpdateRequest,
    ModelFallbackRequest,
)
from agentclaw.api.schemas.dashboard import (
    DashboardStats,
    TracesSummary,
    TrendDataPoint,
    DurationDataPoint,
    TrendData,
    AvailableModel,
    AvailableModelsResponse,
    NodeModelUpdateRequest,
    NodeModelUpdateResponse,
)
from agentclaw.api.schemas.conversation import (
    ConversationMessage,
    ConversationInfo,
    ConversationListResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
    DeleteConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackListResponse,
)
from agentclaw.api.schemas.upload import (
    UploadStatusResponse,
    UploadFileResponse,
)

__all__ = [
    # Common
    "SuccessResponse",
    "ErrorResponse",
    "PaginatedResponse",
    "ErrorCode",
    "error_response",
    # Execution
    "WorkflowRunRequest",
    "WorkflowRunResponse",
    "WorkflowRunError",
    "WorkflowRunMetadata",
    "UsageInfo",
    "ConfirmActionRequest",
    "ConfirmActionResponse",
    # Workflow
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowInfo",
    "WorkflowStructure",
    "WorkflowStats",
    "WorkflowListResponse",
    "WorkflowDetailResponse",
    # Trace
    "TraceRecord",
    "NodeLog",
    "LLMLog",
    "TraceDetail",
    "TraceListResponse",
    "TraceTimelineEvent",
    "TraceTimelineResponse",
    # Prompt
    "PromptInfo",
    "PromptHistory",
    "PromptListResponse",
    "PromptUpdateRequest",
    "PromptPreviewRequest",
    "PromptPreviewResponse",
    "PromptHistoryResponse",
    "PromptRollbackRequest",
    # Model
    "ModelInfo",
    "ModelStats",
    "FallbackState",
    "ModelListResponse",
    "ModelUpdateRequest",
    "ModelFallbackRequest",
    # Dashboard
    "DashboardStats",
    "TracesSummary",
    "TrendDataPoint",
    "DurationDataPoint",
    "TrendData",
    "AvailableModel",
    "AvailableModelsResponse",
    "NodeModelUpdateRequest",
    "NodeModelUpdateResponse",
    # Conversation
    "ConversationMessage",
    "ConversationInfo",
    "ConversationListResponse",
    "CreateConversationRequest",
    "UpdateConversationRequest",
    "DeleteConversationResponse",
    "FeedbackRequest",
    "FeedbackResponse",
    "FeedbackListResponse",
    # Upload
    "UploadStatusResponse",
    "UploadFileResponse",
]
