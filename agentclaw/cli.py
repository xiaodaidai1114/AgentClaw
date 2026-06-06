"""
AgentClaw CLI - 命令行工具

Commands:
  serve  启动 HTTP 服务器
  init   初始化新项目
  up     启动基础设施 + 服务器
"""

import os
import sys
import socket
import time
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional

from .platform_compat import apply_windows_selector_event_loop_policy

apply_windows_selector_event_loop_policy()

import click

from agentclaw import __version__
from agentclaw.env_config import build_data_dir_env_vars, render_env_file, resolve_data_dir


@click.group()
@click.version_option(version=__version__, prog_name="agentclaw")
def cli():
    """AgentClaw - 轻量级 AI Agent 框架 CLI"""
    pass


def _generate_admin_token() -> str:
    import secrets

    return f"ac-admin-{secrets.token_hex(16)}"


def _generate_workflow_api_key() -> str:
    import secrets

    return f"sk-{secrets.token_hex(24)}"


def _generate_mcp_token() -> str:
    import secrets

    return f"mcp-{secrets.token_urlsafe(32)}"


_PLACEHOLDER_ENV_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "FALLBACK_API_KEY",
    "ADMIN_TOKEN",
    "WORKFLOW_API_KEY",
    "MCP_TOKEN",
}

_PLACEHOLDER_ENV_VALUES = {
    "your-admin-token",
    "your-api-key",
    "your-api-key-here",
    "your-openai-api-key",
    "your-anthropic-api-key",
    "your-azure-openai-api-key",
    "sk-your-api-key",
    "sk-your-openai-api-key",
    "sk-your-anthropic-api-key",
    "sk-your-azure-openai-api-key",
    "sk-your-workflow-key",
    "mcp-your-token",
    "your-mcp-token",
    "<your-api-key>",
}


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _is_placeholder_env_value(value: str) -> bool:
    normalized = _strip_env_quotes(value).lower()
    return normalized in _PLACEHOLDER_ENV_VALUES


def _comment_placeholder_env_values(content: str) -> tuple[str, bool]:
    """将 .env 中处于生效状态的占位密钥注释掉，避免误当真实配置加载。"""
    changed = False
    output_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            if key.strip() in _PLACEHOLDER_ENV_KEYS and _is_placeholder_env_value(value):
                indent = line[: len(line) - len(line.lstrip())]
                output_lines.append(f"{indent}# {stripped}")
                changed = True
                continue
        output_lines.append(line)

    return "\n".join(output_lines), changed


def _build_default_env_content(
    admin_token: Optional[str] = None,
    workflow_api_key: Optional[str] = None,
    mcp_token: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
) -> str:
    env_overrides = {key: value for key, value in dict(overrides or {}).items() if value != ""}
    admin_token = admin_token or env_overrides.get("ADMIN_TOKEN") or _generate_admin_token()
    workflow_api_key = workflow_api_key or env_overrides.get("WORKFLOW_API_KEY") or _generate_workflow_api_key()
    mcp_token = mcp_token or env_overrides.get("MCP_TOKEN") or _generate_mcp_token()
    overrides = {
        **env_overrides,
        "ADMIN_TOKEN": admin_token,
        "WORKFLOW_API_KEY": workflow_api_key,
        "MCP_TOKEN": mcp_token,
    }
    content = render_env_file(overrides)
    content, _ = _comment_placeholder_env_values(content)
    return content if content.endswith("\n") else content + "\n"


def _ensure_default_env(project_path: Path, silent: bool = False) -> None:
    env_file = project_path / ".env"
    if env_file.exists():
        return
    env_file.write_text(_build_default_env_content(), encoding="utf-8")
    if not silent:
        click.echo(f"✅ 创建默认环境变量: {env_file}")


def _load_project_env(project_path: Path) -> None:
    """在导入项目 server.py 前加载项目 .env"""
    env_file = project_path / ".env"
    if not env_file.exists():
        return
    content = env_file.read_text(encoding="utf-8")
    sanitized, changed = _comment_placeholder_env_values(content)
    if changed:
        env_file.write_text(sanitized.rstrip() + "\n", encoding="utf-8")
        click.secho(f"⚠️  已注释 .env 中的占位值；模型 API Key 请在 models.json 配置: {env_file}", fg="yellow")

    from dotenv import load_dotenv

    load_dotenv(env_file)


def _read_active_env_file_values(project_path: Path) -> dict[str, str]:
    """读取项目 .env 中已经生效的 KEY=VALUE。注释行不计入。"""
    env_file = project_path / ".env"
    if not env_file.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _strip_env_quotes(value)
    return values


def _get_existing_env_value(project_path: Path, key: str) -> str:
    """读取现有配置值：当前进程环境优先，其次项目 .env。占位值视为未配置。"""
    value = os.getenv(key, "").strip()
    if value and not _is_placeholder_env_value(value):
        return value

    file_value = _read_active_env_file_values(project_path).get(key, "").strip()
    if file_value and not _is_placeholder_env_value(file_value):
        return file_value
    return ""


def _resolve_server_port(port: Optional[int]) -> int:
    """统一解析 server 端口：CLI 显式参数 > .env PORT > 8000。"""
    if port is not None:
        os.environ["PORT"] = str(port)
        return port

    raw_port = (os.getenv("PORT") or "8000").strip() or "8000"
    try:
        resolved = int(raw_port)
    except ValueError as exc:
        raise click.ClickException(f"PORT 必须是整数，当前值: {raw_port!r}") from exc

    os.environ["PORT"] = str(resolved)
    return resolved


