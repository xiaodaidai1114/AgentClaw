from types import SimpleNamespace

import pytest

from agentclaw.api.files import signing


pytestmark = pytest.mark.unit


def _patch_signing_secret(monkeypatch, secret: str = "admin-test-secret") -> None:
    class FakeAdminTokenManager:
        token = secret

    monkeypatch.setattr(
        signing,
        "AdminTokenManager",
        SimpleNamespace(get_instance=lambda: FakeAdminTokenManager()),
    )


def test_file_access_token_is_scoped_to_file_id(monkeypatch):
    _patch_signing_secret(monkeypatch)

    token = signing.create_file_access_token("file-1", ttl_seconds=60, now=1000)

    assert signing.verify_file_access_token("file-1", token, now=1000)
    assert not signing.verify_file_access_token("file-2", token, now=1000)


def test_file_access_token_expires_after_boundary(monkeypatch):
    _patch_signing_secret(monkeypatch)

    token = signing.create_file_access_token("file-1", ttl_seconds=1, now=1000)

    assert signing.verify_file_access_token("file-1", token, now=1001)
    assert not signing.verify_file_access_token("file-1", token, now=1002)


def test_file_access_token_rejects_malformed_tokens(monkeypatch):
    _patch_signing_secret(monkeypatch)

    assert not signing.verify_file_access_token("file-1", None)
    assert not signing.verify_file_access_token("file-1", "missing-dot")
    assert not signing.verify_file_access_token("file-1", "not-int.signature")


def test_signed_file_url_quotes_file_id_and_download_flag(monkeypatch):
    _patch_signing_secret(monkeypatch)

    url = signing.get_signed_file_url("folder/file 1", ttl_seconds=60, download=True)

    assert url.startswith("/api/files/folder%2Ffile%201?")
    assert "download=true" in url
    assert "token=" in url
