from pathlib import Path
from types import SimpleNamespace

import pytest

from agentclaw.config import KnowledgeBaseConfig
from agentclaw.knowledgebase.models import KnowledgeBaseRecord, KnowledgeDocumentRecord
from agentclaw.knowledgebase.parser import DocumentParseError, MarkItDownParser
from agentclaw.knowledgebase.service import KnowledgeBaseService
from agentclaw.knowledgebase.storage import KnowledgeBaseStorage


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_docx_with_non_zip_content_reports_clear_parse_error(tmp_path: Path):
    fake_docx = tmp_path / "not-really.docx"
    fake_docx.write_text("this is plain text with a docx suffix", encoding="utf-8")

    with pytest.raises(DocumentParseError) as exc_info:
        await MarkItDownParser().parse(str(fake_docx))

    message = str(exc_info.value)
    assert "not-really.docx" in message
    assert "文件扩展名是 .docx" in message
    assert "内容不是有效的 Office Open XML" in message


@pytest.mark.asyncio
async def test_upload_document_marks_invalid_docx_as_failed_with_readable_error(tmp_path: Path, monkeypatch):
    from agentclaw.database import file_storage as file_storage_module

    monkeypatch.setattr(file_storage_module, "get_file_storage", lambda: None)
    monkeypatch.setattr(
        file_storage_module,
        "resolve_allowed_legacy_file_path",
        lambda file_path: Path(file_path).resolve(),
    )

    class FakeStore:
        def __init__(self):
            self.document = None

        async def get_knowledgebase(self, knowledgebase_id):
            return KnowledgeBaseRecord(id=knowledgebase_id, name="Docs")

        async def create_document(self, record):
            self.document = record
            return record

        async def update_document(self, document_id, updates):
            assert self.document and self.document.id == document_id
            self.document = KnowledgeDocumentRecord(
                **{
                    **self.document.__dict__,
                    **updates,
                }
            )
            return self.document

    store = FakeStore()
    service = KnowledgeBaseService(
        store=store,
        storage=KnowledgeBaseStorage(tmp_path / "storage", tmp_path / "parsed"),
        parser=MarkItDownParser(),
        model_gateway=SimpleNamespace(),
        retrieval_backend=SimpleNamespace(),
        config=KnowledgeBaseConfig(),
    )

    record = await service.upload_document(
        knowledgebase_id="kb-1",
        data=b"this is not a zip file",
        filename="broken.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert record.status == "failed"
    assert "broken.docx" in record.error
    assert "内容不是有效的 Office Open XML" in record.error


@pytest.mark.asyncio
async def test_upload_document_can_defer_indexing_and_return_processing(tmp_path: Path, monkeypatch):
    from agentclaw.database import file_storage as file_storage_module

    monkeypatch.setattr(file_storage_module, "get_file_storage", lambda: None)
    monkeypatch.setattr(
        file_storage_module,
        "resolve_allowed_legacy_file_path",
        lambda file_path: Path(file_path).resolve(),
    )

    class FakeStore:
        def __init__(self):
            self.document = None

        async def get_knowledgebase(self, knowledgebase_id):
            return KnowledgeBaseRecord(id=knowledgebase_id, name="Docs")

        async def create_document(self, record):
            self.document = record
            return record

        async def update_document(self, document_id, updates):
            raise AssertionError("deferred upload should not update the document during upload")

    class ParserThatMustNotRun:
        async def parse(self, *_args, **_kwargs):
            raise AssertionError("deferred upload should not parse before the response is returned")

    store = FakeStore()
    service = KnowledgeBaseService(
        store=store,
        storage=KnowledgeBaseStorage(tmp_path / "storage", tmp_path / "parsed"),
        parser=ParserThatMustNotRun(),
        model_gateway=SimpleNamespace(),
        retrieval_backend=SimpleNamespace(),
        config=KnowledgeBaseConfig(),
    )

    record = await service.upload_document(
        knowledgebase_id="kb-1",
        data=b"hello",
        filename="hello.txt",
        mime_type="text/plain",
        index_now=False,
    )

    assert record.status == "processing"
    assert record.error == ""
    assert store.document is record


@pytest.mark.asyncio
async def test_reindex_document_marks_invalid_docx_as_failed_with_readable_error(tmp_path: Path, monkeypatch):
    from agentclaw.database import file_storage as file_storage_module

    monkeypatch.setattr(file_storage_module, "get_file_storage", lambda: None)
    monkeypatch.setattr(
        file_storage_module,
        "resolve_allowed_legacy_file_path",
        lambda file_path: Path(file_path).resolve(),
    )

    broken_path = tmp_path / "broken.docx"
    broken_path.write_bytes(b"this is not a zip file")

    class FakeStore:
        def __init__(self):
            self.knowledgebase = KnowledgeBaseRecord(id="kb-1", name="Docs")
            self.document = KnowledgeDocumentRecord(
                id="doc-1",
                knowledgebase_id="kb-1",
                original_name="broken.docx",
                stored_path=str(broken_path),
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=broken_path.stat().st_size,
                file_hash="hash",
                status="ready",
            )

        async def get_document(self, document_id):
            return self.document if document_id == self.document.id else None

        async def get_knowledgebase(self, knowledgebase_id):
            return self.knowledgebase if knowledgebase_id == self.knowledgebase.id else None

        async def update_document(self, document_id, updates):
            assert document_id == self.document.id
            self.document = KnowledgeDocumentRecord(
                **{
                    **self.document.__dict__,
                    **updates,
                }
            )
            return self.document

    store = FakeStore()
    service = KnowledgeBaseService(
        store=store,
        storage=KnowledgeBaseStorage(tmp_path / "storage", tmp_path / "parsed"),
        parser=MarkItDownParser(),
        model_gateway=SimpleNamespace(),
        retrieval_backend=SimpleNamespace(),
        config=KnowledgeBaseConfig(),
    )

    record = await service.reindex_document("doc-1")

    assert record.status == "failed"
    assert "broken.docx" in record.error
    assert "内容不是有效的 Office Open XML" in record.error