def _resolve_server_host(host: Optional[str]) -> str:
    """统一解析 server host：CLI 显式参数 > .env HOST > 0.0.0.0。"""
    resolved = (host or os.getenv("HOST") or "0.0.0.0").strip() or "0.0.0.0"
    os.environ["HOST"] = resolved
    return resolved


def _resolve_project_log_file(project_path: Path) -> Path:
    """解析当前项目应使用的主日志基础路径。"""
    raw_log_file = os.getenv("AGENTCLAW_LOG_FILE") or os.getenv("LOG_FILE")
    if raw_log_file:
        path = Path(raw_log_file).expanduser()
        return path if path.is_absolute() else project_path / path

    data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser() / "logs" / "agentclaw.log"

    return project_path / "logs" / "agentclaw.log"


def _migrate_models_config_if_needed(project_path: Path) -> None:
    """将旧版 models dict 配置迁移为新版 models list 配置"""
    import json

    models_path = project_path / "models.json"
    if not models_path.exists():
        return

    try:
        config = json.loads(models_path.read_text(encoding="utf-8"))
    except Exception as exc:
        click.secho(f"⚠️  models.json 读取失败，跳过自动迁移: {exc}", fg="yellow")
        return

    models = config.get("models") if isinstance(config, dict) else None
    if not isinstance(models, dict):
        return

    migrated_models = []
    for model_id, model_data in models.items():
        if isinstance(model_data, str):
            item = {"id": model_id, "model": model_data}
        elif isinstance(model_data, dict):
            item = dict(model_data)
            item.setdefault("id", model_id)
        else:
            click.secho(f"⚠️  models.json 中模型 {model_id!r} 格式异常，跳过自动迁移", fg="yellow")
            return

        if "channel" not in item and item.get("provider"):
            item["channel"] = item["provider"]
        migrated_models.append(item)

    config["models"] = migrated_models
    models_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    click.secho(f"✓ 已将 models.json 迁移为新版 models list 格式: {models_path}", fg="green")


@cli.command()
@click.option("-p", "--port", type=int, default=None, help="端口号；未指定时读取 .env 中的 PORT，默认 8000")
@click.option("-h", "--host", default=None, help="主机地址；未指定时读取 .env 中的 HOST，默认 0.0.0.0")
@click.option("-d", "--project-dir", default=".", help="项目目录（包含 server.py）")
@click.option("-w", "--workers", default=1, help="工作进程数")
@click.option("--reload", is_flag=True, help="开发模式，热重载")
def serve(port: Optional[int], host: Optional[str], project_dir: str, workers: int, reload: bool):
    """启动 HTTP 服务器"""
    import importlib.util
    from agentclaw.logger.config import setup_logging

    project_path = Path(project_dir).expanduser().resolve()
    server_py = project_path / "server.py"

    # 检查 server.py 是否存在
    if not server_py.exists():
        click.echo(f"❌ 未找到 server.py: {server_py}", err=True)
        click.echo("   请确保在项目目录下运行，或使用 -d 指定项目目录")
        click.echo("   可以使用 'agentclaw init' 创建新项目")
        sys.exit(1)

    os.environ["AGENTCLAW_PROJECT_DIR"] = str(project_path)
    _migrate_models_config_if_needed(project_path)
    _load_project_env(project_path)
    resolved_port = _resolve_server_port(port)
    resolved_host = _resolve_server_host(host)
    log_file = _resolve_project_log_file(project_path)
    setup_logging(log_file=str(log_file))

    click.echo(f"🚀 启动 AgentClaw 服务器...")
    click.echo(f"   项目目录: {project_path}")
    click.echo(f"   主机: {resolved_host}")
    click.echo(f"   端口: {resolved_port}")
    click.echo("   模型配置: 启动后可在 Dashboard 的「系统配置 -> 模型配置」中填写并热更新；也可手动修改 models.json 后重启")
    if reload:
        click.echo(f"   模式: 开发模式（热重载）")
    else:
        click.echo(f"   工作进程: {workers}")
    click.echo(f"   日志文件: {log_file}")

    # 添加项目目录到 Python 路径
    sys.path.insert(0, str(project_path))

    # 加载 server.py 模块（注册工作流）
    spec = importlib.util.spec_from_file_location("server", server_py)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules["server"] = module
        spec.loader.exec_module(module)

    # 启动服务器
    from agentclaw.api.server import AgentClawServer

    server = AgentClawServer(
        host=resolved_host,
        port=resolved_port,
        workers=workers,
        reload=reload,
    )
    server.run()


