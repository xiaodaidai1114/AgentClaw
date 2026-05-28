"""Shared same-origin public browser session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time as _time
import threading
from typing import Any, Tuple

from fastapi import Request

from agentclaw.database import get_database
from agentclaw.api.routers.public.access import trust_proxy_headers


PUBLIC_SESSION_COOKIE = "agentclaw_public_session"
PUBLIC_USER_COOKIE = "agentclaw_public_user"
PUBLIC_SESSION_HEADER = "x-agentclaw-public-session"
PUBLIC_SESSION_TTL_SECONDS = 2 * 60 * 60
DEFAULT_PUBLIC_USER_TTL_SECONDS = 30 * 24 * 60 * 60

_public_user_lock = threading.Lock()
_public_users: dict[str, float] = {}
_public_conversation_owners: dict[tuple[str, str], tuple[str, float]] = {}


def request_origin(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto") if trust_proxy_headers() else None
    forwarded_host = request.headers.get("x-forwarded-host") if trust_proxy_headers() else None
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def is_same_origin_public_page_request(request: Request) -> bool:
    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    if sec_fetch_site == "cross-site":
        return False
    if sec_fetch_site and sec_fetch_site not in {"same-origin", "same-site", "none"}:
        return False

    expected_origin = request_origin(request)
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if not origin and not referer:
        return False

    if origin and origin.rstrip("/") != expected_origin:
        return False

    if referer:
        from urllib.parse import urlsplit

        parsed = urlsplit(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if referer_origin != expected_origin:
            return False

    return True


def public_session_signing_secret() -> bytes:
    secret = os.getenv("AGENTCLAW_PUBLIC_SESSION_SECRET", "").strip()
    if not secret:
        from agentclaw.api.auth.token import AdminTokenManager

        secret = AdminTokenManager.get_instance().token
    return secret.encode("utf-8")


def public_user_ttl_seconds() -> int:
    try:
        value = int(os.getenv("AGENTCLAW_PUBLIC_USER_TTL_SECONDS", "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else DEFAULT_PUBLIC_USER_TTL_SECONDS


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def sign_public_session_payload(encoded_payload: str) -> str:
    digest = hmac.new(
        public_session_signing_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64url_encode(digest)


def sign_public_user_id(user_id: str) -> str:
    digest = hmac.new(
        public_session_signing_secret(),
        f"agentclaw-public-user-v1:{user_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def public_user_cookie_value(user_id: str) -> str:
    return f"{user_id}.{sign_public_user_id(user_id)}"


def public_user_id_from_cookie(value: str | None) -> str:
    if not value or "." not in value:
        return ""
    user_id, signature = value.rsplit(".", 1)
    if not user_id or not signature:
        return ""
    if not hmac.compare_digest(signature, sign_public_user_id(user_id)):
        return ""
    return user_id


def public_owner_id_from_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32] if user_id else ""


def _redis_client() -> Any | None:
    try:
        db = get_database()
        if not db:
            return None
        getter = getattr(db, "get_sync_redis_client", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _public_conversation_owner_key(workflow_id: str, conversation_id: str) -> str:
    workflow_key = base64url_encode(workflow_id.encode("utf-8"))
    conversation_key = base64url_encode(conversation_id.encode("utf-8"))
    return f"agentclaw:public-conversation-owner:{workflow_key}:{conversation_key}"


def _register_public_user(user_id: str, ttl_seconds: int | None = None) -> None:
    ttl = ttl_seconds or public_user_ttl_seconds()
    expires_at = _time.time() + ttl
    client = _redis_client()
    if client:
        try:
            key = f"agentclaw:public-user:{user_id}"
            client.setex(key, ttl, json.dumps({"user_id": user_id}, separators=(",", ":")))
        except Exception:
            pass
    with _public_user_lock:
        _public_users[user_id] = expires_at


def _public_user_is_registered(user_id: str) -> bool:
    if not user_id:
        return False
    client = _redis_client()
    if client:
        try:
            key = f"agentclaw:public-user:{user_id}"
            return bool(client.get(key))
        except Exception:
            pass
    with _public_user_lock:
        expires_at = _public_users.get(user_id)
        if not expires_at:
            return False
        if expires_at <= _time.time():
            _public_users.pop(user_id, None)
            return False
        return True


def ensure_public_user_id(request: Request) -> tuple[str, bool]:
    user_id = public_user_id_from_cookie(request.cookies.get(PUBLIC_USER_COOKIE))
    if user_id:
        _register_public_user(user_id)
        return user_id, False
    user_id = f"pu_{secrets.token_urlsafe(24)}"
    _register_public_user(user_id)
    return user_id, True


def public_owner_id_from_request(request: Request) -> str:
    user_id = public_user_id_from_cookie(request.cookies.get(PUBLIC_USER_COOKIE))
    if not _public_user_is_registered(user_id):
        return ""
    return public_owner_id_from_user_id(user_id)


def set_public_user_cookie(response, request: Request, user_id: str) -> None:
    response.set_cookie(
        PUBLIC_USER_COOKIE,
        public_user_cookie_value(user_id),
        max_age=public_user_ttl_seconds(),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api",
    )


def bind_public_conversation_owner(
    workflow_id: str,
    conversation_id: str,
    owner_id: str,
) -> bool:
    if not workflow_id or not conversation_id or not owner_id:
        return False
    ttl = public_user_ttl_seconds()
    key = _public_conversation_owner_key(workflow_id, conversation_id)
    client = _redis_client()
    expires_at = _time.time() + ttl
    if client:
        try:
            existing = client.get(key)
            if isinstance(existing, bytes):
                existing = existing.decode("utf-8")
            if existing and existing != owner_id:
                return False
            client.setex(key, ttl, owner_id)
        except Exception:
            pass
    memory_key = (workflow_id, conversation_id)
    with _public_user_lock:
        existing = _public_conversation_owners.get(memory_key)
        if existing and existing[1] > _time.time() and existing[0] != owner_id:
            return False
        _public_conversation_owners[memory_key] = (owner_id, expires_at)
    return True


def verify_public_conversation_owner(
    workflow_id: str,
    conversation_id: str,
    owner_id: str,
) -> bool:
    if not workflow_id or not conversation_id or not owner_id:
        return False
    key = _public_conversation_owner_key(workflow_id, conversation_id)
    client = _redis_client()
    if client:
        try:
            existing = client.get(key)
            if isinstance(existing, bytes):
                existing = existing.decode("utf-8")
            return not existing or existing == owner_id
        except Exception:
            pass
    memory_key = (workflow_id, conversation_id)
    with _public_user_lock:
        existing = _public_conversation_owners.get(memory_key)
        if not existing:
            return True
        if existing[1] <= _time.time():
            _public_conversation_owners.pop(memory_key, None)
            return True
        return existing[0] == owner_id


def reset_public_user_state() -> None:
    with _public_user_lock:
        _public_users.clear()
        _public_conversation_owners.clear()


def create_public_session(workflow_id: str) -> Tuple[str, int]:
    expires_at = int(_time.time()) + PUBLIC_SESSION_TTL_SECONDS
    payload = {
        "workflow_id": workflow_id,
        "expires_at": expires_at,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded_payload = base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = sign_public_session_payload(encoded_payload)
    return f"{encoded_payload}.{signature}", expires_at


def verify_public_session(request: Request, workflow_id: str) -> bool:
    if request.headers.get(PUBLIC_SESSION_HEADER) != "1":
        return False
    token = request.cookies.get(PUBLIC_SESSION_COOKIE)
    if not token:
        return False
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError:
        return False

    expected_signature = sign_public_session_payload(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        session = json.loads(base64url_decode(encoded_payload))
    except Exception:
        return False

    if session.get("workflow_id") != workflow_id:
        return False
    return float(session.get("expires_at", 0)) > _time.time()


def verify_public_page_session(request: Request, workflow_id: str) -> bool:
    return is_same_origin_public_page_request(request) and verify_public_session(request, workflow_id)
