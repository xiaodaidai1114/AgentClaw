"""Limits for temporary download URL tools."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DOWNLOAD_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
DEFAULT_DOWNLOAD_MAX_TTL_SECONDS = 24 * 60 * 60
DEFAULT_DOWNLOAD_TTL_SECONDS = 3600


def download_max_file_size_bytes() -> int:
    raw_bytes = os.getenv("DOWNLOAD_MAX_FILE_SIZE_BYTES", "").strip()
    if raw_bytes:
        try:
            return max(1, int(raw_bytes))
        except ValueError:
            return DEFAULT_DOWNLOAD_MAX_FILE_SIZE_BYTES

    raw_mb = os.getenv("DOWNLOAD_MAX_FILE_SIZE_MB", "").strip()
    if raw_mb:
        try:
            return max(1, int(float(raw_mb) * 1024 * 1024))
        except ValueError:
            return DEFAULT_DOWNLOAD_MAX_FILE_SIZE_BYTES

    return DEFAULT_DOWNLOAD_MAX_FILE_SIZE_BYTES


def download_max_ttl_seconds() -> int:
    raw = os.getenv("DOWNLOAD_MAX_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_DOWNLOAD_MAX_TTL_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DOWNLOAD_MAX_TTL_SECONDS


def validate_download_file_size(path: Path) -> str | None:
    max_size = download_max_file_size_bytes()
    size = path.stat().st_size
    if size > max_size:
        return f"[ERROR] File size {size} bytes exceeds download limit ({max_size} bytes)"
    return None


def normalize_download_ttl(value: object) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        ttl = DEFAULT_DOWNLOAD_TTL_SECONDS
    return max(1, min(ttl, download_max_ttl_seconds()))
