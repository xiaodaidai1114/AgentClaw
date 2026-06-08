"""Admin API for managing public multi-user rooms."""

from fastapi import APIRouter, HTTPException, Query

from agentclaw.api.registry import WorkflowRegistry
from agentclaw.api.services.public_room_chat_service import get_public_room_chat_service
from agentclaw.api.services.public_room_service import (
    PublicRoomInfraError,
    get_public_room_service,
)


router = APIRouter(prefix="/public-rooms", tags=["public-rooms"])


def _workflow_label(workflow_id: str) -> str:
    workflow = WorkflowRegistry.get(workflow_id)
    return str(getattr(workflow, "name", "") or workflow_id) if workflow else workflow_id


def _with_workflow_label(room: dict) -> dict:
    workflow_id = str(room.get("workflow_id") or "")
    return {**room, "workflow_name": _workflow_label(workflow_id)}


def _infra_error(exc: PublicRoomInfraError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("", summary="List public rooms")
async def list_public_rooms(
    workflow_id: str = Query("", description="Filter by workflow ID"),
    status: str = Query("", description="Lifecycle status: active, running, expired, deleted"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        result = await get_public_room_service().list_admin_rooms(
            workflow_id=workflow_id,
            status=status,
            page=page,
            page_size=page_size,
        )
    except PublicRoomInfraError as exc:
        raise _infra_error(exc) from exc
    result["rooms"] = [_with_workflow_label(room) for room in result.get("rooms", [])]
    return result


@router.get("/{room_id}", summary="Get public room detail")
async def get_public_room_detail(room_id: str):
    try:
        detail = await get_public_room_service().get_admin_room_detail(room_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Public room not found")
        chat_messages = await get_public_room_chat_service().list_messages(room_id, limit=200)
    except PublicRoomInfraError as exc:
        raise _infra_error(exc) from exc
    detail["room"] = _with_workflow_label(detail["room"])
    detail["chat_messages"] = chat_messages
    return detail


@router.delete("/{room_id}", summary="Delete public room")
async def delete_public_room(room_id: str):
    try:
        success = await get_public_room_service().revoke_room(room_id)
    except PublicRoomInfraError as exc:
        raise _infra_error(exc) from exc
    if not success:
        raise HTTPException(status_code=404, detail="Public room not found")
    return {"success": True}


@router.delete("/{room_id}/participants/{owner_id}", summary="Kick a public room participant")
async def kick_public_room_participant(room_id: str, owner_id: str):
    try:
        success = await get_public_room_service().kick_participant(room_id, owner_id)
    except PublicRoomInfraError as exc:
        raise _infra_error(exc) from exc
    if not success:
        raise HTTPException(status_code=404, detail="Public room participant not found")
    return {"success": True}
