import logging
from pathlib import Path

from agentclaw.api.server import AgentClawServer
from agentclaw.logger.config import get_current_log_file


def _flush_agentclaw_log_handlers() -> None:
    for handler in logging.getLogger("agentclaw").handlers:
        handler.flush()


def test_server_run_writes_startup_log_file_location_to_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTCLAW_LOG_FILE", str(tmp_path / "logs" / "agentclaw.log"))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    server = AgentClawServer(enable_admin=False, host="127.0.0.1", port=8765)
    server._load_config = lambda: None
    server._create_app = lambda: object()

    server.run()
    _flush_agentclaw_log_handlers()

    log_file = Path(get_current_log_file())
    content = log_file.read_text(encoding="utf-8")

    assert "启动服务器: http://127.0.0.1:8765" in content
    assert f"日志文件: {log_file}" in content
