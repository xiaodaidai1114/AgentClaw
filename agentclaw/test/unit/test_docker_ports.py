from pathlib import Path

import pytest

from agentclaw import cli


pytestmark = pytest.mark.unit


def test_docker_compose_uses_env_configurable_host_ports():
    compose = (Path(__file__).resolve().parents[2] / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"${PG_PORT:-5432}:5432"' in compose
    assert '"${REDIS_PORT:-6379}:6379"' in compose
    assert '"${MINIO_API_PORT:-9000}:9000"' in compose
    assert '"${MINIO_CONSOLE_PORT:-9001}:9001"' in compose
    assert '"${MILVUS_PORT:-19530}:19530"' in compose
    assert '"${MILVUS_HTTP_PORT:-9091}:9091"' in compose
    assert '"${ADMINER_PORT:-8080}:8080"' in compose


def test_docker_env_vars_include_all_infra_port_defaults(monkeypatch):
    for key in (
        "PG_PORT",
        "REDIS_PORT",
        "MILVUS_PORT",
        "MILVUS_HTTP_PORT",
        "MINIO_API_PORT",
        "MINIO_CONSOLE_PORT",
        "ADMINER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)

    env_vars = cli._docker_env_vars()

    assert env_vars["PG_PORT"] == "5432"
    assert env_vars["REDIS_PORT"] == "6379"
    assert env_vars["MINIO_API_PORT"] == "9000"
    assert env_vars["MINIO_CONSOLE_PORT"] == "9001"
    assert env_vars["MILVUS_PORT"] == "19530"
    assert env_vars["MILVUS_HTTP_PORT"] == "9091"
    assert env_vars["ADMINER_PORT"] == "8080"


def test_docker_env_vars_keep_custom_infra_ports(monkeypatch):
    monkeypatch.setenv("PG_PORT", "6003")
    monkeypatch.setenv("REDIS_PORT", "6004")
    monkeypatch.setenv("MINIO_API_PORT", "19000")
    monkeypatch.setenv("MINIO_CONSOLE_PORT", "19001")
    monkeypatch.setenv("MILVUS_PORT", "19531")
    monkeypatch.setenv("MILVUS_HTTP_PORT", "9092")
    monkeypatch.setenv("ADMINER_PORT", "18080")

    env_vars = cli._docker_env_vars()

    assert env_vars["PG_PORT"] == "6003"
    assert env_vars["REDIS_PORT"] == "6004"
    assert env_vars["MINIO_API_PORT"] == "19000"
    assert env_vars["MINIO_CONSOLE_PORT"] == "19001"
    assert env_vars["MILVUS_PORT"] == "19531"
    assert env_vars["MILVUS_HTTP_PORT"] == "9092"
    assert env_vars["ADMINER_PORT"] == "18080"
    assert env_vars["MILVUS_URI"] == "http://127.0.0.1:19531"
