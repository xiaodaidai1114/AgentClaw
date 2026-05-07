from pathlib import Path
import tomllib


def test_pypi_distribution_name_keeps_agentclaw_import_and_cli():
    project_root = Path(__file__).resolve().parents[3]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "agentclaw-ai"
    package_include = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert any(pattern == "agentclaw" or pattern.startswith("agentclaw*") for pattern in package_include)
    assert pyproject["project"]["scripts"]["agentclaw"] == "agentclaw.cli:main"
