import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentclaw.config import AgentClawConfig, KnowledgeBaseConfig, ProjectConfig, UploadConfig
from agentclaw.database.file_storage import FileStorage
from agentclaw.database.storage_backend import LocalStorageBackend, is_safe_storage_key


pytestmark = pytest.mark.unit


def _patch_allowed_roots(monkeypatch, tmp_path: Path):
    upload_root = tmp_path / "uploads"
    kb_root = tmp_path / "knowledgebase"
    kb_cache_root = tmp_path / "knowledgebase-cache"
    upload_root.mkdir()
    kb_root.mkdir()
    kb_cache_root.mkdir()
    config = AgentClawConfig(
        upload=UploadConfig(upload_dir=str(upload_root)),
        knowledgebase=KnowledgeBaseConfig(
            storage_dir=str(kb_root),
            parser_cache_dir=str(kb_cache_root),
        ),
        project=ProjectConfig(project_dir=tmp_path),
    )
    monkeypatch.setattr(AgentClawConfig, "_instance", config)
    return upload_root, kb_root, kb_cache_root


@pytest.mark.asyncio
async def test_legacy_absolute_file_paths_must_stay_inside_allowed_roots(
    tmp_path,
    monkeypatch,
):
    upload_root, kb_root, kb_cache_root = _patch_allowed_roots(monkeypatch, tmp_path)
    storage = FileStorage(backend=LocalStorageBackend(upload_root))
    allowed = upload_root / "legacy.txt"
    allowed.write_bytes(b"inside")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")

    assert await storage._read_file(str(allowed)) == b"inside"
    assert await storage._resolve_local_path(str(kb_root)) == str(kb_root.resolve())
    assert await storage._read_file(str(outside)) is None
    assert await storage._resolve_local_path(str(outside)) is None
    assert outside.read_bytes() == b"outside"
    assert kb_cache_root.exists()


@pytest.mark.asyncio
async def test_legacy_absolute_file_path_migrates_to_storage_key_on_read(
    tmp_path,
    monkeypatch,
):
    upload_root, _, _ = _patch_allowed_roots(monkeypatch, tmp_path)
    legacy = upload_root / "legacy.txt"
    legacy.write_bytes(b"legacy content")
    expected_hash = hashlib.sha256(b"legacy content").hexdigest()
    updates: list[tuple[str, str]] = []

    class FakeDB:
        pg_pool = object()

        async def pg_execute(self, query, storage_key, file_id):
            assert "UPDATE files SET file_path" in query
            updates.append((storage_key, file_id))

    storage = FileStorage(db=FakeDB(), backend=LocalStorageBackend(upload_root))
    stored = SimpleNamespace(
        id="file-1",
        original_name="legacy.txt",
        file_path=str(legacy),
        file_hash=expected_hash,
        mime_type="text/plain",
        size=len(b"legacy content"),
    )

    async def find_by_id(file_id):
        assert file_id == "file-1"
        return stored

    monkeypatch.setattr(storage, "find_by_id", find_by_id)

    data = await storage.get_file_bytes("file-1")

    assert data == b"legacy content"
    assert updates == [(f"uploads/{expected_hash}.txt", "file-1")]
    assert await storage.backend.get(f"uploads/{expected_hash}.txt") == b"legacy content"


@pytest.mark.asyncio
async def test_absolute_delete_paths_are_contained_to_allowed_roots(tmp_path, monkeypatch):
    upload_root, _, _ = _patch_allowed_roots(monkeypatch, tmp_path)
    storage = FileStorage(backend=LocalStorageBackend(upload_root))
    allowed = upload_root / "delete-me.txt"
    allowed.write_bytes(b"ok")
    outside = tmp_path / "do-not-delete.txt"
    outside.write_bytes(b"secret")

    assert await storage.delete_by_key(str(outside)) is False
    assert outside.exists()
    assert await storage.delete_by_key(str(allowed)) is True
    assert not allowed.exists()


