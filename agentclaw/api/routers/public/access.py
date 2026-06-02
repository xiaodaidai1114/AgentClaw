"""Shared public workflow access controls."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import os
import secrets
import threading
import time
import uuid
from typing import Any, Mapping, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from agentclaw.api.schemas.common import ErrorCode
from agentclaw.database import get_database
from agentclaw.utils.security import safe_compare_digest


PUBLIC_SHARE_TOKEN_QUERY_KEYS = ("share_token", "token")
DEFAULT_PUBLIC_CONVERSATION_LIMIT = 20
DEFAULT_PUBLIC_MESSAGE_LIMIT = 200


@dataclass(frozen=True)
class PublicRateLimit:
    limit: int
    window_seconds: int


_RATE_LIMIT_WINDOWS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "h": 60 * 60,
    "hour": 60 * 60,
    "hours": 60 * 60,
    "d": 24 * 60 * 60,
    "day": 24 * 60 * 60,
    "days": 24 * 60 * 60,
}

_rate_limit_lock = threading.Lock()
_rate_limit_buckets: dict[tuple[str, str, str, str], deque[float]] = {}
_conversation_quota_counts: dict[tuple[str, str, str], int] = {}
_conversation_quota_updated: dict[tuple[str, str, str], float] = {}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or 0)
    except ValueError:
        value = 0
    return value if value > 0 else default


def _public_memory_rate_limit_max_keys() -> int:
    return _env_int("AGENTCLAW_PUBLIC_MEMORY_RATE_LIMIT_MAX_KEYS", 10000)


def _public_memory_rate_limit_ttl_seconds() -> int:
    return _env_int("AGENTCLAW_PUBLIC_MEMORY_RATE_LIMIT_TTL_SECONDS", 24 * 60 * 60)


def _public_memory_conversation_quota_ttl_seconds() -> int:
    return _env_int("AGENTCLAW_PUBLIC_MEMORY_CONVERSATION_QUOTA_TTL_SECONDS", 24 * 60 * 60)


def _public_memory_conversation_quota_max_keys() -> int:
    return _env_int("AGENTCLAW_PUBLIC_MEMORY_CONVERSATION_QUOTA_MAX_KEYS", 10000)


def _trim_rate_limit_buckets(now: float) -> None:
    cutoff = now - _public_memory_rate_limit_ttl_seconds()
    max_keys = _public_memory_rate_limit_max_keys()
    for key in list(_rate_limit_buckets):
        bucket = _rate_limit_buckets[key]
        if not bucket or bucket[-1] <= cutoff:
            _rate_limit_buckets.pop(key, None)
    while len(_rate_limit_buckets) > max_keys:
        _rate_limit_buckets.pop(next(iter(_rate_limit_buckets)), None)


def _trim_conversation_quota_counts(now: float) -> None:
    ttl = _public_memory_conversation_quota_ttl_seconds()
    cutoff = now - ttl
    for key, updated_at in list(_conversation_quota_updated.items()):
        if updated_at <= cutoff:
            _conversation_quota_updated.pop(key, None)
            _conversation_quota_counts.pop(key, None)
    max_keys = _public_memory_conversation_quota_max_keys()
    while len(_conversation_quota_counts) > max_keys:
        key = next(iter(_conversation_quota_counts))
        _conversation_quota_counts.pop(key, None)
        _conversation_quota_updated.pop(key, None)


def trust_proxy_headers() -> bool:
    return os.getenv("AGENTCLAW_TRUST_PROXY_HEADERS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def public_rate_limit_backend() -> str:
    value = os.getenv("AGENTCLAW_PUBLIC_RATE_LIMIT_BACKEND", "memory").strip().lower()
    return value if value in {"memory", "redis", "auto"} else "memory"


def public_rate_limit_redis_required() -> bool:
    return os.getenv("AGENTCLAW_PUBLIC_RATE_LIMIT_REDIS_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def default_public_rate_limit() -> str:
    return os.getenv("AGENTCLAW_PUBLIC_DEFAULT_RATE_LIMIT", "30/min").strip()


def forbidden_response(error: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": error, "code": ErrorCode.FORBIDDEN},
    )


def rate_limited_response(retry_after: int = 60) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "Public rate limit exceeded", "code": "RATE_LIMITED"},
        headers={"Retry-After": str(max(1, retry_after))},
    )


def is_builtin_workflow(workflow: Any, workflow_id: str) -> bool:
    return (
        workflow_id == "__builtin__"
        or getattr(workflow, "id", None) == "__builtin__"
        or bool(getattr(workflow, "is_builtin", False))
    )


def workflow_not_found_response(workflow_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": f"Workflow '{workflow_id}' not found", "code": ErrorCode.WORKFLOW_NOT_FOUND},
    )


def is_public_share_enabled(workflow: Any, workflow_id: str) -> bool:
    return bool(workflow) and not is_builtin_workflow(workflow, workflow_id) and bool(
        getattr(workflow, "public_share_enabled", False)
    )


def ensure_public_share_token(workflow: Any) -> str:
    token = str(getattr(workflow, "public_share_token", "") or "").strip()
    if not token:
        token = secrets.token_urlsafe(24)
        setattr(workflow, "public_share_token", token)
    return token


def public_share_token_from_request(
    request: Request,
    body: Optional[Mapping[str, Any]] = None,
) -> str:
    header_value = request.headers.get("x-agentclaw-share-token", "")
    if header_value:
        return header_value
    for key in PUBLIC_SHARE_TOKEN_QUERY_KEYS:
        value = request.query_params.get(key)
        if value:
            return value
    if body:
        for key in PUBLIC_SHARE_TOKEN_QUERY_KEYS:
            value = body.get(key)
            if value:
                return str(value)
    return ""


def _constant_time_token_match(expected: str, supplied: str) -> bool:
    if not expected or not supplied:
        return False
    return safe_compare_digest(expected, supplied)


def verify_public_share_token(
    workflow: Any,
    workflow_id: str,
    request: Request,
    body: Optional[Mapping[str, Any]] = None,
) -> JSONResponse | None:
    if not is_public_share_enabled(workflow, workflow_id):
        return workflow_not_found_response(workflow_id)
    expected = str(getattr(workflow, "public_share_token", "") or "").strip()
    supplied = public_share_token_from_request(request, body)
    if not _constant_time_token_match(expected, supplied):
        return forbidden_response("Public workflow share token is required")
    return None


def parse_public_rate_limit(raw: Any) -> Optional[PublicRateLimit]:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    normalized = value.replace(" per ", "/").replace(" ", "")
    count_text = normalized
    unit = "min"
    if "/" in normalized:
        count_text, unit = normalized.split("/", 1)
    try:
        limit = int(count_text)
    except ValueError:
        return None
    if limit <= 0:
        return None
    window_seconds = _RATE_LIMIT_WINDOWS.get(unit)
    if not window_seconds:
        return None
    return PublicRateLimit(limit=limit, window_seconds=window_seconds)


def _client_identity(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "") if trust_proxy_headers() else ""
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _session_identity(request: Request) -> str:
    from agentclaw.api.routers.public.session import PUBLIC_SESSION_COOKIE

    token = request.cookies.get(PUBLIC_SESSION_COOKIE, "")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else "anon"


def check_public_rate_limit(workflow: Any, workflow_id: str, request: Request, action: str) -> JSONResponse | None:
    raw_limit = getattr(workflow, "rate_limit", None) or default_public_rate_limit()
    parsed = parse_public_rate_limit(raw_limit)
    if not parsed:
        return None
    redis_result = _check_public_rate_limit_redis(workflow_id, request, action, parsed)
    if redis_result is True:
        return None
    if redis_result is not None:
        return redis_result
    now = time.monotonic()
    key = (workflow_id, action, _client_identity(request), _session_identity(request))
    with _rate_limit_lock:
        _trim_rate_limit_buckets(now)
        bucket = _rate_limit_buckets.setdefault(key, deque())
        cutoff = now - parsed.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= parsed.limit:
            retry_after = int(max(1, parsed.window_seconds - (now - bucket[0]))) if bucket else parsed.window_seconds
            return rate_limited_response(retry_after)
        bucket.append(now)
        _trim_rate_limit_buckets(now)
    return None


def _check_public_rate_limit_redis(
    workflow_id: str,
    request: Request,
    action: str,
    parsed: PublicRateLimit,
) -> JSONResponse | bool | None:
    backend = public_rate_limit_backend()
    if backend == "memory":
        return None
    try:
        db = get_database()
        if not db:
            if backend == "redis" or public_rate_limit_redis_required():
                return JSONResponse(
                    status_code=503,
                    content={"error": "Redis is required for public rate limiting", "code": "RATE_LIMIT_UNAVAILABLE"},
                )
            return None
        client_getter = getattr(db, "get_sync_redis_client", None)
        client = client_getter() if callable(client_getter) else None
        if not client:
            if backend == "redis" or public_rate_limit_redis_required():
                return JSONResponse(
                    status_code=503,
                    content={"error": "Redis is required for public rate limiting", "code": "RATE_LIMIT_UNAVAILABLE"},
                )
            return None
        now = time.time()
        key = "agentclaw:public-rate:" + ":".join(
            (
                workflow_id,
                action,
                _client_identity(request),
                _session_identity(request),
            )
        )
        cutoff = now - parsed.window_seconds
        client.zremrangebyscore(key, 0, cutoff)
        count = int(client.zcard(key))
        if count >= parsed.limit:
            return rate_limited_response(parsed.window_seconds)
        client.zadd(key, {uuid.uuid4().hex: now})
        client.expire(key, parsed.window_seconds)
        return True
    except Exception:
        if backend == "redis" or public_rate_limit_redis_required():
            return JSONResponse(
                status_code=503,
                content={"error": "Redis is required for public rate limiting", "code": "RATE_LIMIT_UNAVAILABLE"},
            )
        return None


def public_conversation_limit(workflow: Any) -> int:
    try:
        value = int(getattr(workflow, "public_conversation_limit", DEFAULT_PUBLIC_CONVERSATION_LIMIT) or 0)
    except (TypeError, ValueError):
        return DEFAULT_PUBLIC_CONVERSATION_LIMIT
    return value if value > 0 else DEFAULT_PUBLIC_CONVERSATION_LIMIT


def public_message_limit(workflow: Any) -> int:
    try:
        value = int(getattr(workflow, "public_message_limit", DEFAULT_PUBLIC_MESSAGE_LIMIT) or 0)
    except (TypeError, ValueError):
        return DEFAULT_PUBLIC_MESSAGE_LIMIT
    return value if value > 0 else DEFAULT_PUBLIC_MESSAGE_LIMIT


def validate_public_message_quota(workflow: Any, messages: Optional[list[Any]]) -> JSONResponse | None:
    if messages is None:
        return None
    if len(messages) > public_message_limit(workflow):
        return JSONResponse(
            status_code=429,
            content={"error": "Public conversation message quota exceeded", "code": "RATE_LIMITED"},
        )
    return None


def check_public_conversation_quota(workflow: Any, workflow_id: str, request: Request) -> JSONResponse | None:
    key = (workflow_id, _client_identity(request), _session_identity(request))
    limit = public_conversation_limit(workflow)
    now = time.monotonic()
    with _rate_limit_lock:
        _trim_conversation_quota_counts(now)
        used = _conversation_quota_counts.get(key, 0)
        if used >= limit:
            return JSONResponse(
                status_code=429,
                content={"error": "Public conversation quota exceeded", "code": "RATE_LIMITED"},
            )
        _conversation_quota_counts[key] = used + 1
        _conversation_quota_updated[key] = now
        _trim_conversation_quota_counts(now)
    return None


def reset_public_rate_limiter() -> None:
    with _rate_limit_lock:
        _rate_limit_buckets.clear()
        _conversation_quota_counts.clear()
        _conversation_quota_updated.clear()
    try:
        from agentclaw.api.routers.public.session import reset_public_user_state

        reset_public_user_state()
    except Exception:
        pass
