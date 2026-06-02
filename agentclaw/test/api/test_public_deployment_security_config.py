from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _route_paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_server_security_env_defaults_keep_existing_route_surface(monkeypatch, tmp_path: Path):
    from agentclaw.api.server import AgentClawServer

    for name in (
        "AGENTCLAW_ENABLE_ADMIN_API",
        "AGENTCLAW_ENABLE_DASHBOARD",
        "AGENTCLAW_DASHBOARD_MODE",
        "AGENTCLAW_ENABLE_MCP_ROUTES",
        "AGENTCLAW_ENABLE_SCHEDULER_API",
        "AGENTCLAW_ENABLE_CHANNEL_ROUTES",
        "AGENTCLAW_ENABLE_API_DOCS",
    ):
        monkeypatch.delenv(name, raising=False)

    dashboard_dir = tmp_path / "dashboard"
    (dashboard_dir / "dist" / "assets").mkdir(parents=True)
    (dashboard_dir / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

    server = AgentClawServer(enable_admin=False)
    server.enable_admin = False
    server.enable_admin_dashboard = True
    server.admin_dashboard_dir = dashboard_dir

    app = server.app
    paths = _route_paths(app)

    assert "/docs" in paths
    assert "/openapi.json" in paths
    assert "/mcp" in paths
    assert "/api/scheduler/jobs" in paths
    assert "/api/channels/{channel_name}/webhook" in paths
    assert "/dashboard/{path:path}" in paths


def test_server_security_env_can_disable_non_public_routes(monkeypatch, tmp_path: Path):
    from agentclaw.api.server import AgentClawServer

    monkeypatch.setenv("AGENTCLAW_ENABLE_ADMIN_API", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_DASHBOARD", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_MCP_ROUTES", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_SCHEDULER_API", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_CHANNEL_ROUTES", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_API_DOCS", "false")

    server = AgentClawServer(enable_admin=True)
    server.admin_dashboard_dir = tmp_path / "missing-dashboard"

    app = server.app
    paths = _route_paths(app)

    assert "/docs" not in paths
    assert "/openapi.json" not in paths
    assert "/mcp" not in paths
    assert "/api/scheduler/jobs" not in paths
    assert "/api/channels/{channel_name}/webhook" not in paths
    assert "/admin/health" not in paths
    assert "/dashboard/{path:path}" not in paths
    assert "/api/public/workflows/{workflow_id}/run" in paths


def test_dashboard_public_chat_mode_only_serves_chat_spa_paths(monkeypatch, tmp_path: Path):
    from agentclaw.api.server import AgentClawServer

    monkeypatch.setenv("AGENTCLAW_ENABLE_ADMIN_API", "false")
    monkeypatch.setenv("AGENTCLAW_ENABLE_DASHBOARD", "true")
    monkeypatch.setenv("AGENTCLAW_DASHBOARD_MODE", "public-chat")

    dashboard_dir = tmp_path / "dashboard"
    assets_dir = dashboard_dir / "dist" / "assets"
    assets_dir.mkdir(parents=True)
    (dashboard_dir / "dist" / "index.html").write_text("<html>public chat</html>", encoding="utf-8")

    server = AgentClawServer(enable_admin=True)
    server.admin_dashboard_dir = dashboard_dir

    client = TestClient(server.app)

    chat = client.get("/dashboard/agent/wf-1")
    legacy_chat = client.get("/dashboard/workflows/wf-1/chat")
    settings = client.get("/dashboard/settings")

    assert chat.status_code == 200
    assert legacy_chat.status_code == 404
    assert settings.status_code == 404


def test_server_cors_env_overrides_default_origins(monkeypatch):
    from agentclaw.api.server import AgentClawServer

    monkeypatch.setenv("AGENTCLAW_CORS_ORIGINS", "https://a.example, https://b.example")

    server = AgentClawServer(enable_admin=False)

    assert server.cors_origins == ["https://a.example", "https://b.example"]


def test_global_exception_handler_does_not_return_exception_message(monkeypatch):
    from agentclaw.api.server import AgentClawServer

    server = AgentClawServer(enable_admin=False)
    app = FastAPI()
    server._register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    payload = response.json()
    assert payload == {
        "error": "服务器内部错误",
        "code": "UNKNOWN_ERROR",
    }
    assert "secret internal detail" not in response.text
