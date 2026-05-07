"""HTTP security headers for dashboard and API responses."""

from __future__ import annotations

import os
from starlette.types import ASGIApp, Message, Receive, Scope, Send


DEFAULT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; "
    "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "font-src 'self' data:"
)


SECURITY_HEADERS = {
    "content-security-policy": DEFAULT_CONTENT_SECURITY_POLICY,
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class SecurityHeadersMiddleware:
    """Add a conservative baseline of browser security headers."""

    def __init__(self, app: ASGIApp, *, csp: str | None = None):
        self.app = app
        self.headers = dict(SECURITY_HEADERS)
        self.headers["content-security-policy"] = (
            csp
            or os.getenv("AGENTCLAW_CONTENT_SECURITY_POLICY", "").strip()
            or DEFAULT_CONTENT_SECURITY_POLICY
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {
                    key.decode("latin-1").lower()
                    for key, _value in message.get("headers", [])
                }
                headers = list(message.get("headers", []))
                for name, value in self.headers.items():
                    if name not in existing:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
