import pytest

from agentclaw.audio.types import AudioStream, Voice
from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


class FakeAudioService:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio, model_id=None):
        self.calls.append(("transcribe", audio.data, audio.filename, audio.mime_type, model_id))
        return "recognized text"

    async def synthesize(self, text, voice=None, model_id=None):
        self.calls.append(("synthesize", text, voice, model_id))

        async def chunks():
            yield b"one"
            yield b"two"

        return AudioStream(chunks=chunks(), mime_type="audio/mpeg", ext="mp3")

    async def list_voices(self, model_id=None, language=None):
        self.calls.append(("voices", model_id, language))
        return [Voice(name="Alloy", value="alloy", language=["en-US"])]


def test_admin_audio_routes_use_audio_service(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import audio as audio_router

    service = FakeAudioService()
    admin_api_client.app.dependency_overrides[audio_router.get_audio_service] = lambda: service
    headers = auth_header(auth_tokens.admin)

    asr = admin_api_client.post(
        "/admin/audio/speech-to-text",
        headers=headers,
        data={"model_id": "asr-model"},
        files={"file": ("clip.wav", b"audio-data", "audio/wav")},
    )
    tts = admin_api_client.post(
        "/admin/audio/text-to-speech",
        headers=headers,
        json={"text": "hello", "voice": "alloy", "model_id": "tts-model"},
    )
    voices = admin_api_client.get(
        "/admin/audio/voices",
        headers=headers,
        params={"model_id": "tts-model", "language": "en-US"},
    )

    assert asr.status_code == 200
    assert asr.json() == {"text": "recognized text"}
    assert tts.status_code == 200
    assert tts.content == b"onetwo"
    assert tts.headers["content-type"].startswith("audio/mpeg")
    assert voices.status_code == 200
    assert voices.json() == [{"name": "Alloy", "value": "alloy", "language": ["en-US"]}]
    assert service.calls == [
        ("transcribe", b"audio-data", "clip.wav", "audio/wav", "asr-model"),
        ("synthesize", "hello", "alloy", "tts-model"),
        ("voices", "tts-model", "en-US"),
    ]


def test_text_to_speech_uses_process_cache_when_redis_is_unavailable(admin_api_client, auth_tokens, monkeypatch):
    from agentclaw.api.routers.admin import audio as audio_router

    service = FakeAudioService()
    admin_api_client.app.dependency_overrides[audio_router.get_audio_service] = lambda: service
    monkeypatch.setattr(audio_router, "get_database", lambda: None)
    audio_router._memory_tts_cache.clear()
    headers = auth_header(auth_tokens.admin)
    payload = {"text": "cached hello", "voice": "alloy", "model_id": "tts-model"}

    first = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)
    second = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"onetwo"
    assert second.content == b"onetwo"
    assert service.calls == [("synthesize", "cached hello", "alloy", "tts-model")]


def test_text_to_speech_uses_redis_cache_when_available(admin_api_client, auth_tokens, monkeypatch):
    from agentclaw.api.routers.admin import audio as audio_router

    class FakeRedisDb:
        def __init__(self):
            self.values = {}

        def is_redis_available(self):
            return True

        async def redis_get(self, key):
            return self.values.get(key)

        async def redis_set(self, key, value, ex=None):
            self.values[key] = value

    service = FakeAudioService()
    redis_db = FakeRedisDb()
    admin_api_client.app.dependency_overrides[audio_router.get_audio_service] = lambda: service
    monkeypatch.setattr(audio_router, "get_database", lambda: redis_db)
    audio_router._memory_tts_cache.clear()
    headers = auth_header(auth_tokens.admin)
    payload = {"text": "redis hello", "voice": "alloy", "model_id": "tts-model"}

    first = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)
    second = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"onetwo"
    assert second.content == b"onetwo"
    assert service.calls == [("synthesize", "redis hello", "alloy", "tts-model")]


def test_text_to_speech_falls_back_to_process_cache_when_redis_fails(admin_api_client, auth_tokens, monkeypatch):
    from agentclaw.api.routers.admin import audio as audio_router

    class BrokenRedisDb:
        def is_redis_available(self):
            return True

        async def redis_get(self, key):
            raise RuntimeError("redis unavailable")

        async def redis_set(self, key, value, ex=None):
            raise RuntimeError("redis unavailable")

    service = FakeAudioService()
    admin_api_client.app.dependency_overrides[audio_router.get_audio_service] = lambda: service
    monkeypatch.setattr(audio_router, "get_database", lambda: BrokenRedisDb())
    audio_router._memory_tts_cache.clear()
    headers = auth_header(auth_tokens.admin)
    payload = {"text": "fallback hello", "voice": "alloy", "model_id": "tts-model"}

    first = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)
    second = admin_api_client.post("/admin/audio/text-to-speech", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"onetwo"
    assert second.content == b"onetwo"
    assert service.calls == [("synthesize", "fallback hello", "alloy", "tts-model")]
