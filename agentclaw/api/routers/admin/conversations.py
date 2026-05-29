"""
Conversation management API

Supports database-persistent storage for Dashboard chat history.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends

from agentclaw.api.schemas.conversation import (
    CreateConversationRequest,
    UpdateConversationRequest,
    FeedbackRequest,
)
from agentclaw.api.services.conversation_service import (
    ConversationService,
    get_conversation_service,
)
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/{workflow_id}", summary="List conversations")
async def list_conversations(
    workflow_id: str,
    source: str = Query("admin", description="Source filter: admin or public"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    include_messages: bool = Query(False, description="Include full message history in list results"),
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """List conversations for a workflow, filtered by source."""
    result = await service.list_conversations(
        workflow_id=workflow_id,
        source=source,
        page=page,
        page_size=page_size,
        include_messages=include_messages,
    )
    return result


@router.post("", summary="Create conversation")
async def create_conversation(
    req: CreateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Create a new conversation."""
    return await service.create_conversation(
        workflow_id=req.workflow_id,
        title=req.title,
        source=req.source or "admin",
        owner_id=req.owner_id,
        user_id=req.user_id,
        tenant_id=req.tenant_id,
    )


@router.get("/{workflow_id}/{conversation_id}", summary="Get conversation")
async def get_conversation(
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Get conversation detail with messages."""
    conv = await service.get_conversation(workflow_id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.put("/{workflow_id}/{conversation_id}", summary="Update conversation")
async def update_conversation(
    workflow_id: str,
    conversation_id: str,
    req: UpdateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Update conversation title or messages."""
    conv = await service.update_conversation(
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        title=req.title,
        messages=req.messages,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{workflow_id}/{conversation_id}", summary="Delete conversation")
async def delete_conversation(
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Delete a conversation."""
    success = await service.delete_conversation(workflow_id, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": success}


# ============================================================
# Message feedback API
# ============================================================


@router.post("/{workflow_id}/{conversation_id}/feedback", summary="Submit feedback")
async def submit_feedback(
    workflow_id: str,
    conversation_id: str,
    req: FeedbackRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Submit message feedback (like/dislike)."""
    success = await service.submit_feedback(
        conversation_id=conversation_id,
        message_index=req.message_index,
        feedback=req.feedback,
    )
    return {"success": success}


@router.get("/{workflow_id}/{conversation_id}/feedback", summary="Get feedback")
async def get_feedback(
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Get all message feedback for a conversation."""
    feedbacks = await service.get_feedback(conversation_id)
    return {"feedbacks": feedbacks}
