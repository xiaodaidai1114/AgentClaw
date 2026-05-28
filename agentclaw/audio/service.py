from __future__ import annotations

from typing import Optional

from agentclaw.audio.providers.registry import AudioProviderRegistry, default_audio_provider_registry
from agentclaw.audio.types import AudioArtifact, AudioStream, Voice
from agentclaw.model.manager import LLMConfig


class AudioService:
    def __init__(self, llm_manager, registry: Optional[AudioProviderRegistry] = None):
        self.llm_manager = llm_manager
        self.registry = registry or default_audio_provider_registry()

    async def transcribe(self, audio: AudioArtifact, model_id: str | None = None) -> str:
        config = self._resolve_model(model_id, "speech2text")
        provider = self._provider(config, "speech2text")
        return await provider.transcribe(config, audio)

    async def synthesize(self, text: str, voice: str | None = None, model_id: str | None = None) -> AudioStream:
        config = self._resolve_model(model_id, "tts")
        provider = self._provider(config, "tts")
        return await provider.synthesize(config, text, voice or self._default_voice(config))

    async def list_voices(self, model_id: str | None = None, language: str | None = None) -> list[Voice]:
        config = self._resolve_model(model_id, "tts")
        provider = self._provider(config, "tts")
        return await provider.voices(config, language)

    def _resolve_model(self, model_id: str | None, expected_type: str) -> LLMConfig:
        selected_id = model_id or self._default_model_id(expected_type)
        if not selected_id:
            raise ValueError(f"No default {expected_type} model configured")
        config = self.llm_manager.get_model(selected_id)
        if str(config.model_type or "").strip().lower() != expected_type:
            raise ValueError(f"Model '{selected_id}' is not a {expected_type} model")
        return config

    def _default_model_id(self, model_type: str) -> str | None:
        if model_type == "speech2text":
            return getattr(self.llm_manager, "speech2text_id", None)
        if model_type == "tts":
            return getattr(self.llm_manager, "tts_id", None)
        return None

    def _provider(self, config: LLMConfig, model_type: str):
        provider = self.registry.get(config.channel, model_type)
        if not provider and (not config.channel or config.channel == config.provider):
            provider = self.registry.get(config.provider, model_type)
        if not provider:
            raise ValueError(f"No audio provider registered for {config.channel}/{model_type}")
        return provider

    def _default_voice(self, config: LLMConfig) -> str | None:
        extra = config.extra_body or {}
        return extra.get("voice") or getattr(self.llm_manager, "tts_voice", None)