def _init_project(project_path: Path, silent: bool = False, create_env: bool = True):
    """创建项目脚手架文件（供 init 和 setup 共用）"""
    # 创建 agents 目录
    agents_dir = project_path / "agents"
    agents_dir.mkdir(exist_ok=True)

    agents_init = agents_dir / "__init__.py"
    if not agents_init.exists():
        agents_init.write_text(TEMPLATE_AGENTS_INIT, encoding="utf-8")
        if not silent:
            click.echo(f"✅ 创建工作流注册: {agents_init}")

    hello_py = agents_dir / "hello_world.py"
    if not hello_py.exists():
        hello_py.write_text(TEMPLATE_HELLO_PY, encoding="utf-8")
        if not silent:
            click.echo(f"✅ 创建示例工作流: {hello_py}")

    server_py = project_path / "server.py"
    if not server_py.exists():
        server_py.write_text(TEMPLATE_SERVER_PY, encoding="utf-8")
        if not silent:
            click.echo(f"✅ 创建服务入口: {server_py}")

    models_json = project_path / "models.json"
    if not models_json.exists():
        models_json.write_text(TEMPLATE_MODELS_JSON, encoding="utf-8")
        if not silent:
            click.echo(f"✅ 创建模型配置: {models_json}")

    if create_env:
        _ensure_default_env(project_path, silent=silent)

    mcp_json = project_path / "mcp.json"
    if not mcp_json.exists():
        mcp_json.write_text(TEMPLATE_MCP_JSON, encoding="utf-8")
        if not silent:
            click.echo(f"✅ 创建 MCP 配置: {mcp_json}")

    compose_src = _get_compose_file()
    compose_dest = project_path / "docker-compose.yml"
    if compose_src.exists() and not compose_dest.exists():
        shutil.copyfile(compose_src, compose_dest)
        if not silent:
            click.echo(f"✅ 创建 Docker Compose 配置: {compose_dest}")

    skills_dir = project_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    skills_gitkeep = skills_dir / ".gitkeep"
    if not skills_gitkeep.exists():
        skills_gitkeep.touch()
        if not silent:
            click.echo(f"✅ 创建技能目录: {skills_dir}")

    readme = project_path / "README.md"
    if not readme.exists():
        project_name = project_path.name if str(project_path) != "." else "my-agentclaw"
        readme.write_text(
            TEMPLATE_README.format(project_name=project_name), encoding="utf-8"
        )
        if not silent:
            click.echo(f"✅ 创建 README: {readme}")


@cli.command()
@click.argument("path", default=".", required=False)
def init(path: str):
    """初始化新项目"""
    project_path = Path(path)

    if path != ".":
        project_path.mkdir(parents=True, exist_ok=True)
        click.echo(f"📁 创建项目目录: {project_path}")

    _init_project(project_path)

    click.echo("")
    click.echo("🎉 项目初始化完成！")
    click.echo("")
    click.echo("下一步：")
    click.echo(f"  1. 启动向导: agentclaw up（手动选择 Docker 或 Remote 模式）")
    click.echo(f"  2. 启动后在 Dashboard 系统配置中配置模型，或手动更新 models.json 后重启")
    click.echo(f"  3. 仅启动已有项目 Server: agentclaw serve")


# ============================================================
# Docker 基础设施命令
# ============================================================

DOCKER_COMPOSE_PROJECT_NAME = "agentclaw"


def _get_compose_file() -> Path:
    """获取内置的 docker-compose.yml 路径"""
    return Path(__file__).parent / "docker" / "docker-compose.yml"


def _docker_compose_command(compose_file: Path) -> list[str]:
    """返回固定项目名的 docker compose 基础命令"""
    return [
        "docker",
        "compose",
        "-p",
        DOCKER_COMPOSE_PROJECT_NAME,
        "-f",
        str(compose_file),
    ]


def _docker_available() -> bool:
    """检测 Docker 是否可用"""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _docker_daemon_accessible() -> tuple[bool, str]:
    """检测当前用户是否能访问 Docker daemon。"""
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return False, "Docker 命令不存在，请先安装 Docker。"
    except subprocess.TimeoutExpired:
        return False, "Docker daemon 响应超时，请检查 Docker 服务状态。"

    if result.returncode == 0:
        return True, ""

    error = (result.stderr or result.stdout or "").strip()
    if "permission denied" in error.lower() and "/var/run/docker.sock" in error:
        return (
            False,
            "当前用户无法访问 Docker daemon。请将当前用户加入 docker 组后重新登录，例如：\n"
            "   sudo usermod -aG docker $USER\n"
            "   newgrp docker\n"
            "也可以先用 sudo docker ps 验证 Docker 本身是否正常。\n"
            "不建议使用 sudo agentclaw up；sudo 环境通常找不到虚拟环境中的 agentclaw，"
            "并且会让项目文件、日志和缓存变成 root 权限。",
        )
    return False, error or "无法访问 Docker daemon，请检查 Docker 服务状态。"


def _docker_compose_services(vector_backend: str = "milvus") -> list[str]:
    """返回 docker compose up 要显式启动的服务；空列表表示启动全部服务。"""
    if vector_backend == "milvus-lite":
        return ["postgres", "redis", "adminer"]
    return []


def _start_infra(compose_file: Path, vector_backend: str = "milvus") -> bool:
    """启动 Docker 基础设施，返回是否成功"""

    services = _docker_compose_services(vector_backend)
    label = "PostgreSQL + Redis + Adminer" if vector_backend == "milvus-lite" else "PostgreSQL + Redis + Milvus + Adminer"
    click.echo(f"🐳 启动基础设施 ({label})...")
    command = [*_docker_compose_command(compose_file), "up", "-d", "--wait", *services]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 and "unknown flag" in (result.stderr or "").lower():
        result = subprocess.run(
            [*_docker_compose_command(compose_file), "up", "-d", *services],
            capture_output=True, text=True,
        )
    if result.returncode != 0:
        click.echo(f"⚠️  Docker 基础设施启动失败:", err=True)
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-3:]:
                click.echo(f"   {line}", err=True)
        return False

    if not _wait_for_docker_host_ports(vector_backend=vector_backend):
        return False

    click.echo(f"   ✅ PostgreSQL 已可连接 (localhost:{_get_int_env('PG_PORT', 5432)})")
    click.echo(f"   ✅ Redis 已可连接 (localhost:{_get_int_env('REDIS_PORT', 6379)})")
    if vector_backend != "milvus-lite":
        click.echo(f"   ✅ Milvus 已可连接 (localhost:{_get_int_env('MILVUS_PORT', 19530)})")
    else:
        click.echo("   ✅ Milvus Lite 将由知识库服务在本地文件中自动初始化")
    click.echo(f"   ✅ Adminer 已启动 (localhost:{_get_int_env('ADMINER_PORT', 8080)})")
    return True


