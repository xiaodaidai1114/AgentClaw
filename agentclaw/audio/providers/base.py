from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentclaw.audio.types import AudioArtifact, AudioStream, Voice
from agentclaw.model.manager import LLMConfig


@runtime_checkable
class Speech2TextProvider(Protocol):
    async def transcribe(self, config: LLMConfig, audio: AudioArtifact) -> str:
        ...


@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize(self, config: LLMConfig, text: str, voice: str | None = None) -> AudioStream:
        ...

    async def voices(self, config: LLMConfig, language: str | None = None) -> list[Voice]:
        ...
