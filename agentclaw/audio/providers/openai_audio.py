from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from io import BytesIO
from typing import Any

from openai import OpenAI

from agentclaw.audio.types import AudioArtifact, AudioStream, Voice
from agentclaw.model.manager import LLMConfig


OPENAI_TTS_VOICES = [
    Voice(name="Alloy", value="alloy", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Ash", value="ash", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Ballad", value="ballad", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Coral", value="coral", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Echo", value="echo", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Fable", value="fable", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Onyx", value="onyx", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Nova", value="nova", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Sage", value="sage", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Shimmer", value="shimmer", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
    Voice(name="Verse", value="verse", language=["zh-Hans", "en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "th-TH", "id-ID"]),
]


_MIME_BY_FORMAT = {
    "aac": "audio/aac",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "pcm": "audio/pcm",
    "wav": "audio/wav",
}


class OpenAIAudioProvider:
    async def transcribe(self, config: LLMConfig, audio: AudioArtifact) -> str:
        if not audio.data:
            raise ValueError("audio data is empty")

        def invoke() -> str:
            client = OpenAI(**self._client_kwargs(config))
            file_obj = BytesIO(audio.data)
            file_obj.name = self._filename(audio)
            response = client.audio.transcriptions.create(model=config.model, file=file_obj)
            return response.text

        return await asyncio.to_thread(invoke)

    async def synthesize(self, config: LLMConfig, text: str, voice: str | None = None) -> AudioStream:
        text = text.strip()
        if not text:
            raise ValueError("text is required")

        selected_voice = self._select_voice(config, voice)
        audio_format = self._audio_format(config)

        def invoke() -> Iterable[bytes]:
            client = OpenAI(**self._client_kwargs(config))
            response = client.audio.speech.with_streaming_response.create(
                model=config.model,
                voice=selected_voice,
                response_format=audio_format,
                input=text,
            )
            with response as stream:
                yield from stream.iter_bytes(1024)

        async def chunks() -> AsyncIterator[bytes]:
            for chunk in await asyncio.to_thread(lambda: list(invoke())):
                yield chunk

        return AudioStream(
            chunks=chunks(),
            mime_type=_MIME_BY_FORMAT.get(audio_format, "application/octet-stream"),
            ext=audio_format,
        )

    async def voices(self, config: LLMConfig, language: str | None = None) -> list[Voice]:
        configured = self._extra(config).get("voices")
        if isinstance(configured, list):
            voices = [self._voice_from_mapping(item) for item in configured if isinstance(item, dict)]
        else:
            voices = OPENAI_TTS_VOICES
        if not language:
            return voices
        return [voice for voice in voices if not voice.language or language in voice.language]

    def _client_kwargs(self, config: LLMConfig) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        if config.base_url:
            kwargs["base_url"] = config.base_url
        if config.timeout:
            kwargs["timeout"] = config.timeout
        if config.extra_headers:
            kwargs["default_headers"] = config.extra_headers
        return kwargs

    def _filename(self, audio: AudioArtifact) -> str:
        if audio.filename:
            return audio.filename
        ext = (audio.ext or "").lstrip(".")
        if not ext and audio.mime_type and "/" in audio.mime_type:
            ext = audio.mime_type.rsplit("/", 1)[-1]
        return f"audio.{ext or 'bin'}"

    def _select_voice(self, config: LLMConfig, voice: str | None) -> str:
        extra = self._extra(config)
        voices = extra.get("voices")
        if isinstance(voices, list):
            allowed = {item.get("value") or item.get("mode") for item in voices if isinstance(item, dict)}
        else:
            allowed = {item.value for item in OPENAI_TTS_VOICES}
        default_voice = str(extra.get("voice") or extra.get("default_voice") or "alloy")
        return voice if voice and voice in allowed else default_voice

    def _audio_format(self, config: LLMConfig) -> str:
        extra = self._extra(config)
        return str(extra.get("audio_format") or extra.get("audio_type") or "mp3")

    def _extra(self, config: LLMConfig) -> dict[str, Any]:
        return dict(config.extra_body or {})

    def _voice_from_mapping(self, item: dict[str, Any]) -> Voice:
        value = str(item.get("value") or item.get("mode") or item.get("id") or "")
        return Voice(name=str(item.get("name") or value), value=value, language=item.get("language"))
