from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentclaw.api.server import AgentClawServer


def test_dashboard_assets_use_long_cache_while_spa_entry_stays_no_cache(tmp_path):
    dist_path = tmp_path / "dist"
    assets_path = dist_path / "assets"
    assets_path.mkdir(parents=True)
    (dist_path / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (assets_path / "app-abc123.js").write_text("console.log('dashboard')", encoding="utf-8")

    server = AgentClawServer(enable_admin=False)
    server.admin_dashboard_dir = str(tmp_path)
    app = FastAPI()
    server._mount_admin_dashboard(app)

    client = TestClient(app)
    asset_response = client.get("/dashboard/assets/app-abc123.js")
    entry_response = client.get("/dashboard")

    assert asset_response.status_code == 200
    assert asset_response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "pragma" not in asset_response.headers
    assert "expires" not in asset_response.headers
    assert entry_response.status_code == 200
    assert entry_response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
