from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ADMIN_TOKEN = "admin-token"
WORKFLOW_KEY = "workflow-key"


class FakeAdminTokenManager:
    token = ADMIN_TOKEN

    def verify(self, token: str) -> bool:
        return token == ADMIN_TOKEN


class FakeWorkflowAPIKeyManager:
    api_key = WORKFLOW_KEY

    def verify(self, token: str) -> bool:
        return token == WORKFLOW_KEY


@pytest.fixture
def auth_tokens(monkeypatch):
    """Patch all request-time auth entry points to stable test credentials."""
    fake_admin = FakeAdminTokenManager()
    fake_workflow = FakeWorkflowAPIKeyManager()

    from agentclaw.api.auth import dependencies as auth_deps
    from agentclaw.api.auth import middleware as auth_middleware
    from agentclaw.api.routers.admin import auth as admin_auth

    monkeypatch.setattr(
        auth_deps,
        "AdminTokenManager",
        SimpleNamespace(get_instance=lambda: fake_admin),
    )
    monkeypatch.setattr(
        auth_deps,
        "WorkflowAPIKeyManager",
        SimpleNamespace(get_instance=lambda: fake_workflow),
    )
    monkeypatch.setattr(
        auth_middleware,
        "AdminTokenManager",
        SimpleNamespace(get_instance=lambda: fake_admin),
    )
    monkeypatch.setattr(
        admin_auth,
        "AdminTokenManager",
        SimpleNamespace(get_instance=lambda: fake_admin),
    )
    return SimpleNamespace(admin=ADMIN_TOKEN, workflow=WORKFLOW_KEY)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def public_api_client(auth_tokens):
    from agentclaw.api.routers.public.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def admin_api_client(auth_tokens):
    from agentclaw.api.auth.middleware import AuthMiddleware
    from agentclaw.api.routers.admin.router import router

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(AuthMiddleware)
    return TestClient(app)
