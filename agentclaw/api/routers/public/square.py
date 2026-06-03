"""Public agent square routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from agentclaw.api.routers.public.access import is_public_square_published


router = APIRouter(prefix="/public/square", tags=["public-square"])


def _is_square_published(workflow: Any, workflow_id: str) -> bool:
    return is_public_square_published(workflow, workflow_id)


def _square_workflow_payload(workflow: Any) -> dict[str, Any]:
    workflow_id = str(getattr(workflow, "id", "") or "")
    chat_audio = getattr(workflow, "chat_audio", None)
    chat_audio = chat_audio if isinstance(chat_audio, dict) else {}
    return {
        "id": workflow_id,
        "name": getattr(workflow, "name", workflow_id),
        "description": getattr(workflow, "description", "") or "",
        "recommended_input": getattr(workflow, "recommended_input", "") or "",
        "chat_audio": {
            "enabled": bool(chat_audio.get("enabled")),
            "speech_input_enabled": bool(chat_audio.get("speech_input_enabled")),
            "tts_enabled": bool(chat_audio.get("tts_enabled")),
        },
    }


@router.get("/workflows", summary="List public square workflows")
async def list_public_square_workflows():
    """Return anonymous public workflows that owners explicitly publish to the square."""
    from agentclaw.api.registry import WorkflowRegistry

    workflows = []
    for workflow in WorkflowRegistry.list_all():
        workflow_id = str(getattr(workflow, "id", "") or "")
        if _is_square_published(workflow, workflow_id):
            workflows.append(_square_workflow_payload(workflow))
    return {"workflows": workflows}
