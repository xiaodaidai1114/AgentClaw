from types import SimpleNamespace

import pytest

from agentclaw.audio.types import AudioStream


pytestmark = pytest.mark.api


class FakeAudioService:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio, model_id=None):
        self.calls.append(("transcribe", audio.data, audio.filename, audio.mime_type, model_id))
        return "public transcript"

    async def synthesize(self, text, voice=None, model_id=None):
        self.calls.append(("synthesize", text, voice, model_id))

        async def chunks():
            yield b"public-audio"

        return AudioStream(chunks=chunks(), mime_type="audio/mpeg", ext="mp3")


def _public_headers() -> dict[str, str]:
    return {
        "origin": "http://testserver",
        "sec-fetch-site": "same-origin",
        "x-agentclaw-public-session": "1",
    }


def _open_public_session(public_api_client, workflow_id: str, share_token: str = "share-test"):
    return public_api_client.post(
        f"/api/public/workflows/{workflow_id}/session",
        params={"share_token": share_token},
        headers={
            "origin": "http://testserver",
            "sec-fetch-site": "same-origin",
        },
    )


def _workflow(**overrides):
    chat_audio = {
        "enabled": True,
        "speech_input_enabled": True,
        "tts_enabled": True,
        "speech2text_model_id": "workflow-asr",
        "tts_model_id": "workflow-tts",
        "tts_voice": "workflow-voice",
    }
    chat_audio.update(overrides.pop("chat_audio", {}) or {})
    return SimpleNamespace(
        id="public-audio",
        name="Public Audio",
        description="",
        welcome="",
        public_share_enabled=True,
        public_share_token="share-test",
        rate_limit=None,
        chat_audio=chat_audio,
        get_input_schema=lambda: None,
        get_form_config=lambda: None,
        get_user_input_field=lambda: "query",
        **overrides,
    )


def test_public_workflow_metadata_exposes_only_public_chat_audio(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )

    response = public_api_client.get(
        "/api/public/workflows/public-audio",
        params={"share_token": "share-test"},
    )

    assert response.status_code == 200
    chat_audio = response.json()["workflow"]["chat_audio"]
    assert chat_audio["enabled"] is True
    assert chat_audio["speech_input_enabled"] is True
    assert chat_audio["tts_enabled"] is True
    assert "speech2text_model_id" not in chat_audio
    assert "tts_model_id" not in chat_audio
    assert "tts_voice" not in chat_audio


def test_public_speech_to_text_requires_public_session(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )

    response = public_api_client.post(
        "/api/public/workflows/public-audio/speech-to-text",
        params={"share_token": "share-test"},
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
        files={"file": ("clip.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 403


def test_public_speech_to_text_uses_workflow_audio_model(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import audio as public_audio_router

    service = FakeAudioService()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )
    public_api_client.app.dependency_overrides[public_audio_router.get_audio_service] = lambda: service

    session = _open_public_session(public_api_client, "public-audio")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/public-audio/speech-to-text",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        files={"file": ("clip.webm", b"audio-data", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "public transcript"}
    assert service.calls == [
        ("transcribe", b"audio-data", "clip.webm", "audio/webm", "workflow-asr")
    ]


def test_public_speech_to_text_rejects_disallowed_mime_type_when_configured(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import audio as public_audio_router

    service = FakeAudioService()
    monkeypatch.setenv("AGENTCLAW_PUBLIC_AUDIO_ALLOWED_MIME_TYPES", "audio/webm,audio/wav")
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )
    public_api_client.app.dependency_overrides[public_audio_router.get_audio_service] = lambda: service

    session = _open_public_session(public_api_client, "public-audio")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/public-audio/speech-to-text",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        files={"file": ("clip.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert service.calls == []


def test_public_speech_to_text_rejects_disallowed_extension_when_configured(
    public_api_client,
    monkeypatch,
):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import audio as public_audio_router

    service = FakeAudioService()
    monkeypatch.setenv("AGENTCLAW_PUBLIC_AUDIO_ALLOWED_EXTENSIONS", ".webm,.wav")
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )
    public_api_client.app.dependency_overrides[public_audio_router.get_audio_service] = lambda: service

    session = _open_public_session(public_api_client, "public-audio")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/public-audio/speech-to-text",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        files={"file": ("clip.txt", b"not-audio", "audio/webm")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert service.calls == []


def test_public_text_to_speech_uses_workflow_model_and_voice(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.routers.public import audio as public_audio_router

    service = FakeAudioService()
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: _workflow() if workflow_id == "public-audio" else None),
    )
    monkeypatch.setattr(public_audio_router, "get_database", lambda: None)
    public_audio_router._memory_tts_cache.clear()
    public_api_client.app.dependency_overrides[public_audio_router.get_audio_service] = lambda: service

    session = _open_public_session(public_api_client, "public-audio")
    assert session.status_code == 200

    response = public_api_client.post(
        "/api/public/workflows/public-audio/text-to-speech",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        json={"text": "hello", "model_id": "browser-model", "voice": "browser-voice"},
    )

    assert response.status_code == 200
    assert response.content == b"public-audio"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert service.calls == [("synthesize", "hello", "workflow-voice", "workflow-tts")]


def test_public_audio_respects_chat_audio_switches(public_api_client, monkeypatch):
    from agentclaw.api.registry import WorkflowRegistry

    workflow = _workflow(chat_audio={"speech_input_enabled": False, "tts_enabled": False})
    monkeypatch.setattr(
        WorkflowRegistry,
        "get",
        classmethod(lambda cls, workflow_id: workflow if workflow_id == "public-audio" else None),
    )

    session = _open_public_session(public_api_client, "public-audio")
    assert session.status_code == 200

    asr = public_api_client.post(
        "/api/public/workflows/public-audio/speech-to-text",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        files={"file": ("clip.webm", b"audio-data", "audio/webm")},
    )
    tts = public_api_client.post(
        "/api/public/workflows/public-audio/text-to-speech",
        params={"share_token": "share-test"},
        headers=_public_headers(),
        json={"text": "hello"},
    )

    assert asr.status_code == 403
    assert tts.status_code == 403
