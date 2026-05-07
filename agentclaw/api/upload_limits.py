"""Shared upload size guards."""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadTooLarge(Exception):
    """Raised when a streamed upload exceeds the configured file limit."""


MULTIPART_OVERHEAD_ALLOWANCE_BYTES = 1024 * 1024
DEFAULT_UPLOAD_CHUNK_SIZE = 1024 * 1024
DEFAULT_REQUEST_BODY_LIMIT_BYTES = 4 * 1024 * 1024


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before route handlers parse them."""

    error_detail = "Request body too large"

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_size: int,
        path_prefixes: Iterable[str] = ("/",),
        excluded_path_prefixes: Iterable[str] = (),
    ):
        self.app = app
        self.limit = max_size
        self.path_prefixes = tuple(path_prefixes)
        self.excluded_path_prefixes = tuple(excluded_path_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._matches_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        if self._content_length_exceeds_limit(scope):
            await self._send_413(send)
            return

        total = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.limit:
                    raise UploadTooLarge()
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except UploadTooLarge:
            if not response_started:
                await self._send_413(send)

    def _matches_path(self, path: str) -> bool:
        included = any(self._prefix_matches(path, prefix) for prefix in self.path_prefixes)
        excluded = any(self._prefix_matches(path, prefix) for prefix in self.excluded_path_prefixes)
        return included and not excluded

    @staticmethod
    def _prefix_matches(path: str, prefix: str) -> bool:
        normalized = prefix.rstrip("/") or "/"
        if normalized == "/":
            return True
        return path == normalized or path.startswith(f"{normalized}/")

    def _content_length_exceeds_limit(self, scope: Scope) -> bool:
        for key, value in scope.get("headers", []):
            if key.lower() != b"content-length":
                continue
            try:
                return int(value.decode("ascii")) > self.limit
            except (TypeError, ValueError, UnicodeDecodeError):
                return False
        return False

    async def _send_413(self, send: Send) -> None:
        body = f'{{"detail":"{self.error_detail}"}}'.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class UploadSizeLimitMiddleware(RequestBodyLimitMiddleware):
    """Reject oversized upload request bodies before route handlers run."""
    error_detail = "File size exceeds limit"

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_size: int,
        path_prefixes: Iterable[str],
        overhead_allowance: int = 0,
    ):
        super().__init__(
            app,
            max_size=max_size + max(0, overhead_allowance),
            path_prefixes=path_prefixes,
        )
        self.max_size = max_size


def enforce_upload_content_length(
    request: Request,
    max_size: int,
    *,
    overhead_allowance: int = MULTIPART_OVERHEAD_ALLOWANCE_BYTES,
) -> None:
    """Reject obviously oversized uploads before reading file bytes."""
    raw = request.headers.get("content-length")
    if not raw:
        return
    try:
        content_length = int(raw)
    except ValueError:
        return
    if content_length > max_size + overhead_allowance:
        raise HTTPException(status_code=413, detail="File size exceeds limit")


async def read_upload_file_limited(
    file: Any,
    max_size: int,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
) -> bytes:
    """Read an UploadFile in chunks and stop as soon as the limit is exceeded."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise UploadTooLarge()
        chunks.append(chunk)
    return b"".join(chunks)
