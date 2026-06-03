from pathlib import Path


def test_project_config_discover_prefers_explicit_project_dir_env(monkeypatch, tmp_path: Path):
    from agentclaw.config import ProjectConfig

    cwd_project = tmp_path / "repo"
    explicit_project = tmp_path / "demo2"
    cwd_project.mkdir()
    explicit_project.mkdir()
    (cwd_project / "server.py").write_text("", encoding="utf-8")
    (cwd_project / ".env").write_text("PORT=8000\n", encoding="utf-8")
    (explicit_project / "server.py").write_text("", encoding="utf-8")
    (explicit_project / ".env").write_text("PORT=8123\n", encoding="utf-8")

    monkeypatch.chdir(cwd_project)
    monkeypatch.setenv("AGENTCLAW_PROJECT_DIR", str(explicit_project))

    project = ProjectConfig.discover()

    assert project.project_dir == explicit_project.resolve()
    assert project.env_file == (explicit_project / ".env").resolve()
