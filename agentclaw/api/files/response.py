"""Helpers for browser-safe file download responses."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

SAFE_INLINE_MIME_TYPES = {
    "application/json",
    "application/pdf",
    "text/csv",
    "text/plain",
}

SAFE_INLINE_IMAGE_MIME_TYPES = {
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _base_content_type(content_type: str | None) -> str:
    return (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()


def is_browser_safe_inline_type(content_type: str | None) -> bool:
    """Return whether the MIME type is safe to render inline on the app origin."""
    base = _base_content_type(content_type)
    return base in SAFE_INLINE_MIME_TYPES or base in SAFE_INLINE_IMAGE_MIME_TYPES


def _safe_filename_parts(filename: str | None) -> tuple[str, str]:
    raw = str(filename or "file")
    # Treat CR/LF as hostile header separators and discard anything after them.
    safe_utf8 = re.split(r"[\r\n]", raw, maxsplit=1)[0].strip() or "file"
    safe_utf8 = "".join(ch for ch in safe_utf8 if ch.isprintable()) or "file"

    ascii_name = unicodedata.normalize("NFKD", safe_utf8).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r'[\x00-\x1f\x7f"\\;/]', "_", ascii_name).strip(" ._")
    ascii_name = re.sub(r"\s+", " ", ascii_name) or "file"
    return ascii_name, quote(safe_utf8, safe="")


def content_disposition_header(filename: str | None, disposition: str = "attachment") -> str:
    """Build an RFC 5987-compatible Content-Disposition header."""
    disposition = "inline" if disposition == "inline" else "attachment"
    ascii_name, encoded_name = _safe_filename_parts(filename)
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def file_response_headers(
    filename: str | None,
    content_type: str | None,
    *,
    download: bool = False,
) -> dict[str, str]:
    disposition = "attachment" if download or not is_browser_safe_inline_type(content_type) else "inline"
    return {
        "Content-Disposition": content_disposition_header(filename, disposition),
        "X-Content-Type-Options": "nosniff",
    }
