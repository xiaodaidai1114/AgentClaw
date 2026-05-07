"""FastAPI authentication dependencies for public-facing API routes."""

from __future__ import annotations

from dataclasses import dataclass, field
import hmac
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from agentclaw.api.auth.token import AdminTokenManager, WorkflowAPIKeyManager


@dataclass(frozen=True)
class AuthPrincipal:
    """Authenticated caller identity.

    user_id and tenant_id are intentionally reserved for a future multi-user
    edition. The current personal edition authenticates by token/key only.
    """

    subject: str
    auth_type: str
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    scopes: tuple[str, ...] = field(default_factory=tuple)


AUTH_ERROR_MESSAGE = (
    "Invalid or missing API Key. Add header: Authorization: Bearer {api_key}"
)


def extract_bearer_token(request: Request) -> Optional[str]:
    """Extract a Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    scheme, separator, token = auth_header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


async def authenticate_bearer(request: Request) -> AuthPrincipal:
    """Authenticate an Admin Token or Workflow API Key from a request."""
    token = extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=AUTH_ERROR_MESSAGE,
            headers={"WWW-Authenticate": "Bearer"},
        )

    admin_token_manager = AdminTokenManager.get_instance()
    if admin_token_manager.verify(token):
        return AuthPrincipal(
            subject="admin",
            auth_type="admin",
            scopes=("admin",),
        )

    workflow_api_key_manager = WorkflowAPIKeyManager.get_instance()
    if workflow_api_key_manager.verify(token):
        return AuthPrincipal(
            subject="workflow-api-key",
            auth_type="workflow",
            scopes=("workflow",),
        )

    raise HTTPException(
        status_code=401,
        detail=AUTH_ERROR_MESSAGE,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate_workflow_or_admin_bearer(
    request: Request,
    *,
    workflow: object = None,
    workflow_id: Optional[str] = None,
) -> AuthPrincipal:
    """Authenticate Admin Token, global Workflow API Key, or this workflow's API key."""
    try:
        return await authenticate_bearer(request)
    except HTTPException:
        token = extract_bearer_token(request)
        workflow_key = str(getattr(workflow, "workflow_api_key", "") or "").strip()
        if token and workflow_key and hmac.compare_digest(token, workflow_key):
            return AuthPrincipal(
                subject=f"workflow:{workflow_id or getattr(workflow, 'id', '')}",
                auth_type="workflow",
                scopes=("workflow",),
            )
        raise


async def require_bearer_auth(request: Request) -> AuthPrincipal:
    """FastAPI dependency requiring Admin Token or Workflow API Key auth."""
    return await authenticate_bearer(request)


async def require_workflow_or_admin_auth(request: Request) -> AuthPrincipal:
    """FastAPI dependency allowing workflow execution keys or Admin Token."""
    return await authenticate_bearer(request)


async def require_admin_auth(request: Request) -> AuthPrincipal:
    """FastAPI dependency requiring the Admin Token specifically."""
    principal = await authenticate_bearer(request)
    if principal.auth_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin token required",
        )
    return principal


def authentication_failed_response() -> JSONResponse:
    """Dify-compatible auth error response for workflow execution endpoints."""
    return JSONResponse(
        status_code=401,
        content={
            "error": "Authentication failed",
            "code": "unauthorized",
            "message": AUTH_ERROR_MESSAGE,
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
