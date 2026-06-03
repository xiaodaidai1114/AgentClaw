"""Public workflow audio routes constrained by workflow share settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from agentclaw.api.routers.public.access import (
    check_public_rate_limit,
    forbidden_response,
    verify_public_share_token,
    workflow_not_found_response,
)
from agentclaw.api.routers.public.session import verify_public_page_session
from agentclaw.api.schemas.audio import SpeechToTextResponse, TextToSpeechRequest
from agentclaw.api.schemas.common import ErrorCode
from agentclaw.api.services import audio_synthesis
from agentclaw.api.services.public_room_service import (
    PUBLIC_ROOM_INFRA_ERROR,
    PublicRoomAccessError,
    PublicRoomInfraError,
    get_public_room_service,
)
from agentclaw.api.upload_limits import UploadTooLarge, enforce_upload_content_length, read_upload_file_limited
from agentclaw.audio import AudioArtifact, AudioService
from agentclaw.database import get_database


router = APIRouter(tags=["public-audio"])
workflow_audio_router = APIRouter(prefix="/public/workflows/{workflow_id}")
room_audio_router = APIRouter(prefix="/public/rooms/{room_id}")
_memory_tts_cache = audio_synthesis._memory_tts_cache


def get_audio_service() -> AudioService:
    from agentclaw.api.services.model_service import get_model_service

    model_service = get_model_service()
    llm_manager = getattr(model_service, "_llm_manager", None)
    if not llm_manager:
        raise RuntimeError("LLMManager is not configured")
    return AudioService(llm_manager)


def _resolve_audio_service(request: Request) -> AudioService:
    override = getattr(request.app, "dependency_overrides", {}).get(get_audio_service)
    if override:
        return override()
    return get_audio_service()


def _public_max_audio_bytes() -> int:
    try:
        value = int(os.getenv("AGENTCLAW_PUBLIC_MAX_AUDIO_BYTES", "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else 10 * 1024 * 1024


def _public_max_tts_chars() -> int:
    try:
        value = int(os.getenv("AGENTCLAW_PUBLIC_MAX_TTS_CHARS", "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else 2000


def public_speech_to_text_path_prefix() -> str:
    return "/api/public/workflows/*/speech-to-text"


def public_room_speech_to_text_path_prefix() -> str:
    return "/api/public/rooms/*/speech-to-text"


def _csv_env_values(name: str) -> set[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _validate_public_audio_file(file: UploadFile) -> JSONResponse | None:
    allowed_mime_types = _csv_env_values("AGENTCLAW_PUBLIC_AUDIO_ALLOWED_MIME_TYPES")
    if allowed_mime_types:
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        if content_type not in allowed_mime_types:
            return JSONResponse(
                status_code=400,
                content={"error": "Audio MIME type is not allowed", "code": ErrorCode.INVALID_REQUEST},
            )

    allowed_extensions = _csv_env_values("AGENTCLAW_PUBLIC_AUDIO_ALLOWED_EXTENSIONS")
    if allowed_extensions:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in allowed_extensions:
            return JSONResponse(
                status_code=400,
                content={"error": "Audio file extension is not allowed", "code": ErrorCode.INVALID_REQUEST},
            )
    return None


def _chat_audio(workflow: Any) -> dict[str, Any]:
    config = getattr(workflow, "chat_audio", None)
    return config if isinstance(config, dict) else {}


def public_chat_audio_payload(workflow: Any) -> dict[str, Any]:
    config = _chat_audio(workflow)
    return {
        "enabled": bool(config.get("enabled")),
        "speech_input_enabled": bool(config.get("speech_input_enabled")),
        "tts_enabled": bool(config.get("tts_enabled")),
        "max_audio_bytes": _public_max_audio_bytes(),
        "max_tts_chars": _public_max_tts_chars(),
    }


def _get_public_workflow_or_error(workflow_id: str, request: Request, body: dict[str, Any] | None = None):
    from agentclaw.api.registry import WorkflowRegistry

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return None, workflow_not_found_response(workflow_id)
    share_error = verify_public_share_token(workflow, workflow_id, request, body)
    if share_error:
        return None, share_error
    if not verify_public_page_session(request, workflow_id):
        return None, forbidden_response("Public audio requires a same-origin public page session")
    return workflow, None


async def _get_public_room_workflow_or_error(room_id: str, request: Request):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public.session import public_owner_id_from_request

    try:
        service = get_public_room_service()
        room = await service.get_room(room_id)
        if not room:
            return None, None, JSONResponse(
                status_code=404,
                content={"error": "Public room not found", "code": ErrorCode.NOT_FOUND},
            )
        workflow_id = str(room.get("workflow_id") or "")
        if not verify_public_page_session(request, workflow_id):
            return None, None, forbidden_response("Public room audio requires a same-origin public page session")
        owner_id = public_owner_id_from_request(request)
        if not owner_id:
            return None, None, forbidden_response("Public room audio requires an anonymous public user")
        await service.require_member(room_id, owner_id)
    except PublicRoomInfraError as exc:
        return None, None, JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": PUBLIC_ROOM_INFRA_ERROR},
        )
    except PublicRoomAccessError as exc:
        return None, None, forbidden_response(str(exc))

    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        return None, None, workflow_not_found_response(workflow_id)
    return workflow, room, None


def _feature_disabled_response(feature: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": f"Public {feature} is not enabled for this workflow", "code": ErrorCode.FORBIDDEN},
    )


@workflow_audio_router.post("/speech-to-text", response_model=SpeechToTextResponse, summary="Transcribe public workflow audio")
async def public_speech_to_text(
    workflow_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    workflow, access_error = _get_public_workflow_or_error(workflow_id, request)
    if access_error:
        return access_error
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "speech_to_text")
    if rate_error:
        return rate_error

    config = _chat_audio(workflow)
    if not bool(config.get("enabled")) or not bool(config.get("speech_input_enabled")):
        return _feature_disabled_response("speech input")

    validation_error = _validate_public_audio_file(file)
    if validation_error:
        return validation_error

    max_size = _public_max_audio_bytes()
    try:
        enforce_upload_content_length(request, max_size)
        data = await read_upload_file_limited(file, max_size)
    except UploadTooLarge:
        return JSONResponse(
            status_code=413,
            content={"error": "Audio file is too large", "code": ErrorCode.INVALID_REQUEST},
        )

    service = _resolve_audio_service(request)
    text = await service.transcribe(
        AudioArtifact(data=data, mime_type=file.content_type, filename=file.filename),
        model_id=str(config.get("speech2text_model_id") or "") or None,
    )
    return SpeechToTextResponse(text=text)


@room_audio_router.post("/speech-to-text", response_model=SpeechToTextResponse, summary="Transcribe public room audio")
async def public_room_speech_to_text(
    room_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    workflow, room, access_error = await _get_public_room_workflow_or_error(room_id, request)
    if access_error:
        return access_error
    workflow_id = str(room.get("workflow_id") or "")
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "room-speech-to-text")
    if rate_error:
        return rate_error

    config = _chat_audio(workflow)
    if not bool(config.get("enabled")) or not bool(config.get("speech_input_enabled")):
        return _feature_disabled_response("speech input")

    validation_error = _validate_public_audio_file(file)
    if validation_error:
        return validation_error

    max_size = _public_max_audio_bytes()
    try:
        enforce_upload_content_length(request, max_size)
        data = await read_upload_file_limited(file, max_size)
    except UploadTooLarge:
        return JSONResponse(
            status_code=413,
            content={"error": "Audio file is too large", "code": ErrorCode.INVALID_REQUEST},
        )

    service = _resolve_audio_service(request)
    text = await service.transcribe(
        AudioArtifact(data=data, mime_type=file.content_type, filename=file.filename),
        model_id=str(config.get("speech2text_model_id") or "") or None,
    )
    return SpeechToTextResponse(text=text)


@workflow_audio_router.post("/text-to-speech", summary="Synthesize public workflow speech")
async def public_text_to_speech(
    workflow_id: str,
    request: Request,
    body: TextToSpeechRequest,
):
    workflow, access_error = _get_public_workflow_or_error(workflow_id, request, body.model_dump())
    if access_error:
        return access_error
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "text_to_speech")
    if rate_error:
        return rate_error

    config = _chat_audio(workflow)
    if not bool(config.get("enabled")) or not bool(config.get("tts_enabled")):
        return _feature_disabled_response("text-to-speech")

    text = body.text or ""
    max_chars = _public_max_tts_chars()
    if len(text) > max_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Text exceeds public text-to-speech limit ({max_chars} characters)",
                "code": ErrorCode.INVALID_REQUEST,
            },
        )

    service = _resolve_audio_service(request)
    data, mime_type = await audio_synthesis.synthesize_with_cache(
        service,
        text=text,
        voice=str(config.get("tts_voice") or ""),
        model_id=str(config.get("tts_model_id") or ""),
        database_getter=get_database,
    )
    return Response(content=data, media_type=mime_type)


@room_audio_router.post("/text-to-speech", summary="Synthesize public room speech")
async def public_room_text_to_speech(
    room_id: str,
    request: Request,
    body: TextToSpeechRequest,
):
    workflow, room, access_error = await _get_public_room_workflow_or_error(room_id, request)
    if access_error:
        return access_error
    workflow_id = str(room.get("workflow_id") or "")
    rate_error = check_public_rate_limit(workflow, workflow_id, request, "room-text-to-speech")
    if rate_error:
        return rate_error

    config = _chat_audio(workflow)
    if not bool(config.get("enabled")) or not bool(config.get("tts_enabled")):
        return _feature_disabled_response("text-to-speech")

    text = body.text or ""
    max_chars = _public_max_tts_chars()
    if len(text) > max_chars:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Text exceeds public text-to-speech limit ({max_chars} characters)",
                "code": ErrorCode.INVALID_REQUEST,
            },
        )

    service = _resolve_audio_service(request)
    data, mime_type = await audio_synthesis.synthesize_with_cache(
        service,
        text=text,
        voice=str(config.get("tts_voice") or ""),
        model_id=str(config.get("tts_model_id") or ""),
        database_getter=get_database,
    )
    return Response(content=data, media_type=mime_type)


router.include_router(workflow_audio_router)
router.include_router(room_audio_router)
