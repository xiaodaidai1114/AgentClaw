from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentclaw.api.files import signing


pytestmark = pytest.mark.integration


def _client_for_files_router(monkeypatch, *, mime_type: str, original_name: str, data: bytes):
    from agentclaw.api.routers.public import files as files_router

    class FakeAdminTokenManager:
        token = "admin-test-secret"

    class FakeStorage:
        async def find_by_id(self, file_id: str):
            assert file_id == "file-1"
            return SimpleNamespace(mime_type=mime_type, original_name=original_name)

        async def get_file_bytes(self, file_id: str) -> bytes:
            assert file_id == "file-1"
            return data

    monkeypatch.setattr(
        signing,
        "AdminTokenManager",
        SimpleNamespace(get_instance=lambda: FakeAdminTokenManager()),
    )
    monkeypatch.setattr(files_router, "get_file_storage", lambda: FakeStorage())

    app = FastAPI()
    app.include_router(files_router.router, prefix="/api")
    return TestClient(app)


def test_signed_file_url_downloads_without_bearer_header(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="image/png",
        original_name="chart.png",
        data=b"png-data",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    response = client.get(f"/api/files/file-1?token={token}")

    assert response.status_code == 200
    assert response.content == b"png-data"
    assert response.headers["content-disposition"].startswith("inline;")


def test_signed_file_url_forces_active_content_to_attachment(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="text/html",
        original_name="page.html",
        data=b"<script>alert(1)</script>",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    response = client.get(f"/api/files/file-1?token={token}")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_file_download_requires_valid_signed_token_or_bearer(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="text/plain",
        original_name="secret.txt",
        data=b"secret",
    )

    response = client.get("/api/files/file-1?token=bad-token")

    assert response.status_code == 403


def test_signed_file_url_rejects_expired_token(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="image/png",
        original_name="chart.png",
        data=b"png-data",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=1, now=1000)
    monkeypatch.setattr(signing.time, "time", lambda: 1002)

    response = client.get(f"/api/files/file-1?token={token}")

    assert response.status_code == 403


def test_signed_file_url_rejects_token_for_another_file(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="image/png",
        original_name="chart.png",
        data=b"png-data",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    response = client.get(f"/api/files/file-2?token={token}")

    assert response.status_code == 403


def test_download_query_forces_attachment_even_for_inline_safe_types(monkeypatch):
    client = _client_for_files_router(
        monkeypatch,
        mime_type="image/png",
        original_name="chart.png",
        data=b"png-data",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    response = client.get(f"/api/files/file-1?download=true&token={token}")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")


def test_file_download_reports_503_when_storage_is_unavailable(monkeypatch):
    from agentclaw.api.routers.public import files as files_router

    client = _client_for_files_router(
        monkeypatch,
        mime_type="text/plain",
        original_name="hello.txt",
        data=b"hello",
    )
    monkeypatch.setattr(files_router, "get_file_storage", lambda: None)
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    response = client.get(f"/api/files/file-1?token={token}")

    assert response.status_code == 503
    assert response.json()["detail"] == "File storage not available"


def test_file_download_reports_404_when_metadata_or_content_is_missing(monkeypatch):
    from agentclaw.api.routers.public import files as files_router

    class MissingMetadataStorage:
        async def find_by_id(self, file_id: str):
            return None

        async def get_file_bytes(self, file_id: str) -> bytes:
            raise AssertionError("content should not be read when metadata is missing")

    class MissingContentStorage:
        async def find_by_id(self, file_id: str):
            return SimpleNamespace(mime_type="text/plain", original_name="hello.txt")

        async def get_file_bytes(self, file_id: str):
            return None

    client = _client_for_files_router(
        monkeypatch,
        mime_type="text/plain",
        original_name="hello.txt",
        data=b"hello",
    )
    token = signing.create_file_access_token("file-1", ttl_seconds=60)

    monkeypatch.setattr(files_router, "get_file_storage", lambda: MissingMetadataStorage())
    missing_metadata = client.get(f"/api/files/file-1?token={token}")

    monkeypatch.setattr(files_router, "get_file_storage", lambda: MissingContentStorage())
    missing_content = client.get(f"/api/files/file-1?token={token}")

    assert missing_metadata.status_code == 404
    assert missing_metadata.json()["detail"] == "File not found"
    assert missing_content.status_code == 404
    assert missing_content.json()["detail"] == "File content not found"