def _can_connect_tcp(host: str, port: int, timeout: float = 0.5) -> bool:
    """检测宿主机是否可以建立 TCP 连接。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _can_ping_redis(host: str, port: int, timeout: float = 0.8) -> bool:
    """检测宿主机 Redis 端口是否能返回 PONG，而不只是 TCP 握手成功。"""
    try:
        with socket.create_connection((host, port), timeout=timeout) as client:
            client.settimeout(timeout)
            client.sendall(b"*1\r\n$4\r\nPING\r\n")
            return client.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def _get_int_env(name: str, default: int) -> int:
    """读取整数环境变量，非法值回退默认值。"""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        click.secho(f"⚠️  {name}={raw_value!r} 不是有效端口，使用默认值 {default}", fg="yellow")
        return default


def _docker_host_checks(vector_backend: str = "milvus") -> tuple[tuple[str, str, int, Callable[[str, int], bool]], ...]:
    """Docker 基础设施暴露到宿主机后的可用性检查。"""
    checks = [
        ("PostgreSQL", "127.0.0.1", _get_int_env("PG_PORT", 5432), _can_connect_tcp),
        ("Redis", "127.0.0.1", _get_int_env("REDIS_PORT", 6379), _can_ping_redis),
    ]
    if vector_backend != "milvus-lite":
        checks.append(("Milvus", "127.0.0.1", _get_int_env("MILVUS_PORT", 19530), _can_connect_tcp))
    return tuple(checks)


def _wait_for_docker_host_ports(timeout: float = 20.0, vector_backend: str = "milvus") -> bool:
    """等待 Docker 暴露到宿主机的 PG/Redis/Milvus 端口可用。"""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if all(check(host, port) for _, host, port, check in _docker_host_checks(vector_backend)):
            return True
        time.sleep(0.5)

    unavailable = [
        f"{label} {host}:{port}"
        for label, host, port, check in _docker_host_checks(vector_backend)
        if not check(host, port)
    ]
    click.secho("⚠️  Docker 容器已启动，但宿主机端口仍不可连接:", fg="yellow", err=True)
    for item in unavailable:
        click.echo(f"   - {item}", err=True)
    click.echo("   Redis 会执行协议级 PING 检查；TCP 可连接但不返回 PONG 也会视为不可用。", err=True)
    click.echo("   请检查 Docker Desktop 端口映射、防火墙或本机端口占用；也可在 .env 中改 REDIS_PORT / MILVUS_PORT / MILVUS_HTTP_PORT 避开异常端口。", err=True)
    return False


def _docker_infra_running(compose_file: Path, vector_backend: str = "milvus") -> bool:
    """检测内置 Docker 基础设施是否已运行"""

    result = subprocess.run(
        [*_docker_compose_command(compose_file), "ps", "--status", "running", "--services"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    required = {"postgres", "redis"} if vector_backend == "milvus-lite" else {"postgres", "redis", "milvus"}
    return required.issubset(running) and _wait_for_docker_host_ports(timeout=3.0, vector_backend=vector_backend)


def _docker_env_vars(vector_backend: str = "milvus") -> dict:
    """Docker 默认基础设施环境变量；已有进程环境变量优先。"""
    pg_port = os.getenv("PG_PORT", "").strip() or "5432"
    redis_port = os.getenv("REDIS_PORT", "").strip() or "6379"
    adminer_port = os.getenv("ADMINER_PORT", "").strip() or "8080"
    env_vars = {
        "PG_HOST": "127.0.0.1",
        "PG_PORT": pg_port,
        "PG_USER": "postgres",
        "PG_PASSWORD": "agentclaw",
        "PG_DATABASE": "agentclaw",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": redis_port,
        "ADMINER_PORT": adminer_port,
    }
    if vector_backend != "milvus-lite":
        minio_api_port = os.getenv("MINIO_API_PORT", "").strip() or "9000"
        minio_console_port = os.getenv("MINIO_CONSOLE_PORT", "").strip() or "9001"
        milvus_port = os.getenv("MILVUS_PORT", "").strip() or "19530"
        milvus_http_port = os.getenv("MILVUS_HTTP_PORT", "").strip() or "9091"
        env_vars.update({
            "MINIO_API_PORT": minio_api_port,
            "MINIO_CONSOLE_PORT": minio_console_port,
            "MILVUS_PORT": milvus_port,
            "MILVUS_HTTP_PORT": milvus_http_port,
            "MILVUS_URI": f"http://127.0.0.1:{milvus_port}",
        })
    return env_vars


def _warn_docker_env_overrides(env_vars: dict) -> None:
    """提示当前进程已有环境变量会优先于 Docker 默认值。"""
    conflicts = [
        (key, os.environ[key], value)
        for key, value in env_vars.items()
        if os.getenv(key) and os.environ[key] != value
    ]
    if not conflicts:
        return

    click.secho("⚠️  检测到已有 Docker 基础设施配置与默认值不同，AgentClaw 会保留这些配置:", fg="yellow")
    for key, current, default in conflicts:
        click.echo(f"   {key}={current}（Docker 默认: {default}）")
    click.echo("   如非预期，请清理对应环境变量或修改项目 .env。")


def _echo_up_banner() -> None:
    """展示 up 启动向导标题"""
    click.echo("")
    click.secho("╭────────────────────────────────────────────╮", fg="cyan")
    click.secho("│            AgentClaw 启动向导              │", fg="cyan", bold=True)
    click.secho("╰────────────────────────────────────────────╯", fg="cyan")
    click.echo("")


def _echo_up_section(title: str, subtitle: str = "") -> None:
    """展示 up 启动向导小节"""
    click.echo("")
    click.secho(f"◆ {title}", fg="cyan", bold=True)
    if subtitle:
        click.secho(f"  {subtitle}", fg="bright_black")


def _select_up_mode(mode: Optional[str]) -> str:
    """选择 up 启动模式；未通过参数指定时必须手动选择"""
    if mode:
        return mode

    _echo_up_banner()
    click.secho("请选择启动模式：", bold=True)
    click.echo("")
    click.secho("  1) Docker 本地基础设施", fg="green", bold=True)
    click.echo("     自动托管 PostgreSQL / Redis / Milvus，适合本地开发、Demo 和完整体验。")
    click.secho("  2) Remote 远程环境", fg="blue", bold=True)
    click.echo("     不启动 Docker，使用已有 PG / Redis；连接信息可为空，空则以内存模式运行。")
    click.echo("")
    choice = click.prompt(
        "请输入选项",
        type=click.Choice(["1", "2"]),
        show_choices=False,
    )
    selected = "docker" if choice == "1" else "remote"
    click.secho(f"✓ 已选择: {'Docker 本地基础设施' if selected == 'docker' else 'Remote 远程环境'}", fg="green")
    return selected


def _select_vector_backend(vector_backend: Optional[str], *, interactive: bool) -> str:
    """选择 Docker 模式使用完整 Milvus 还是 Milvus Lite。"""
    if vector_backend:
        return vector_backend
    if not interactive:
        return "milvus"

    _echo_up_section("向量存储", "选择知识库向量数据的存储方式。")
    click.secho("  1) Milvus Docker", fg="green", bold=True)
    click.echo("     启动完整 Milvus Standalone，适合生产预演、较大知识库和跨进程稳定服务。")
    click.secho("  2) Milvus Lite", fg="blue", bold=True)
    click.echo("     不启动 Milvus Docker；由本地文件 milvus.db 存储向量，资源占用更低。")
    click.echo("")
    choice = click.prompt(
        "请输入选项",
        type=click.Choice(["1", "2"]),
        default="1",
        show_choices=False,
    )
    selected = "milvus" if choice == "1" else "milvus-lite"
    label = "Milvus Docker" if selected == "milvus" else "Milvus Lite"
    click.secho(f"✓ 已选择: {label}", fg="green")
    return selected


def _apply_env_vars(env_vars: dict, override: bool = False) -> None:
    """写入当前进程环境，供即将启动的 server 使用"""
    for key, value in env_vars.items():
        if value == "":
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value


def _upsert_env_file(project_path: Path, env_vars: dict, section_title: str, overwrite: bool = False) -> None:
    """向 .env 补齐一组环境变量。

    默认不覆盖已经生效的用户配置；模板中的注释配置可被启用为本次模式的默认值。
    当 overwrite=True 时，只覆盖传入 env_vars 对应的已有配置。
    """
    if not env_vars:
        return

    env_file = project_path / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    written = set()
    active_values = {
        line.strip().split("=", 1)[0].strip(): line.strip().split("=", 1)[1].strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#") and "=" in line.strip()
    }

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        is_commented = stripped.startswith("#")
        uncommented = stripped[1:].strip() if is_commented else stripped
        if "=" not in uncommented:
            continue
        key = uncommented.split("=", 1)[0].strip()
        if key not in env_vars or key in written:
            continue

        value = env_vars[key]
        if value == "":
            continue

        if not is_commented:
            current_value = uncommented.split("=", 1)[1].strip()
            if overwrite or current_value == "":
                lines[index] = f"{key}={value}"
            written.add(key)
        elif key in env_vars and (key not in active_values or active_values[key] == ""):
            lines[index] = f"{key}={value}"
            written.add(key)

    missing = [key for key, value in env_vars.items() if key not in written and value != ""]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"# {section_title}")
        for key in missing:
            lines.append(f"{key}={env_vars[key]}")

    env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_initial_up_env_file(project_path: Path, env_vars: dict) -> None:
    """为 agentclaw up 初始化项目写入 .env；已有文件只补齐缺失配置。"""
    env_file = project_path / ".env"
    if env_file.exists():
        _upsert_env_file(project_path, env_vars, "AgentClaw up 自动配置")
        return
    env_file.write_text(_build_default_env_content(overrides=env_vars), encoding="utf-8")


def _activate_milvus_lite_env(project_path: Path) -> None:
    """清空完整 Milvus 连接配置，确保本次启动使用本地 Milvus Lite。"""
    os.environ.pop("MILVUS_URI", None)
    env_file = project_path / ".env"
    if not env_file.exists():
        return

    lines = env_file.read_text(encoding="utf-8").splitlines()
    changed = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key == "MILVUS_URI" and stripped.split("=", 1)[1].strip():
            lines[index] = "MILVUS_URI="
            changed = True
    if changed:
        env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _configured_data_dir_needs_sync(project_path: Path, mode: str) -> bool:
    """判断已配置的数据目录是否缺少当前启动模式需要的派生配置。"""
    data_dir = _get_existing_env_value(project_path, "AGENTCLAW_DATA_DIR")
    if not data_dir:
        return False

    required_keys = {
        "AGENTCLAW_LOG_FILE",
        "AGENTCLAW_FEISHU_LOG_FILE",
        "UPLOAD_DIR",
        "KNOWLEDGEBASE_STORAGE_DIR",
        "KNOWLEDGEBASE_PARSER_CACHE_DIR",
    }
    if mode == "docker":
        required_keys.update({
            "AGENTCLAW_DOCKER_STORAGE_TYPE",
            "AGENTCLAW_DOCKER_PGDATA_DIR",
            "AGENTCLAW_DOCKER_REDISDATA_DIR",
            "AGENTCLAW_DOCKER_ETCDDATA_DIR",
            "AGENTCLAW_DOCKER_MINIODATA_DIR",
            "AGENTCLAW_DOCKER_MILVUSDATA_DIR",
        })

    expected = build_data_dir_env_vars(data_dir, project_dir=project_path, include_docker=mode == "docker")
    return any(_get_existing_env_value(project_path, key) != expected[key] for key in required_keys)


def _ensure_storage_directories(env_vars: dict[str, str]) -> None:
    """提前创建本地存储目录，避免 Docker bind 或本地写入时路径不存在。"""
    directory_keys = {
        "UPLOAD_DIR",
        "KNOWLEDGEBASE_STORAGE_DIR",
        "KNOWLEDGEBASE_PARSER_CACHE_DIR",
        "AGENTCLAW_DOCKER_PGDATA_DIR",
        "AGENTCLAW_DOCKER_REDISDATA_DIR",
        "AGENTCLAW_DOCKER_ETCDDATA_DIR",
        "AGENTCLAW_DOCKER_MINIODATA_DIR",
        "AGENTCLAW_DOCKER_MILVUSDATA_DIR",
    }
    file_keys = {
        "AGENTCLAW_LOG_FILE",
        "AGENTCLAW_FEISHU_LOG_FILE",
    }

    for key in directory_keys:
        value = env_vars.get(key)
        if value:
            Path(value).expanduser().mkdir(parents=True, exist_ok=True)
    for key in file_keys:
        value = env_vars.get(key)
        if value:
            Path(value).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _prompt_data_dir_env_vars(project_path: Path, mode: str) -> dict[str, str]:
    """交互配置统一数据目录；留空保持历史默认行为。"""
    _echo_up_section(
        "数据目录",
        "可选；用于把项目代码与日志、上传文件、知识库缓存和 Docker 数据卷分离。",
    )
    existing = _get_existing_env_value(project_path, "AGENTCLAW_DATA_DIR")
    if existing:
        click.echo(f"  当前 AGENTCLAW_DATA_DIR: {existing}")
        needs_sync = _configured_data_dir_needs_sync(project_path, mode)
        sync = click.confirm(
            "  是否同步/更新相关存储路径？",
            default=needs_sync,
            show_default=True,
        )
        if not sync:
            return {}
        raw_value = click.prompt("  数据目录（回车保持当前值）", default=existing, show_default=False)
    else:
        raw_value = click.prompt(
            "  数据目录（回车保持默认）",
            default="",
            show_default=False,
        )
        if not raw_value.strip():
            click.echo("  ✓ 保持默认：本地文件写入项目目录，Docker 使用 named volumes")
            return {}

    data_dir = resolve_data_dir(raw_value, project_path)
    env_vars = build_data_dir_env_vars(data_dir, include_docker=mode == "docker")
    click.secho(f"  ✓ 使用数据目录: {data_dir}", fg="green")
    if mode == "docker":
        click.secho("  ⚠️  切换 Docker 存储目录不会自动迁移已有 named volume 数据。", fg="yellow")
    return env_vars


def _prompt_generated_secret(project_path: Path, name: str, generator) -> str:
    """让用户输入密钥；留空时自动生成"""
    existing = _get_existing_env_value(project_path, name)
    if existing:
        click.echo(f"  ✓ {name} 已配置，跳过")
        return existing

    value = click.prompt(f"  {name}（回车自动生成）", default="", hide_input=True, show_default=False)
    if value:
        return value
    generated = generator()
    click.echo(f"  ✅ {name} 已自动生成")
    return generated


def _prompt_runtime_secrets(project_path: Path) -> dict:
    """新项目启动时需要写入的基础密钥"""
    _echo_up_section("运行密钥", "留空会自动生成安全随机值，并写入项目 .env。")
    return {
        "ADMIN_TOKEN": _prompt_generated_secret(project_path, "ADMIN_TOKEN", _generate_admin_token),
        "WORKFLOW_API_KEY": _prompt_generated_secret(project_path, "WORKFLOW_API_KEY", _generate_workflow_api_key),
        "MCP_TOKEN": _prompt_generated_secret(project_path, "MCP_TOKEN", _generate_mcp_token),
    }


def _prompt_remote_env_vars() -> dict:
    """远程环境模式下可选填写 PG/Redis 连接"""
    env_vars = {}

    _echo_up_section("远程 PostgreSQL", "可选；PG_HOST 留空则不连接 PostgreSQL。")
    pg_host = click.prompt("  PG_HOST", default="", show_default=False)
    if pg_host:
        env_vars["PG_HOST"] = pg_host
        env_vars["PG_PORT"] = click.prompt("  PG_PORT", default="5432")
        env_vars["PG_USER"] = click.prompt("  PG_USER", default="postgres")
        pg_password = click.prompt("  PG_PASSWORD（无密码直接回车）", default="", hide_input=True, show_default=False)
        if pg_password:
            env_vars["PG_PASSWORD"] = pg_password
        env_vars["PG_DATABASE"] = click.prompt("  PG_DATABASE", default="agentclaw")

    _echo_up_section("远程 Redis", "可选；REDIS_HOST 留空则不连接 Redis。")
    redis_host = click.prompt("  REDIS_HOST", default="", show_default=False)
    if redis_host:
        env_vars["REDIS_HOST"] = redis_host
        env_vars["REDIS_PORT"] = click.prompt("  REDIS_PORT", default="6379")
        redis_password = click.prompt("  REDIS_PASSWORD（无密码直接回车）", default="", hide_input=True, show_default=False)
        if redis_password:
            env_vars["REDIS_PASSWORD"] = redis_password

    return env_vars


def _is_agentclaw_project(project_path: Path) -> bool:
    """判断目录是否已经是 AgentClaw 项目"""
    return (project_path / "server.py").exists()


def _prepare_project_for_up(project_dir: str, mode: str) -> tuple[Path, bool]:
    """确保 up 有可启动项目，必要时自动初始化"""
    project_path = Path(project_dir).expanduser().resolve()
    if _is_agentclaw_project(project_path):
        click.secho(f"✓ 检测到 AgentClaw 项目: {project_path}", fg="green")
        return project_path, False

    if mode == "docker":
        _echo_up_section("项目目录", f"当前路径还不是 AgentClaw 项目: {project_path}")
        chosen_path = click.prompt(
            "请输入启动/创建路径（相对或绝对路径，回车使用当前路径）",
            default=project_dir or ".",
        )
        project_path = Path(chosen_path or ".").expanduser().resolve()
        if _is_agentclaw_project(project_path):
            click.secho(f"✓ 检测到 AgentClaw 项目: {project_path}", fg="green")
            return project_path, False
    else:
        _echo_up_section("项目目录", f"当前路径还不是 AgentClaw 项目，将自动初始化: {project_path}")

    project_path.mkdir(parents=True, exist_ok=True)
    click.secho(f"📁 初始化 AgentClaw 项目: {project_path}", fg="cyan")
    _init_project(project_path, create_env=False)
    click.secho("✓ 项目初始化完成", fg="green")
    return project_path, True


def _start_agentclaw_server(project_path: Path, port: Optional[int], host: Optional[str], workers: int, reload: bool) -> None:
    """加载项目 server.py 并启动 AgentClaw server"""
    import importlib.util

    server_py = project_path / "server.py"
    if not server_py.exists():
        click.echo(f"❌ 未找到 server.py: {server_py}", err=True)
        click.echo("   可以使用 'agentclaw init' 创建新项目")
        sys.exit(1)

    os.environ["AGENTCLAW_PROJECT_DIR"] = str(project_path)
    _migrate_models_config_if_needed(project_path)
    _load_project_env(project_path)
    resolved_port = _resolve_server_port(port)
    resolved_host = _resolve_server_host(host)

    _echo_up_section("启动 Server")
    click.echo(f"🚀 启动 AgentClaw 服务器...")
    click.echo(f"   项目目录: {project_path}")
    click.echo(f"   主机: {resolved_host}")
    click.echo(f"   端口: {resolved_port}")

    sys.path.insert(0, str(project_path))

    spec = importlib.util.spec_from_file_location("server", server_py)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules["server"] = module
        spec.loader.exec_module(module)

    from agentclaw.api.server import AgentClawServer

    server = AgentClawServer(
        host=resolved_host,
        port=resolved_port,
        workers=workers,
        reload=reload,
    )
    server.run()


@cli.command()
@click.option("-p", "--port", type=int, default=None, help="端口号；未指定时读取 .env 中的 PORT，默认 8000")
@click.option("-h", "--host", default=None, help="主机地址；未指定时读取 .env 中的 HOST，默认 0.0.0.0")
@click.option("-d", "--project-dir", default=".", help="项目目录")
@click.option("-w", "--workers", default=1, help="工作进程数")
@click.option("--reload", is_flag=True, help="开发模式，热重载")
@click.option(
    "--mode",
    type=click.Choice(["docker", "remote"]),
    default=None,
    help="跳过交互选择，直接指定启动模式：docker=自动托管 PG/Redis/Milvus，remote=使用远程环境",
)
@click.option(
    "--vector-backend",
    type=click.Choice(["milvus", "milvus-lite"]),
    default=None,
    help="Docker 模式下选择向量存储：milvus=启动完整 Milvus，milvus-lite=使用本地 Milvus Lite",
)
def up(
    port: Optional[int],
    host: Optional[str],
    project_dir: str,
    workers: int,
    reload: bool,
    mode: Optional[str],
    vector_backend: Optional[str],
):
    """启动 AgentClaw 项目（交互选择 Docker 或 Remote 模式）"""
    mode_was_explicit = mode is not None
    mode = _select_up_mode(mode)
    project_path, initialized = _prepare_project_for_up(project_dir, mode)
    if mode == "docker":
        vector_backend = _select_vector_backend(vector_backend, interactive=not mode_was_explicit)
    else:
        vector_backend = "milvus"

    if initialized:
        env_vars = _prompt_runtime_secrets(project_path)
        if mode == "docker":
            env_vars.update(_docker_env_vars(vector_backend=vector_backend))
        else:
            env_vars.update(_prompt_remote_env_vars())
        _write_initial_up_env_file(project_path, env_vars)
        _apply_env_vars(env_vars)

    data_dir_env_vars = _prompt_data_dir_env_vars(project_path, mode)
    if data_dir_env_vars:
        _ensure_storage_directories(data_dir_env_vars)
        _upsert_env_file(project_path, data_dir_env_vars, "AgentClaw 数据目录", overwrite=True)
        _apply_env_vars(data_dir_env_vars, override=True)

    if mode == "docker" and vector_backend == "milvus-lite":
        _activate_milvus_lite_env(project_path)
    _load_project_env(project_path)

    if mode == "docker":
        if not _docker_available():
            click.echo("❌ Docker 不可用，无法使用 docker 启动模式", err=True)
            click.echo("   可安装 Docker 后重试，或使用: agentclaw up --mode remote", err=True)
            sys.exit(1)
        daemon_ok, daemon_error = _docker_daemon_accessible()
        if not daemon_ok:
            click.echo("❌ Docker daemon 不可访问，无法使用 docker 启动模式", err=True)
            for line in daemon_error.splitlines():
                click.echo(f"   {line}", err=True)
            sys.exit(1)

        infra_label = "PostgreSQL / Redis / Adminer" if vector_backend == "milvus-lite" else "PostgreSQL / Redis / Milvus / Adminer"
        _echo_up_section("Docker 基础设施", f"检查 {infra_label} 是否已经运行。")
        compose_file = _get_compose_file()
        docker_env_vars = _docker_env_vars(vector_backend=vector_backend)
        _warn_docker_env_overrides(docker_env_vars)
        _upsert_env_file(project_path, docker_env_vars, "AgentClaw Docker 基础设施")
        _apply_env_vars(docker_env_vars)
        if _docker_infra_running(compose_file, vector_backend=vector_backend):
            click.secho("✓ Docker 基础设施已运行，跳过 docker compose up", fg="green")
        elif not _start_infra(compose_file, vector_backend=vector_backend):
            sys.exit(1)
    else:
        _echo_up_section("Remote 环境", "不会启动 Docker，将使用当前 .env / 环境变量中的 PG、Redis 配置。")

    _start_agentclaw_server(project_path, port, host, workers, reload)



# ============================================================
# 模板文件
# ============================================================

TEMPLATE_HELLO_PY = '''"""
示例工作流 - Hello World
"""

from agentclaw import Workflow, LLMNode, Input

# 创建工作流
workflow = Workflow(
    id="hello_world",
    name="Hello World",
    description="一个简单的问候工作流",
    inputs=[
        Input("user_input", str, required=True, description="请输入想让助手回答的内容"),
    ],
    user_input="user_input",
)

# 添加 LLM 节点
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手，用简洁的语言回答问题。",
    enable_memory=True,
    output_to_user=True,
))

# 发布工作流
workflow.publish()
'''

TEMPLATE_AGENTS_INIT = '''"""
工作流注册模块

