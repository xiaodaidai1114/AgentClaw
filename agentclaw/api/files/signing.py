"""Short-lived signed URLs for browser-rendered stored files."""

from __future__ import annotations

import hmac
import time
from hashlib import sha256
from urllib.parse import quote, urlencode

from agentclaw.api.auth.token import AdminTokenManager


DEFAULT_FILE_URL_TTL_SECONDS = 3600


def _signing_secret() -> bytes:
    return AdminTokenManager.get_instance().token.encode("utf-8")


def _signature(file_id: str, expires_at: int) -> str:
    payload = f"agentclaw-file-v1:{file_id}:{expires_at}".encode("utf-8")
    return hmac.new(_signing_secret(), payload, sha256).hexdigest()


def create_file_access_token(
    file_id: str,
    *,
    ttl_seconds: int = DEFAULT_FILE_URL_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Create a short-lived URL token scoped to one stored file id."""
    current = time.time() if now is None else now
    expires_at = int(current + max(1, ttl_seconds))
    return f"{expires_at}.{_signature(file_id, expires_at)}"


def verify_file_access_token(
    file_id: str,
    token: str | None,
    *,
    now: float | None = None,
) -> bool:
    """Verify a file URL token without accepting it for any other file id."""
    if not token or "." not in token:
        return False
    expires_raw, provided_sig = token.split(".", 1)
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if expires_at < int(current):
        return False
    expected_sig = _signature(file_id, expires_at)
    return hmac.compare_digest(provided_sig, expected_sig)


def get_signed_file_url(
    file_id: str,
    *,
    ttl_seconds: int = DEFAULT_FILE_URL_TTL_SECONDS,
    download: bool | None = None,
) -> str:
    """Return a browser-embeddable file URL that does not need Bearer auth."""
    query = {"token": create_file_access_token(file_id, ttl_seconds=ttl_seconds)}
    if download is not None:
        query["download"] = "true" if download else "false"
    return f"/api/files/{quote(file_id, safe='')}?{urlencode(query)}"
