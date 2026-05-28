import asyncio
import json
from pathlib import Path

import pytest

from agentclaw.model.manager import LLMConfig, LLMManager


pytestmark = pytest.mark.unit


def _write_models(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "default": "chat",
                "speech2text": "asr",
                "tts": "tts",
                "tts_voice": "nova",
                "models": [
                    {"id": "chat", "model_type": "chat", "model": "gpt-4o-mini", "api_key": "chat-key"},
                    {"id": "asr", "model_type": "speech2text", "model": "whisper-1", "api_key": "asr-key"},
                    {
                        "id": "tts",
                        "model_type": "tts",
                        "model": "tts-1",
                        "api_key": "tts-key",
                        "voice": "alloy",
                        "audio_format": "mp3",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_audio_types_preserve_metadata():
    from agentclaw.audio.types import AudioArtifact, AudioStream, Voice

    audio = AudioArtifact(data=b"abc", mime_type="audio/wav", filename="clip.wav")
    voice = Voice(name="Alloy", value="alloy", language=["en-US"])

    async def chunks():
        yield b"a"

    stream = AudioStream(chunks=chunks(), mime_type="audio/mpeg", ext="mp3")

    assert audio.data == b"abc"
    assert audio.mime_type == "audio/wav"
    assert audio.filename == "clip.wav"
    assert voice.value == "alloy"
    assert voice.language == ["en-US"]
    assert stream.mime_type == "audio/mpeg"
    assert stream.ext == "mp3"


def test_provider_registry_returns_registered_adapter():
    from agentclaw.audio.providers.base import Speech2TextProvider
    from agentclaw.audio.providers.registry import AudioProviderRegistry

    class DummyProvider:
        async def transcribe(self, config, audio):
            return "ok"

    registry = AudioProviderRegistry()
    provider = DummyProvider()
    registry.register("custom", "speech2text", provider)

    assert registry.get("custom", "speech2text") is provider
    assert isinstance(registry.get("custom", "speech2text"), Speech2TextProvider)


def test_default_registry_supports_openai_compatible_aliases():
    from agentclaw.audio.providers.registry import default_audio_provider_registry

    registry = default_audio_provider_registry()

    assert registry.get("openai_compatible", "speech2text") is not None
    assert registry.get("openai_api_compatible", "speech2text") is not None
    assert registry.get("openai_api_compatible", "tts") is not None


def test_openai_provider_preserves_audio_filename_for_asr(monkeypatch):
    from agentclaw.audio.providers.openai_audio import OpenAIAudioProvider
    from agentclaw.audio.types import AudioArtifact

    captured = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"text": "hello"})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.audio = type("Audio", (), {"transcriptions": FakeTranscriptions()})()

    monkeypatch.setattr("agentclaw.audio.providers.openai_audio.OpenAI", FakeOpenAI)

    config = LLMConfig(id="asr", model_type="speech2text", model="whisper-1", api_key="sk-test")
    audio = AudioArtifact(data=b"RIFF----WAVE", mime_type="audio/wav", filename="meeting.wav")

    text = asyncio.run(OpenAIAudioProvider().transcribe(config, audio))

    assert text == "hello"
    assert captured["model"] == "whisper-1"
    assert captured["file"].name == "meeting.wav"
    assert captured["file"].read() == b"RIFF----WAVE"
    assert captured["client_kwargs"]["api_key"] == "sk-test"


def test_openai_provider_streams_tts_and_falls_back_to_default_voice(monkeypatch):
    from agentclaw.audio.providers.openai_audio import OpenAIAudioProvider

    captured = {}

    class FakeStreamingResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_bytes(self, chunk_size):
            captured["chunk_size"] = chunk_size
            yield b"one"
            yield b"two"

    class FakeSpeechResponse:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeStreamingResponse()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.audio = type(
                "Audio",
                (),
                {
                    "speech": type(
                        "Speech",
                        (),
                        {"with_streaming_response": FakeSpeechResponse()},
                    )()
                },
            )()

    monkeypatch.setattr("agentclaw.audio.providers.openai_audio.OpenAI", FakeOpenAI)

    config = LLMConfig(
        id="tts",
        model_type="tts",
        model="tts-1",
        api_key="sk-test",
        extra_body={"voice": "nova", "audio_format": "mp3"},
    )

    stream = asyncio.run(OpenAIAudioProvider().synthesize(config, "hello", voice="missing"))

    async def collect():
        return [chunk async for chunk in stream.chunks]

    assert asyncio.run(collect()) == [b"one", b"two"]
    assert stream.mime_type == "audio/mpeg"
    assert stream.ext == "mp3"
    assert captured["voice"] == "nova"
    assert captured["response_format"] == "mp3"
    assert captured["input"] == "hello"


def test_audio_service_uses_default_models_and_model_voice(tmp_path, monkeypatch):
    from agentclaw.audio.service import AudioService
    from agentclaw.audio.types import AudioArtifact, AudioStream

    models_path = tmp_path / "models.json"
    _write_models(models_path)
    manager = LLMManager(config_path=str(models_path))
    service = AudioService(manager)

    calls = []

    class FakeProvider:
        async def transcribe(self, config, audio):
            calls.append(("asr", config.id, audio.filename))
            return "recognized"

        async def synthesize(self, config, text, voice=None):
            calls.append(("tts", config.id, text, voice))

            async def chunks():
                yield b"audio"

            return AudioStream(chunks=chunks(), mime_type="audio/mpeg", ext="mp3")

        async def voices(self, config, language=None):
            calls.append(("voices", config.id, language))
            return []

    monkeypatch.setattr(service.registry, "get", lambda channel, model_type: FakeProvider())

    text = asyncio.run(service.transcribe(AudioArtifact(data=b"abc", filename="a.wav")))
    stream = asyncio.run(service.synthesize("hello"))

    async def collect():
        return [chunk async for chunk in stream.chunks]

    assert text == "recognized"
    assert asyncio.run(collect()) == [b"audio"]
    assert calls == [
        ("asr", "asr", "a.wav"),
        ("tts", "tts", "hello", "alloy"),
    ]


def test_audio_service_rejects_wrong_model_type(tmp_path):
    from agentclaw.audio.service import AudioService
    from agentclaw.audio.types import AudioArtifact

    models_path = tmp_path / "models.json"
    _write_models(models_path)
    manager = LLMManager(config_path=str(models_path))
    service = AudioService(manager)

    with pytest.raises(ValueError, match="speech2text"):
        asyncio.run(service.transcribe(AudioArtifact(data=b"abc"), model_id="chat"))


def test_audio_service_rejects_unregistered_provider_channel(tmp_path):
    from agentclaw.audio.service import AudioService

    models_path = tmp_path / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "default": "chat",
                "tts": "tongyi-tts",
                "models": [
                    {"id": "chat", "model_type": "chat", "model": "gpt-4o-mini"},
                    {"id": "tongyi-tts", "channel": "tongyi", "model_type": "tts", "model": "qwen-tts"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = LLMManager(config_path=str(models_path))
    service = AudioService(manager)

    with pytest.raises(ValueError, match="No audio provider registered"):
        asyncio.run(service.list_voices())


def test_model_service_excludes_audio_models_from_available_list(tmp_path):
    from agentclaw.api.services.model_service import ModelService

    models_path = tmp_path / "models.json"
    _write_models(models_path)
    manager = LLMManager(config_path=str(models_path))
    service = ModelService(llm_manager=manager)

    ids = {item["id"] for item in service.list_available_models()["models"]}

    assert "chat" in ids
    assert "asr" not in ids
    assert "tts" not in ids
