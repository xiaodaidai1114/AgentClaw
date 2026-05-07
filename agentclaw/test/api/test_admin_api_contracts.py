from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentclaw.test.conftest import auth_header


pytestmark = pytest.mark.api


def test_admin_health_is_public(admin_api_client):
    response = admin_api_client.get("/admin/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "admin"}


def test_admin_routes_require_admin_token(admin_api_client):
    response = admin_api_client.get("/admin/workflows")

    assert response.status_code == 401


def test_admin_auth_verify_contract(admin_api_client, auth_tokens):
    valid = admin_api_client.post("/admin/auth/verify", json={"token": auth_tokens.admin})
    invalid = admin_api_client.post("/admin/auth/verify", json={"token": "wrong"})

    assert valid.status_code == 200
    assert valid.json() == {"valid": True}
    assert invalid.status_code == 200
    assert invalid.json() == {"valid": False}


def test_admin_dashboard_stats_uses_service_dependency(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import dashboard as dashboard_router

    class FakeDashboardService:
        async def get_dashboard_stats(self):
            return {
                "workflow_count": 2,
                "execution_count_24h": 5,
                "success_rate": 0.8,
                "avg_duration_ms": 123.4,
                "running_count": 1,
            }

    admin_api_client.app.dependency_overrides[
        dashboard_router.get_dashboard_service
    ] = lambda: FakeDashboardService()

    response = admin_api_client.get(
        "/admin/dashboard/stats",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert response.json()["workflow_count"] == 2
    assert response.json()["running_count"] == 1


def test_admin_workflows_list_uses_service_dependency(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import workflows as workflows_router

    calls = []

    class FakeWorkflowService:
        async def list_workflows_with_stats(self, include_builtin=False, time_range="24h"):
            calls.append({"include_builtin": include_builtin, "time_range": time_range})
            return [
                {
                    "id": "wf-1",
                    "name": "Workflow 1",
                    "version": "1.0.0",
                    "description": "demo",
                    "node_count": 3,
                    "is_builtin": bool(include_builtin),
                }
            ]

    admin_api_client.app.dependency_overrides[
        workflows_router.get_workflow_service
    ] = lambda: FakeWorkflowService()

    response = admin_api_client.get(
        "/admin/workflows?include_builtin=true&time_range=7d",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert calls == [{"include_builtin": True, "time_range": "7d"}]
    assert response.json()["workflows"][0]["id"] == "wf-1"
    assert response.json()["workflows"][0]["is_builtin"] is True


def test_admin_traces_list_uses_service_dependency(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import traces as traces_router

    class FakeTraceService:
        async def list_traces(self, **kwargs):
            return {
                "traces": [
                    {
                        "id": "trace-1",
                        "workflow_id": "wf-1",
                        "thread_id": "thread-1",
                        "name": "run",
                        "status": "success",
                        "duration_ms": 10,
                        "start_time": datetime.now(timezone.utc),
                    }
                ],
                "total": 1,
                "page": kwargs["page"],
                "limit": kwargs["limit"],
            }

    admin_api_client.app.dependency_overrides[
        traces_router.get_trace_service
    ] = lambda: FakeTraceService()

    response = admin_api_client.get(
        "/admin/traces?page=1&limit=10",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["traces"][0]["conversation_id"] == "thread-1"


def test_admin_settings_env_uses_service_dependency(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import settings as settings_router

    class FakeSettingsService:
        def get_env_reference(self):
            return {"sections": [{"title": "Server", "variables": []}]}

        def update_env(self, payload):
            return {"updated": sorted(payload.get("values", {}))}

    admin_api_client.app.dependency_overrides[
        settings_router.get_settings_service
    ] = lambda: FakeSettingsService()

    get_response = admin_api_client.get(
        "/admin/settings/env",
        headers=auth_header(auth_tokens.admin),
    )
    put_response = admin_api_client.put(
        "/admin/settings/env",
        headers=auth_header(auth_tokens.admin),
        json={"values": {"PORT": "9001"}},
    )

    assert get_response.status_code == 200
    assert get_response.json()["sections"][0]["title"] == "Server"
    assert put_response.status_code == 200
    assert put_response.json()["updated"] == ["PORT"]


def test_admin_settings_models_uses_service_dependency(admin_api_client, auth_tokens):
    from agentclaw.api.routers.admin import settings as settings_router

    class FakeSettingsService:
        def get_models_config(self):
            return {"default": "primary", "models": [{"id": "primary", "api_key": "***"}]}

        def update_models_config(self, payload):
            return {"default": payload["default"], "hot_reloaded": True, "models": payload["models"]}

    admin_api_client.app.dependency_overrides[
        settings_router.get_settings_service
    ] = lambda: FakeSettingsService()

    get_response = admin_api_client.get(
        "/admin/settings/models",
        headers=auth_header(auth_tokens.admin),
    )
    put_response = admin_api_client.put(
        "/admin/settings/models",
        headers=auth_header(auth_tokens.admin),
        json={"default": "secondary", "models": [{"id": "secondary", "model": "gpt-4.1"}]},
    )

    assert get_response.status_code == 200
    assert get_response.json()["models"][0]["api_key"] == "***"
    assert put_response.status_code == 200
    assert put_response.json()["default"] == "secondary"
    assert put_response.json()["hot_reloaded"] is True


def test_admin_tasks_list_contract(admin_api_client, auth_tokens):
    response = admin_api_client.get(
        "/admin/tasks",
        headers=auth_header(auth_tokens.admin),
    )

    assert response.status_code == 200
    assert "tasks" in response.json()
