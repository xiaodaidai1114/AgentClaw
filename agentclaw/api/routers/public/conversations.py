"""Public conversation API constrained to public conversation records."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from agentclaw.api.schemas.conversation import (
    CreateConversationRequest,
    FeedbackRequest,
    UpdateConversationRequest,
)
from agentclaw.api.services.conversation_service import (
    ConversationService,
    get_conversation_service,
)
from agentclaw.api.routers.public.access import (
    check_public_conversation_quota,
    check_public_rate_limit,
    forbidden_response,
    validate_public_message_quota,
    verify_public_share_token,
    workflow_not_found_response,
)
from agentclaw.api.routers.public.session import (
    bind_public_conversation_owner,
    public_owner_id_from_request,
    verify_public_page_session,
)


PUBLIC_SOURCE = "public"

router = APIRouter(
    prefix="/conversations",
    tags=["public-conversations"],
)


def _get_workflow(workflow_id: str) -> Any:
    from agentclaw.api.registry import WorkflowRegistry

    return WorkflowRegistry.get(workflow_id)


def _verify_public_conversation_access(
    workflow_id: str,
    request: Request,
    body: dict[str, Any] | None = None,
) -> tuple[Any | None, JSONResponse | None]:
    workflow = _get_workflow(workflow_id)
    if not workflow:
        return None, workflow_not_found_response(workflow_id)
    share_error = verify_public_share_token(workflow, workflow_id, request, body)
    if share_error:
        return None, share_error
    if not verify_public_page_session(request, workflow_id):
        return None, forbidden_response("Public conversation access requires a same-origin public page session")
    if not public_owner_id_from_request(request):
        return None, forbidden_response("Public conversation access requires an anonymous public user")
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "conversation")
    if rate_error:
        return None, rate_error
    return workflow, None


@router.get("/{workflow_id}", summary="List public conversations")
async def list_conversations(
    request: Request,
    workflow_id: str,
    source: str = Query(PUBLIC_SOURCE, description="Ignored; public API is always scoped to public"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    include_messages: bool = Query(False, description="Include full message history in list results"),
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Return conversations owned by the current anonymous public user."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    return await service.list_conversations(
        workflow_id=workflow_id,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
        page=page,
        page_size=page_size,
        include_messages=include_messages,
    )


@router.post("", summary="Create public conversation")
async def create_conversation(
    request: Request,
    req: CreateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Create a public conversation, regardless of caller-provided source."""
    workflow, access_error = _verify_public_conversation_access(
        req.workflow_id,
        request,
        req.model_dump(),
    )
    if access_error:
        return access_error
    quota_error = check_public_conversation_quota(workflow, req.workflow_id, request)
    if quota_error:
        return quota_error
    owner_id = public_owner_id_from_request(request)
    conv = await service.create_conversation(
        workflow_id=req.workflow_id,
        title=req.title,
        source=PUBLIC_SOURCE,
        owner_id=owner_id,
        user_id=None,
        tenant_id=None,
    )
    bind_public_conversation_owner(req.workflow_id, conv.get("id", ""), owner_id)
    return conv


@router.get("/{workflow_id}/{conversation_id}", summary="Get public conversation")
async def get_conversation(
    request: Request,
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Get a public conversation detail with messages."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    conv = await service.get_conversation(
        workflow_id,
        conversation_id,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.put("/{workflow_id}/{conversation_id}", summary="Update public conversation")
async def update_conversation(
    request: Request,
    workflow_id: str,
    conversation_id: str,
    req: UpdateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Update a public conversation."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    quota_error = validate_public_message_quota(workflow, req.messages)
    if quota_error:
        return quota_error
    conv = await service.update_conversation(
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        title=req.title,
        messages=req.messages,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{workflow_id}/{conversation_id}", summary="Delete public conversation")
async def delete_conversation(
    request: Request,
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Delete a public conversation."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    success = await service.delete_conversation(
        workflow_id,
        conversation_id,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": success}


@router.post("/{workflow_id}/{conversation_id}/feedback", summary="Submit public feedback")
async def submit_feedback(
    request: Request,
    workflow_id: str,
    conversation_id: str,
    req: FeedbackRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Submit message feedback for a public conversation."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    conv = await service.get_conversation(
        workflow_id,
        conversation_id,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    success = await service.submit_feedback(
        conversation_id=conversation_id,
        message_index=req.message_index,
        feedback=req.feedback,
    )
    return {"success": success}


@router.get("/{workflow_id}/{conversation_id}/feedback", summary="Get public feedback")
async def get_feedback(
    request: Request,
    workflow_id: str,
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Get feedback for a public conversation."""
    workflow, access_error = _verify_public_conversation_access(workflow_id, request)
    if access_error:
        return access_error
    conv = await service.get_conversation(
        workflow_id,
        conversation_id,
        source=PUBLIC_SOURCE,
        owner_id=public_owner_id_from_request(request),
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    feedbacks = await service.get_feedback(conversation_id)
    return {"feedbacks": feedbacks}
