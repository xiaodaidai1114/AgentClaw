from __future__ import annotations

from pathlib import Path
import importlib

import pytest

from agentclaw.graph.context import WorkflowContext
from agentclaw.database.file_storage import FileStorage
from agentclaw.database.storage_backend import LocalStorageBackend
from agentclaw.node.document import DocumentNode


pytestmark = pytest.mark.unit
document_module = importlib.import_module("agentclaw.node.document")


class FakeAudioService:
    def __init__(self, text: str = "转写文本"):
        self.text = text
        self.calls = []

    async def transcribe(self, audio, model_id=None):
        self.calls.append((audio, model_id))
        return self.text


@pytest.mark.asyncio
async def test_document_node_transcribes_audio_file_metadata(tmp_path: Path):
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"audio bytes")
    service = FakeAudioService("你好，世界")
    node = DocumentNode(
        id="parse_audio",
        input_key="document",
        output_key="content",
        asr_model_id="asr-demo",
        audio_service=service,
    )

    state = await node.execute(
        {
            "document": {
                "file_path": str(audio_path),
                "original_name": "recording.wav",
                "mime_type": "audio/wav",
                "size": audio_path.stat().st_size,
            }
        },
        WorkflowContext(thread_id="doc-asr"),
    )

    assert state["content"] == "你好，世界"
    assert len(service.calls) == 1
    artifact, model_id = service.calls[0]
    assert model_id == "asr-demo"
    assert artifact.data == b"audio bytes"
    assert artifact.mime_type == "audio/wav"
    assert artifact.filename == "recording.wav"
    assert artifact.ext == ".wav"


@pytest.mark.asyncio
async def test_document_node_transcribes_audio_storage_key(tmp_path: Path, monkeypatch):
    upload_root = tmp_path / "storage"
    audio_path = upload_root / "uploads" / "voice.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"stored audio bytes")
    service = FakeAudioService("storage key text")
    storage = FileStorage(backend=LocalStorageBackend(upload_root))
    monkeypatch.setattr(document_module, "get_file_storage", lambda: storage)
    node = DocumentNode(
        id="parse_audio",
        input_key="document",
        output_key="content",
        asr_model_id="asr-demo",
        audio_service=service,
    )

    state = await node.execute(
        {
            "document": {
                "file_path": "uploads/voice.mp3",
                "original_name": "voice.mp3",
                "mime_type": "audio/mpeg",
                "size": audio_path.stat().st_size,
            }
        },
        WorkflowContext(thread_id="doc-asr-storage-key"),
    )

    assert state["content"] == "storage key text"
    assert len(service.calls) == 1
    artifact, model_id = service.calls[0]
    assert model_id == "asr-demo"
    assert artifact.data == b"stored audio bytes"
    assert artifact.filename == "voice.mp3"
    assert artifact.ext == ".mp3"


@pytest.mark.asyncio
async def test_document_node_keeps_markitdown_for_non_audio_files(tmp_path: Path, monkeypatch):
    document_path = tmp_path / "notes.txt"
    document_path.write_text("plain text", encoding="utf-8")
    service = FakeAudioService("should not be used")
    node = DocumentNode(
        id="parse_doc",
        input_key="document",
        output_key="content",
        asr_model_id="asr-demo",
        audio_service=service,
    )

    class FakeMarkItDown:
        def convert(self, path):
            assert path == str(document_path)
            return type("Result", (), {"text_content": "markdown content"})()

    monkeypatch.setattr(document_module, "_get_markitdown", lambda: FakeMarkItDown())

    state = await node.execute(
        {"document": {"file_path": str(document_path), "mime_type": "text/plain"}},
        WorkflowContext(thread_id="doc-markitdown"),
    )

    assert state["content"] == "markdown content"
    assert service.calls == []


@pytest.mark.asyncio
async def test_document_node_combines_audio_and_document_results(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "voice.webm"
    doc_path = tmp_path / "report.pdf"
    audio_path.write_bytes(b"audio bytes")
    doc_path.write_bytes(b"%PDF")
    service = FakeAudioService("audio text")
    node = DocumentNode(
        id="parse_files",
        input_key="files",
        output_key="content",
        asr_model_id="asr-demo",
        audio_service=service,
    )

    class FakeMarkItDown:
        def convert(self, path):
            assert path == str(doc_path)
            return type("Result", (), {"text_content": "document text"})()

    monkeypatch.setattr(document_module, "_get_markitdown", lambda: FakeMarkItDown())

    state = await node.execute(
        {
            "files": [
                {"file_path": str(audio_path), "original_name": "voice.webm", "mime_type": "audio/webm"},
                {"file_path": str(doc_path), "original_name": "report.pdf", "mime_type": "application/pdf"},
            ]
        },
        WorkflowContext(thread_id="doc-mixed"),
    )

    assert state["content"] == "audio text\n\n---\n\ndocument text"
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_document_node_returns_parse_failure_when_asr_fails(tmp_path: Path):
    audio_path = tmp_path / "broken.mp3"
    audio_path.write_bytes(b"audio bytes")

    class FailingAudioService:
        async def transcribe(self, audio, model_id=None):
            raise RuntimeError("asr unavailable")

    node = DocumentNode(
        id="parse_audio",
        input_key="document",
        output_key="content",
        asr_model_id="asr-demo",
        audio_service=FailingAudioService(),
    )

    state = await node.execute(
        {"document": {"file_path": str(audio_path), "mime_type": "audio/mpeg"}},
        WorkflowContext(thread_id="doc-asr-fail"),
    )

    assert state["content"] == "[解析失败: asr unavailable]"
