import pytest

from agentclaw.api.services import audio_synthesis


pytestmark = pytest.mark.unit


def test_memory_tts_cache_evicts_by_encoded_byte_size(monkeypatch):
    audio_synthesis.clear_memory_tts_cache()
    monkeypatch.setattr(audio_synthesis, "MEMORY_TTS_CACHE_MAX_ITEMS", 100)
    first = audio_synthesis.encode_cached_audio(b"a" * 32, "audio/mpeg", "mp3")
    second = audio_synthesis.encode_cached_audio(b"b" * 32, "audio/mpeg", "mp3")
    monkeypatch.setattr(
        audio_synthesis,
        "MEMORY_TTS_CACHE_MAX_BYTES",
        max(len(first.encode("utf-8")), len(second.encode("utf-8"))) + 1,
        raising=False,
    )

    audio_synthesis.set_memory_tts_cache("first", first)
    audio_synthesis.set_memory_tts_cache("second", second)

    assert audio_synthesis.get_memory_tts_cache("first") is None
    assert audio_synthesis.get_memory_tts_cache("second") == (b"b" * 32, "audio/mpeg")