@pytest.mark.asyncio
async def test_local_storage_backend_rejects_path_traversal_keys(tmp_path):
    backend = LocalStorageBackend(tmp_path / "storage")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")

    with pytest.raises(ValueError):
        await backend.save("../outside.txt", b"overwrite")

    assert await backend.get("../outside.txt") is None
    assert await backend.delete("../outside.txt") is False
    assert await backend.exists("../outside.txt") is False
    assert backend.get_local_path("../outside.txt") is None
    assert outside.read_bytes() == b"secret"


def test_storage_key_validator_rejects_absolute_and_traversal_keys():
    assert is_safe_storage_key("uploads/file.txt") is True
    assert is_safe_storage_key("knowledgebase/kb-1/doc.md") is True
    assert is_safe_storage_key("../outside.txt") is False
    assert is_safe_storage_key("/tmp/outside.txt") is False
    assert is_safe_storage_key("uploads/../../outside.txt") is False
    assert is_safe_storage_key("") is False


@pytest.mark.asyncio
async def test_knowledgebase_asset_delete_containment(tmp_path, monkeypatch):
    from agentclaw.database import file_storage as file_storage_module
    from agentclaw.knowledgebase.storage import KnowledgeBaseStorage

    _, kb_root, kb_cache_root = _patch_allowed_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(file_storage_module, "get_file_storage", lambda: None)
    storage = KnowledgeBaseStorage(root_dir=kb_root, parsed_dir=kb_cache_root)
    inside_doc = kb_root / "kb-1" / "doc.txt"
    inside_doc.parent.mkdir()
    inside_doc.write_text("inside", encoding="utf-8")
    outside_doc = tmp_path / "outside-doc.txt"
    outside_doc.write_text("outside", encoding="utf-8")

    await storage.delete_document_assets(str(outside_doc), "")
    assert outside_doc.exists()

    await storage.delete_document_assets(str(inside_doc), "")
    assert not inside_doc.exists()


@pytest.mark.asyncio
async def test_knowledgebase_legacy_stored_path_migrates_to_storage_key(
    tmp_path,
    monkeypatch,
):
    from agentclaw.database import file_storage as file_storage_module
    from agentclaw.knowledgebase.models import KnowledgeBaseRecord, KnowledgeDocumentRecord
    from agentclaw.knowledgebase.service import KnowledgeBaseService

    upload_root, kb_root, kb_cache_root = _patch_allowed_roots(monkeypatch, tmp_path)
    legacy = kb_root / "kb-1" / "legacy.txt"
    legacy.parent.mkdir()
    legacy.write_bytes(b"knowledge legacy")
    expected_hash = hashlib.sha256(b"knowledge legacy").hexdigest()
    file_storage = FileStorage(backend=LocalStorageBackend(upload_root))
    monkeypatch.setattr(file_storage_module, "get_file_storage", lambda: file_storage)
    updates: list[tuple[str, dict]] = []

    class FakeStore:
        async def update_document(self, document_id, payload):
            updates.append((document_id, payload))
            return KnowledgeDocumentRecord(
                id=document_id,
                knowledgebase_id="kb-1",
                original_name="legacy.txt",
                stored_path=payload["stored_path"],
                mime_type=payload["mime_type"],
                size=payload["size"],
                file_hash=payload["file_hash"],
            )

    service = KnowledgeBaseService(
        store=FakeStore(),
        storage=SimpleNamespace(),
        parser=SimpleNamespace(),
        model_gateway=SimpleNamespace(),
        retrieval_backend=SimpleNamespace(),
        config=KnowledgeBaseConfig(),
    )
    kb = KnowledgeBaseRecord(id="kb-1", name="KB")
    document = KnowledgeDocumentRecord(
        id="doc-1",
        knowledgebase_id="kb-1",
        original_name="legacy.txt",
        stored_path=str(legacy),
        mime_type="text/plain",
    )

    migrated = await service._migrate_legacy_document_stored_path(kb, document)

    expected_key = f"knowledgebase/kb-1/{expected_hash}.txt"
    assert migrated.stored_path == expected_key
    assert updates == [
        (
            "doc-1",
            {
                "stored_path": expected_key,
                "file_hash": expected_hash,
                "mime_type": "text/plain",
                "size": len(b"knowledge legacy"),
            },
        )
    ]
    assert await file_storage.backend.get(expected_key) == b"knowledge legacy"
    assert kb_cache_root.exists()
