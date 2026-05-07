from pathlib import Path

import pytest

from agentclaw.mcp.download_limits import (
    DEFAULT_DOWNLOAD_TTL_SECONDS,
    normalize_download_ttl,
    validate_download_file_size,
)


pytestmark = pytest.mark.unit


def test_normalize_download_ttl_clamps_to_configured_max(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_MAX_TTL_SECONDS", "30")

    assert normalize_download_ttl(120) == 30
    assert normalize_download_ttl(0) == 1
    assert normalize_download_ttl("bad") == 30


def test_normalize_download_ttl_falls_back_when_max_is_invalid(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_MAX_TTL_SECONDS", "not-a-number")

    assert normalize_download_ttl("not-a-number") == DEFAULT_DOWNLOAD_TTL_SECONDS


def test_validate_download_file_size_uses_byte_limit(tmp_path: Path, monkeypatch):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"123456")
    monkeypatch.setenv("DOWNLOAD_MAX_FILE_SIZE_BYTES", "5")

    error = validate_download_file_size(path)

    assert error is not None
    assert "exceeds download limit" in error


def test_validate_download_file_size_allows_exact_limit(tmp_path: Path, monkeypatch):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"12345")
    monkeypatch.setenv("DOWNLOAD_MAX_FILE_SIZE_BYTES", "5")

    assert validate_download_file_size(path) is None