在此文件中导入所有工作流，确保它们被注册到 WorkflowRegistry。
添加新工作流时，只需在此文件中添加导入语句即可。
"""

# 导入所有工作流（确保它们被注册）
from .hello_world import workflow as hello_world_workflow

# 导出所有工作流（可选，方便外部访问）
__all__ = [
    "hello_world_workflow",
]
'''

TEMPLATE_SERVER_PY = '''"""
AgentClaw 服务入口

启动方式：
  agentclaw serve
  # 或
  python server.py
"""

# 导入 agents 模块，自动注册所有工作流
import agents  # noqa: F401

# 如果直接运行此文件，启动服务器
if __name__ == "__main__":
    from agentclaw import AgentClawServer

    server = AgentClawServer()
    server.run()
'''

TEMPLATE_MODELS_JSON = '''{
  "default": "gpt-4o-mini",
  "fallback": "gpt-3.5-turbo",
  "safe_guard": "",
  "safe_guard_apply_api": false,
  "safe_guard_apply_public": true,
  "safe_guard_rules": "",
  "models": [
    {
      "id": "gpt-4o-mini",
      "channel": "openai",
      "api_key": "your-openai-api-key",
      "model": "gpt-4o-mini",
      "temperature": 0.7
    },
    {
      "id": "gpt-3.5-turbo",
      "channel": "openai",
      "api_key": "your-openai-api-key",
      "model": "gpt-3.5-turbo",
      "temperature": 0.7
    }
  ]
}
'''

TEMPLATE_MCP_JSON = '''{
  "mcpServers": {
    "example-server": {
      "command": "uvx",
      "args": ["example-mcp-server"],
      "env": {},
      "disabled": true
    }
  }
}
'''

TEMPLATE_README = '''# {project_name}

基于 AgentClaw 构建的 AI Agent 项目。

## 快速开始

1. 安装依赖

```bash
pip install agentclaw-ai
```

2. 启动项目

```bash
agentclaw up
```

3. 配置模型与运行环境

```bash
# 启动后在 Dashboard「系统配置 -> 模型配置」中填写模型并热更新
# 也可以手动编辑 models.json 后重启
# .env 用于服务、鉴权、PG/Redis 等启动配置
```

4. 仅启动已有项目 Server

```bash
agentclaw serve
```

5. 测试 API

```bash
curl -X POST http://localhost:8000/api/workflow/run \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <your-api-key>" \\
  -d '{{"workflow_id": "hello_world", "inputs": {{"user_input": "你好"}}}}'
```

## 项目结构

```
{project_name}/
├── agents/           # 工作流定义
│   └── hello_world.py # 示例工作流
├── server.py         # 服务入口
├── models.json       # 模型配置
├── docker-compose.yml # Docker 基础设施配置
├── .env              # 环境变量
└── README.md
```

## 添加新工作流

1. 在 `agents/` 目录下创建新文件，如 `agents/my_workflow.py`
2. 在 `agents/__init__.py` 中导入新工作流
3. 运行 `agentclaw up`，在 Dashboard 或 API 中调用工作流

## 文档

- [AgentClaw 文档](https://github.com/your-repo/agentclaw)
'''


def main():
    """CLI 入口点"""
    cli()


if __name__ == "__main__":
    main()
