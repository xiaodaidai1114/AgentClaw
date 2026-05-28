"""
Admin audio API routes.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from agentclaw.api.schemas.audio import SpeechToTextResponse, TextToSpeechRequest, VoiceInfo
from agentclaw.api.services import audio_synthesis
from agentclaw.audio import AudioArtifact, AudioService
from agentclaw.database import get_database

router = APIRouter(prefix="/audio", tags=["audio"])

_memory_tts_cache = audio_synthesis._memory_tts_cache


def get_audio_service() -> AudioService:
    from agentclaw.api.services.model_service import get_model_service

    model_service = get_model_service()
    llm_manager = getattr(model_service, "_llm_manager", None)
    if not llm_manager:
        raise RuntimeError("LLMManager is not configured")
    return AudioService(llm_manager)


@router.post("/speech-to-text", response_model=SpeechToTextResponse, summary="Transcribe audio")
async def speech_to_text(
    file: UploadFile = File(...),
    model_id: str | None = Form(default=None),
    service: AudioService = Depends(get_audio_service),
):
    data = await file.read()
    text = await service.transcribe(
        AudioArtifact(data=data, mime_type=file.content_type, filename=file.filename),
        model_id=model_id,
    )
    return SpeechToTextResponse(text=text)


@router.post("/text-to-speech", summary="Synthesize speech")
async def text_to_speech(
    request: TextToSpeechRequest,
    service: AudioService = Depends(get_audio_service),
):
    data, mime_type = await audio_synthesis.synthesize_with_cache(
        service,
        text=request.text,
        voice=request.voice or "",
        model_id=request.model_id or "",
        database_getter=get_database,
    )
    return Response(content=data, media_type=mime_type)


@router.get("/voices", response_model=list[VoiceInfo], summary="List TTS voices")
async def voices(
    model_id: str | None = None,
    language: str | None = None,
    service: AudioService = Depends(get_audio_service),
):
    results = await service.list_voices(model_id=model_id, language=language)
    return [VoiceInfo(name=item.name, value=item.value, language=item.language) for item in results]
