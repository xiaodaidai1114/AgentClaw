"""Registry and CLI entry point for built-in MCP servers."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


# Server 配置映射：server-name -> (module_name, class_name, init_params)
SERVER_REGISTRY = {
    "skill-tools": {
        "module": "skill_tools",
        "class": "SkillToolsServer",
        "init_params": ["skills_dir", "working_dir", "models_config", "project_dir"],
    },
    "coding-tools": {
        "module": "coding_tools",
        "class": "CodingToolsServer",
        "init_params": ["project_dir"],
    },
    "planning-tools": {
        "module": "planning_tools",
        "class": "PlanningToolsServer",
        "init_params": [],
    },
    "download-tools": {
        "module": "download_tools",
        "class": "DownloadToolsServer",
        "init_params": ["working_dir"],
    },
    "search-tools": {
        "module": "search_tools",
        "class": "SearchToolsServer",
        "init_params": [],
    },
    "computer-tools": {
        "module": "computer_tools",
        "class": "ComputerToolsServer",
        "init_params": ["working_dir", "models_config"],
    },
    "browser-tools": {
        "module": "agentclaw.mcp.browser_server",
        "class": "BrowserToolsServer",
        "init_params": [],
        "external": True,  # 标记为外部模块
    },
}


def _get_server_class(server_name: str):
    """延迟导入 server 类以避免循环导入"""
    if server_name not in SERVER_REGISTRY:
        raise ValueError(f"Unknown server: {server_name}")

    config = SERVER_REGISTRY[server_name]
    module_name = config["module"]
    class_name = config["class"]
    is_external = config.get("external", False)

    # 动态导入
    import importlib

    if is_external:
        module = importlib.import_module(module_name)
    else:
        module = importlib.import_module(f".{module_name}", package="agentclaw.mcp.builtin_servers")

    return getattr(module, class_name)


BUILTIN_SERVERS = {
    server_name: {
        "description": {
            "skill-tools": "Python/shell execution with skill environment support",
            "coding-tools": "Project-scoped coding tools (search/syntax/read/update/replace/rename)",
            "planning-tools": "Task planning and tracking (TodoWrite, GetTodos)",
            "download-tools": "Generate temporary download URLs for local files (requires Redis)",
            "browser-tools": "Browser automation via CDP (navigate, click, fill, snapshot, etc.)",
            "search-tools": "Web search via SearXNG (requires SEARXNG_BASE_URL env var)",
            "computer-tools": "Screenshot and system simulation (mouse, keyboard)",
        }[server_name],
        "class": None,  # Lazy loaded
    }
    for server_name in SERVER_REGISTRY.keys()
}


def get_builtin_server_config(
    server_name: str,
    skills_dir: Optional[str] = None,
    working_dir: Optional[str] = None,
    models_config: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get MCPServerConfig dict for a built-in server.

    Args:
        server_name: Name of the built-in server
        skills_dir: Skills directory path (for skill-tools)
        working_dir: Working directory path
        models_config: Models config file path (for skill-tools VL support)
        project_dir: Project directory path (for coding-tools sandbox)

    Returns:
        Config dict compatible with MCPServerConfig.from_dict()
    """
    if server_name not in SERVER_REGISTRY:
        return None

    config = SERVER_REGISTRY[server_name]
    is_external = config.get("external", False)

    # 构建命令参数
    if is_external:
        args = ["-m", config["module"]]
    else:
        args = ["-m", "agentclaw.mcp.builtin_servers", server_name]

    # 参数映射：CLI 参数名 -> 本地变量
    param_mapping = {
        "skills_dir": ("--skills-dir", skills_dir),
        "working_dir": ("--working-dir", working_dir),
        "models_config": ("--models-config", models_config),
        "project_dir": ("--project-dir", project_dir or working_dir),
    }

    # 根据 server 配置添加参数
    for param_name in config.get("init_params", []):
        if param_name in param_mapping:
            flag, value = param_mapping[param_name]
            if value:
                args.extend([flag, value])

    # 特殊处理：search-tools 需要 SEARXNG_BASE_URL
    if server_name == "search-tools":
        searxng_url = os.getenv("SEARXNG_BASE_URL")
        if not searxng_url:
            return None

    # 设置环境变量
    import agentclaw
    package_root = str(Path(agentclaw.__file__).parent.parent)
    env: Dict[str, str] = {}
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{package_root}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = package_root

    # 特殊环境变量处理
    if server_name == "search-tools":
        env["SEARXNG_BASE_URL"] = os.getenv("SEARXNG_BASE_URL", "")

    # skill-tools 需要 server_base_url + token
    if server_name == "skill-tools":
        server_base_url = (
            os.getenv("AGENTCLAW_URL", "").strip()
            or os.getenv("AgentClaw_SERVER_BASE_URL", "").strip()
            or f"http://127.0.0.1:{os.getenv('PORT', '8000')}"
        ).rstrip("/")
        env["AGENTCLAW_URL"] = server_base_url
        env["AgentClaw_SERVER_BASE_URL"] = server_base_url

        admin_token = os.getenv("ADMIN_TOKEN", "").strip()
        workflow_api_key = os.getenv("WORKFLOW_API_KEY", "").strip()
        if not admin_token or not workflow_api_key:
            try:
                from agentclaw.api.auth.token import AdminTokenManager, WorkflowAPIKeyManager
                if not admin_token:
                    admin_token = AdminTokenManager.get_instance().token
                if not workflow_api_key:
                    workflow_api_key = WorkflowAPIKeyManager.get_instance().api_key
            except Exception:
                pass
        if admin_token:
            env["ADMIN_TOKEN"] = admin_token
        if workflow_api_key:
            env["WORKFLOW_API_KEY"] = workflow_api_key

    result: Dict[str, Any] = {
        "command": sys.executable,
        "args": args,
        "env": env,
        "disabled": True,
    }

    # 特殊超时配置
    if server_name == "skill-tools":
        result["timeout"] = 120.0
    elif server_name == "browser-tools":
        result["timeout"] = 120.0

    return result


def is_builtin_server(name: str) -> bool:
    """Check if a server name is a built-in server."""
    return name in BUILTIN_SERVERS


def main():
    """CLI entry point for running built-in servers."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentClaw Built-in MCP Servers")
    parser.add_argument("server", choices=list(SERVER_REGISTRY.keys()), help="Server to run")
    parser.add_argument("--skills-dir", default=None, help="Skills directory path")
    parser.add_argument("--working-dir", default=None, help="Working directory")
    parser.add_argument("--models-config", default=None, help="Models config file path")
    parser.add_argument("--project-dir", default=None, help="Project directory (coding-tools sandbox)")

    args = parser.parse_args()

    # 获取 server 类
    server_class = _get_server_class(args.server)
    if server_class is None:
        raise ValueError(f"Server {args.server} not available")

    # 构建初始化参数
    config = SERVER_REGISTRY[args.server]
    init_kwargs = {}

    # 参数映射：init_param -> CLI arg
    param_to_arg = {
        "skills_dir": args.skills_dir,
        "working_dir": args.working_dir,
        "models_config": args.models_config,
        "project_dir": args.project_dir,
    }

    # 根据 server 配置构建参数
    for param_name in config.get("init_params", []):
        if param_name in param_to_arg and param_to_arg[param_name] is not None:
            init_kwargs[param_name] = param_to_arg[param_name]

    # 创建并运行 server
    server = server_class(**init_kwargs)
    asyncio.run(server.run())
