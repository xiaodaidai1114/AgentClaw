from __future__ import annotations

from typing import Any


class AudioProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], Any] = {}

    def register(self, channel: str, model_type: str, provider: Any) -> None:
        self._providers[(self._normalize(channel), self._normalize(model_type))] = provider

    def get(self, channel: str, model_type: str) -> Any | None:
        return self._providers.get((self._normalize(channel), self._normalize(model_type)))

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").strip().lower()


def default_audio_provider_registry() -> AudioProviderRegistry:
    from agentclaw.audio.providers.openai_audio import OpenAIAudioProvider

    registry = AudioProviderRegistry()
    openai_provider = OpenAIAudioProvider()
    for channel in ("openai", "openai_compatible", "openai_api_compatible", "azure", "azure_openai"):
        registry.register(channel, "speech2text", openai_provider)
        registry.register(channel, "tts", openai_provider)
    return registry
