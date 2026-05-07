from pathlib import Path

import pytest

from agentclaw import cli


pytestmark = pytest.mark.unit


def test_init_project_copies_docker_compose(tmp_path: Path):
    cli._init_project(tmp_path, silent=True)

    compose_path = tmp_path / "docker-compose.yml"
    bundled_compose = (Path(cli.__file__).parent / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose_path.exists()
    assert compose_path.read_text(encoding="utf-8") == bundled_compose


def test_init_project_does_not_overwrite_existing_docker_compose(tmp_path: Path):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("name: custom\n", encoding="utf-8")

    cli._init_project(tmp_path, silent=True)

    assert compose_path.read_text(encoding="utf-8") == "name: custom\n"
