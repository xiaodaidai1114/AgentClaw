"""
AgentClawServer - HTTP 服务器

提供：
- 自动扫描和加载工作流
- 动态路由注册
- SSE 流式响应
- Admin API
- 任务管理和中止
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

from ..platform_compat import apply_windows_selector_event_loop_policy

apply_windows_selector_event_loop_policy()

from agentclaw.logger.config import get_logger, setup_logging, get_current_log_file
from agentclaw.version import get_version

# FastAPI imports（顶层导入避免闭包问题）
try:
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if TYPE_CHECKING:
    from agentclaw.api.auth import AuthConfig

logger = get_logger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_csv(name: str) -> Optional[List[str]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None


# ============================================================
# 任务管理器 - 跟踪运行中的工作流任务
# ============================================================

class TaskManager:
    """
    工作流任务管理器
    
    跟踪运行中的任务，支持中止操作
    """
    _instance: Optional["TaskManager"] = None
    
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> {task, cancel_token, ...}
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "TaskManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def register(
        self,
        task_id: str,
        task: asyncio.Task,
        cancel_token: Any,
        workflow_id: str,
        thread_id: Optional[str] = None,
    ) -> None:
        """注册任务"""
        async with self._lock:
            self._tasks[task_id] = {
                "task": task,
                "cancel_token": cancel_token,
                "workflow_id": workflow_id,
                "thread_id": thread_id,
                "created_at": asyncio.get_event_loop().time(),
            }
    
    async def unregister(self, task_id: str) -> None:
        """注销任务"""
        async with self._lock:
            self._tasks.pop(task_id, None)
    
    async def cancel(self, task_id: str, reason: str = "用户中止") -> bool:
        """
        中止任务

        Returns:
            True 如果成功中止，False 如果任务不存在或已完成
        """
        async with self._lock:
            task_info = self._tasks.get(task_id)
            if not task_info:
                return False

            task = task_info["task"]
            cancel_token = task_info["cancel_token"]

            # 设置取消标志
            if cancel_token and hasattr(cancel_token, "cancel"):
                cancel_token.cancel(reason)

            # 取消 asyncio 任务
            if not task.done():
                task.cancel()

        # checkpoint 清理由 run_workflow() 的 CancelledError 处理器负责
        return True
    
    async def get_running_tasks(self, workflow_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取运行中的任务列表"""
        async with self._lock:
            tasks = []
            for task_id, info in self._tasks.items():
                if workflow_id and info["workflow_id"] != workflow_id:
                    continue
                if not info["task"].done():
                    tasks.append({
                        "task_id": task_id,
                        "workflow_id": info["workflow_id"],
                        "thread_id": info["thread_id"],
                        "created_at": info["created_at"],
                    })
            return tasks
    
    async def cleanup_done_tasks(self) -> int:
        """清理已完成的任务"""
        async with self._lock:
            done_ids = [
                task_id for task_id, info in self._tasks.items()
                if info["task"].done()
            ]
            for task_id in done_ids:
                del self._tasks[task_id]
            return len(done_ids)


class AgentClawServer:
    """
    AgentClaw HTTP 服务器
    
    使用方式：
    1. 在 server.py 中导入工作流
    2. 创建 AgentClawServer 实例
    3. 调用 run() 启动服务
    
    Example:
        # server.py
        import agents  # 自动注册所有工作流
        
        from agentclaw import AgentClawServer
        
        server = AgentClawServer()
        server.run()
        
        # 或使用 CLI
        # agentclaw serve
    """
    
    def __init__(
        self,
        config: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        workers: int = 1,
        reload: bool = False,
        # Admin Dashboard（包含 Admin API + 前端页面）
        enable_admin: bool = True,
        admin_prefix: str = "/admin",
        admin_dashboard_port: Optional[int] = None,
        # CORS
        cors_origins: Optional[List[str]] = None,
        # 认证配置
        auth: Optional["AuthConfig"] = None,
        api_keys: Optional[Dict[str, Any]] = None,  # 简写：{"sk-xxx": {"name": "prod"}}
        # MCP 工具导出
        export_mcp_tools: bool = False,  # 启动时导出 MCP 工具到 mcp_tools.json
    ):
        self.config_path = config
        self.project_dir = self._resolve_project_dir(config)
        os.environ["AGENTCLAW_PROJECT_DIR"] = str(self.project_dir)
        self._load_project_env(self.project_dir)
        self.host = self._resolve_host(host)
        self.port = self._resolve_port(port)
        self.workers = workers
        self.reload = reload
        
        # enable_admin 统一控制 Admin API + Dashboard 前端；环境变量只在显式配置时覆盖，默认保持本地开发行为。
        self.enable_admin = enable_admin and _env_bool("AGENTCLAW_ENABLE_ADMIN_API", True)
        self.admin_prefix = admin_prefix
        self.enable_mcp_routes = _env_bool("AGENTCLAW_ENABLE_MCP_ROUTES", True)
        self.enable_scheduler_api = _env_bool("AGENTCLAW_ENABLE_SCHEDULER_API", True)
        self.enable_channel_routes = _env_bool("AGENTCLAW_ENABLE_CHANNEL_ROUTES", True)
        self.enable_api_docs = _env_bool("AGENTCLAW_ENABLE_API_DOCS", True)
        
        # MCP 工具导出
        self.export_mcp_tools = export_mcp_tools or os.getenv("EXPORT_MCP_TOOLS", "").lower() in ("true", "1", "yes")
        
        # 项目目录（用于 channels.json、日志等配置文件）
        raw_log_file = os.getenv("AGENTCLAW_LOG_FILE") or os.getenv("LOG_FILE")
        if raw_log_file:
            log_path = Path(raw_log_file).expanduser()
            self.log_file = log_path if log_path.is_absolute() else self.project_dir / log_path
        else:
            data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
            self.log_file = Path(data_dir).expanduser() / "logs" / "agentclaw.log" if data_dir else self.project_dir / "logs" / "agentclaw.log"
        setup_logging(log_file=str(self.log_file))

        # 检查 PG 数据库配置状态（用于提示，不禁用 Admin API）
        if self.enable_admin and not self._is_pg_configured():
            logger.warning("⚠️ PostgreSQL 未配置，Admin API 中涉及数据库的功能（日志、统计等）将不可用")
        if not self._is_redis_configured():
            logger.warning("⚠️ Redis 未配置，Prompt 热更新、多实例同步、分布式锁和缓存能力将不可用")
        
        # Dashboard 前端配置（默认跟随 enable_admin，生产可用环境变量单独收紧）
        self.enable_admin_dashboard = _env_bool("AGENTCLAW_ENABLE_DASHBOARD", enable_admin)
        self.dashboard_mode = os.getenv("AGENTCLAW_DASHBOARD_MODE", "full").strip().lower() or "full"
        self.admin_dashboard_port = admin_dashboard_port if admin_dashboard_port is not None else int(os.getenv("ADMIN_DASHBOARD_PORT", "5173"))
        
        # 自动查找 admin-dashboard 目录（在 agentclaw 包内）
        self.admin_dashboard_dir = self._find_admin_dashboard_dir()
        self._dashboard_process = None
        
        self.cors_origins = cors_origins or _env_csv("AGENTCLAW_CORS_ORIGINS") or ["*"]
        self.cors_allow_credentials = _env_bool("AGENTCLAW_CORS_ALLOW_CREDENTIALS", True)
        
        # 认证配置
        self._setup_auth(auth, api_keys)

        # 配置对象
        self._config: Dict[str, Any] = {}
        
        # FastAPI 应用
        self._app = None
        self._internal_relay_app = None
        self._internal_relay_server = None
        self._internal_relay_thread = None
        self._internal_relay_url: Optional[str] = None
        
        # 启动时检查关键依赖
        self._check_dependencies()

    @staticmethod
    def _resolve_project_dir(config: Optional[str]) -> Path:
        """推断项目目录，优先使用显式配置和入口脚本目录"""
        if config is not None:
            return Path(config).expanduser().resolve().parent

        env_project_dir = os.getenv("AGENTCLAW_PROJECT_DIR")
        if env_project_dir:
            return Path(env_project_dir).expanduser().resolve()

        main_module = sys.modules.get("__main__")
        main_file = getattr(main_module, "__file__", None)
        if main_file:
            main_path = Path(main_file).expanduser().resolve()
            if main_path.name == "server.py":
                return main_path.parent

        return Path.cwd().resolve()

    @staticmethod
    def _load_project_env(project_dir: Path) -> None:
        """加载项目 .env，让 python server.py 与 CLI 启动读取同一套运行配置。"""
        env_file = project_dir / ".env"
        if not env_file.exists():
            return
        try:
            from dotenv import load_dotenv
        except ImportError:
            return
        load_dotenv(env_file)

    @staticmethod
    def _resolve_port(port: Optional[int]) -> int:
        """统一解析端口：显式参数 > PORT 环境变量 > 8000。"""
        if port is not None:
            os.environ["PORT"] = str(port)
            return port

        raw_port = (os.getenv("PORT") or "8000").strip() or "8000"
        try:
            resolved = int(raw_port)
        except ValueError as exc:
            raise ValueError(f"PORT 必须是整数，当前值: {raw_port!r}") from exc

        os.environ["PORT"] = str(resolved)
        return resolved

    @staticmethod
    def _resolve_host(host: Optional[str]) -> str:
        """统一解析监听地址：显式参数 > HOST 环境变量 > 0.0.0.0。"""
        resolved = (host or os.getenv("HOST") or "0.0.0.0").strip() or "0.0.0.0"
        os.environ["HOST"] = resolved
        return resolved
    
    def _is_pg_configured(self) -> bool:
        """检查 PostgreSQL 是否已配置"""
        from agentclaw.config import get_config
        config = get_config()
        return config.database is not None

    def _is_redis_configured(self) -> bool:
        """检查 Redis 是否已配置"""
        from agentclaw.config import get_config
        config = get_config()
        return config.redis is not None

    def _check_dependencies(self) -> None:
        """启动时检查关键外部依赖，输出明确的警告"""
        import shutil
        
        checks = {
            "node": {
                "required_for": "MCP servers (npx), JavaScript skill execution",
                "install": "https://nodejs.org/",
            },
            "npm": {
                "required_for": "Installing MCP servers, Admin Dashboard build",
                "install": "Included with Node.js: https://nodejs.org/",
            },
            "uvx": {
                "required_for": "Running Python-based MCP servers (e.g. mcp-server-fetch)",
                "install": "pip install uv 或 https://docs.astral.sh/uv/getting-started/installation/",
            },
        }
        
        missing = []
        for cmd, info in checks.items():
            if not shutil.which(cmd):
                missing.append((cmd, info))
        
        if missing:
            logger.warning("=" * 60)
            logger.warning("⚠️  缺少外部依赖，部分功能可能不可用:")
            for cmd, info in missing:
                logger.warning(f"  • {cmd}: {info['required_for']}")
                logger.warning(f"    安装: {info['install']}")
            logger.warning("=" * 60)
    
    async def _export_mcp_tools(self) -> None:
        """
        导出 MCP 工具到 JSON 文件
        
        连接所有配置的 MCP Server，获取工具列表并导出到 mcp_tools.json
        """
        import json
        from pathlib import Path
        
        # 查找 mcp.json 配置文件
        mcp_config_paths = [
            Path("mcp.json"),
            Path(".kiro/mcp.json"),
        ]
        
        config_path = None
        for p in mcp_config_paths:
            if p.exists():
                config_path = p
                break
        
        if not config_path:
            logger.info("未找到 mcp.json，跳过 MCP 工具导出")
            return
        
        try:
            from agentclaw.mcp import MCPManager
            
            logger.info(f"正在连接 MCP Server 并导出工具列表...")
            
            manager = MCPManager.from_config(config_path)
            results = await manager.connect_all()
            
            # 统计连接结果
            connected = [name for name, err in results.items() if err is None]
            failed = [(name, err) for name, err in results.items() if err is not None]
            
            if failed:
                for name, err in failed:
                    logger.warning(f"MCP Server '{name}' 连接失败: {err}")
            
            if not connected:
                logger.warning("没有成功连接的 MCP Server，跳过工具导出")
                await manager.disconnect_all()
                return
            
            # 收集所有工具信息
            tools_data = {
                "servers": {},
                "tools": [],
                "tool_count": 0,
            }
            
            for server_name in connected:
                server_tools = manager.list_tools(server_name)
                tools_data["servers"][server_name] = {
                    "tool_count": len(server_tools),
                    "tools": [t.name for t in server_tools],
                }
                
                for tool in server_tools:
                    tools_data["tools"].append({
                        "name": tool.name,
                        "description": tool.description,
                        "server": server_name,
                        "input_schema": tool.input_schema,
                    })
            
            tools_data["tool_count"] = len(tools_data["tools"])
            
            # 写入文件
            output_path = Path("mcp_tools.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(tools_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ MCP 工具已导出: {output_path} ({tools_data['tool_count']} 个工具)")
            
            # 断开连接
            await manager.disconnect_all()
            
        except Exception as e:
            logger.error(f"MCP 工具导出失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _find_admin_dashboard_dir(self) -> str:
        """自动查找 admin-dashboard 目录"""
        # 1. 尝试在 agentclaw 包内查找
        try:
            import agentclaw
            package_dir = Path(agentclaw.__file__).parent
            dashboard_dir = package_dir / "admin-dashboard"
            if dashboard_dir.exists():
                return str(dashboard_dir)
        except Exception:
            pass
        
        # 2. 尝试在当前工作目录查找（向后兼容）
        cwd_dashboard = Path.cwd() / "admin-dashboard"
        if cwd_dashboard.exists():
            return str(cwd_dashboard)
        
        # 3. 尝试在项目根目录查找
        # 假设当前文件在 agentclaw/api/server.py
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        root_dashboard = project_root / "admin-dashboard"
        if root_dashboard.exists():
            return str(root_dashboard)
        
        # 4. 返回默认值（即使不存在）
        return "admin-dashboard"
    
    def _setup_auth(self, auth, api_keys) -> None:
        """配置认证"""
        from agentclaw.api.auth import AuthConfig, APIKeyManager
        
        if auth:
            self.auth_config = auth
        elif api_keys:
            # 从简写配置创建
            self.auth_config = AuthConfig.from_dict({
                "enabled": True,
                "api_keys": api_keys,
            })
        else:
            self.auth_config = AuthConfig(enabled=False)
        
        self.auth_manager = APIKeyManager(self.auth_config)
    
    def _load_config(self) -> None:
        """加载配置文件"""
        if not self.config_path:
            return
        
        if not os.path.exists(self.config_path):
            logger.warning(f"配置文件不存在: {self.config_path}")
            return
        
        try:
            if self.config_path.endswith(".yaml") or self.config_path.endswith(".yml"):
                import yaml
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            elif self.config_path.endswith(".json"):
                import json
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            
            logger.info(f"加载配置文件: {self.config_path}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
    
    # ── 内部中转配置文件 ──────────────────────────────

    def _relay_config_path(self) -> Path:
        """Return the project-scoped relay config path."""
        return Path(self.project_dir).expanduser().resolve() / ".agentclaw" / "relay.json"

    def _write_relay_config(self) -> None:
        """启动时写入中转配置文件，供 skill 脚本通过 /_internal/ 路径访问 API"""
        import json as _json

        relay_path = self._relay_config_path()
        config = {
            "url": f"http://127.0.0.1:{self.port}",
            "pid": os.getpid(),
            "project_dir": str(Path(self.project_dir).expanduser().resolve()),
        }
        if self._internal_relay_url:
            config["internal_url"] = self._internal_relay_url
        try:
            relay_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = relay_path.with_name(f"{relay_path.name}.{os.getpid()}.tmp")
            tmp_path.write_text(_json.dumps(config), encoding="utf-8")
            try:
                tmp_path.chmod(0o600)
            except Exception:
                pass
            os.replace(tmp_path, relay_path)
            try:
                relay_path.chmod(0o600)
            except Exception:
                pass
            logger.info(f"中转配置已写入: {relay_path}")
        except Exception as e:
            logger.warning(f"写入中转配置失败: {e}")

    def _cleanup_relay_config(self) -> None:
        """关闭时清理中转配置文件"""
        import json as _json

        relay_path = self._relay_config_path()
        try:
            if not relay_path.exists():
                return
            cfg = _json.loads(relay_path.read_text(encoding="utf-8"))
            if cfg.get("pid") not in (None, os.getpid()):
                return
            relay_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _create_internal_relay_app(self, target_base_url: str):
        """创建只绑定本机端口的内部中转 ASGI 应用。"""
        import httpx
        from starlette.background import BackgroundTask

        relay_app = FastAPI(
            title="AgentClaw Internal Relay",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )

        async def _relay(request: Request, relay_path: str = ""):
            if not relay_path:
                return JSONResponse(status_code=404, content={"error": "Not found"})

            body = await request.body()
            from agentclaw.api.auth.token import AdminTokenManager

            manager = AdminTokenManager.get_instance()
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower()
                not in {
                    "authorization",
                    "host",
                    "content-length",
                    "connection",
                }
            }
            headers["authorization"] = f"Bearer {manager.token}"

            query = request.url.query.encode("utf-8")
            url = httpx.URL(path=f"/{relay_path}", query=query)
            client = httpx.AsyncClient(
                base_url=target_base_url,
                timeout=None,
            )
            outbound = client.build_request(
                request.method,
                url,
                headers=headers,
                content=body,
            )
            response = await client.send(outbound, stream=True)

            async def _close_response():
                await response.aclose()
                await client.aclose()

            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower()
                not in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                }
            }
            return StreamingResponse(
                response.aiter_raw(),
                status_code=response.status_code,
                headers=response_headers,
                background=BackgroundTask(_close_response),
            )

        relay_app.add_api_route(
            "/_internal/{relay_path:path}",
            _relay,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
        return relay_app

    def _start_internal_relay_server(self) -> None:
        """启动独立本机内部中转端口；调用方无需传任何 key。"""
        if self._internal_relay_server or not self._app:
            return

        import socket
        import threading
        import time

        try:
            import uvicorn
        except ImportError:
            logger.warning("内部中转启动失败：缺少 uvicorn")
            return

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.listen(socket.SOMAXCONN)
            sock.set_inheritable(True)

            target_base_url = f"http://127.0.0.1:{self.port}"
            self._internal_relay_app = self._create_internal_relay_app(target_base_url)
            config = uvicorn.Config(
                self._internal_relay_app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                log_config=None,
                lifespan="off",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=lambda: server.run(sockets=[sock]),
                daemon=True,
            )
            thread.start()

            for _ in range(50):
                if server.started:
                    break
                if not thread.is_alive():
                    break
                time.sleep(0.02)

            if not server.started:
                server.should_exit = True
                if thread.is_alive():
                    thread.join(timeout=2)
                logger.warning("内部中转启动失败：未进入就绪状态")
                self._internal_relay_server = None
                self._internal_relay_thread = None
                self._internal_relay_url = None
                try:
                    sock.close()
                except Exception:
                    pass
                return

            self._internal_relay_server = server
            self._internal_relay_thread = thread
            self._internal_relay_url = f"http://127.0.0.1:{port}"
            logger.info(f"内部中转已启动: {self._internal_relay_url}")
        except Exception as e:
            logger.warning(f"内部中转启动失败: {e}")
            self._internal_relay_server = None
            self._internal_relay_thread = None
            self._internal_relay_url = None
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _stop_internal_relay_server(self) -> None:
        """停止独立本机内部中转端口。"""
        server = self._internal_relay_server
        thread = self._internal_relay_thread
        self._internal_relay_server = None
        self._internal_relay_thread = None
        self._internal_relay_url = None
        if server:
            try:
                server.should_exit = True
            except Exception:
                pass
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def _create_app(self):
        """创建 FastAPI 应用"""
        if not HAS_FASTAPI:
            raise ImportError("需要安装 fastapi: pip install fastapi uvicorn")
        
        app = FastAPI(
            title="AgentClaw API",
            description="AgentClaw workflow execution and management API",
            version=get_version(),
            docs_url="/docs" if self.enable_api_docs else None,
            redoc_url="/redoc" if self.enable_api_docs else None,
            openapi_url="/openapi.json" if self.enable_api_docs else None,
        )
        self._register_error_handlers(app)
        from agentclaw.api.upload_limits import (
            DEFAULT_REQUEST_BODY_LIMIT_BYTES,
            MULTIPART_OVERHEAD_ALLOWANCE_BYTES,
            RequestBodyLimitMiddleware,
            UploadSizeLimitMiddleware,
        )
        from agentclaw.api.routers.public.audio import (
            _public_max_audio_bytes,
            public_room_speech_to_text_path_prefix,
            public_speech_to_text_path_prefix,
        )
        from agentclaw.api.security_headers import SecurityHeadersMiddleware
        from agentclaw.config import get_config

        upload_config = get_config().upload
        app.add_middleware(SecurityHeadersMiddleware)
        try:
            request_body_limit = int(
                os.getenv(
                    "AGENTCLAW_MAX_REQUEST_BODY_BYTES",
                    str(DEFAULT_REQUEST_BODY_LIMIT_BYTES),
                )
            )
        except ValueError:
            request_body_limit = DEFAULT_REQUEST_BODY_LIMIT_BYTES
        app.add_middleware(
            RequestBodyLimitMiddleware,
            max_size=request_body_limit,
            path_prefixes=("/",),
            excluded_path_prefixes=("/api/upload", "/admin/knowledgebases"),
            path_limits={
                public_speech_to_text_path_prefix(): _public_max_audio_bytes(),
                public_room_speech_to_text_path_prefix(): _public_max_audio_bytes(),
            },
        )
        app.add_middleware(
            UploadSizeLimitMiddleware,
            max_size=upload_config.max_size_bytes,
            path_prefixes=("/api/upload", "/admin/knowledgebases"),
            overhead_allowance=MULTIPART_OVERHEAD_ALLOWANCE_BYTES,
        )

        # Startup 事件：初始化追踪器 + 延迟加载提示词
        @app.on_event("startup")
        async def startup_event():
            # 初始化全局数据库管理器
            from agentclaw.database import init_database, get_database, init_file_storage
            from agentclaw.database.manager import PostgresConfig, RedisConfig
            from agentclaw.config import get_config

            config = get_config()

            # 如果配置了数据库，初始化全局数据库管理器
            if config.database or config.redis:
                pg_config = None
                if config.database:
                    pg_config = PostgresConfig(
                        host=config.database.host,
                        port=config.database.port,
                        user=config.database.user,
                        password=config.database.password,
                        database=config.database.database,
                    )

                redis_config = None
                if config.redis:
                    redis_config = RedisConfig(
                        host=config.redis.host,
                        port=config.redis.port,
                        password=config.redis.password,
                    )

                await init_database(postgres=pg_config, redis=redis_config)
                logger.info("Global database manager initialized")
            else:
                logger.info("Database not configured, running in memory mode")

            # 启动资源管理器
            from agentclaw.runtime.resource_manager import get_resource_manager
            rm = get_resource_manager()
            await rm.start()
            logger.info("ResourceManager started")

            from agentclaw.runtime.tracing.db_tracer import auto_setup_tracing
            await auto_setup_tracing()

            # 注册内置智能体
            from agentclaw.api.builtin_agent import register_builtin_workflow
            register_builtin_workflow()

            # 初始化文件存储
            db = get_database()
            init_file_storage(db)
            logger.info("文件存储服务已初始化")

            if db and db.pg_pool and (
                getattr(config.maintenance, "log_retention_days", 0) > 0
                or getattr(config.maintenance, "checkpointer_retention_days", 0) > 0
            ):
                from agentclaw.runtime.maintenance import retention_loop

                app.state.maintenance_retention_task = asyncio.create_task(
                    retention_loop(config=config, db=db)
                )
                logger.info(
                    "维护清理任务已启动: log_retention_days=%s, checkpointer_retention_days=%s",
                    config.maintenance.log_retention_days,
                    config.maintenance.checkpointer_retention_days,
                )

            # 初始化知识库服务
            try:
                if config.knowledgebase.enabled and db and db.pg_pool:
                    from agentclaw.knowledgebase import init_knowledgebase_service

                    await init_knowledgebase_service(db)
                    logger.info("知识库服务已初始化")
                elif config.knowledgebase.enabled:
                    logger.warning("知识库服务未初始化：需要 PostgreSQL 连接")
            except ImportError:
                logger.debug("KnowledgeBase dependencies not installed, skipping")
            except Exception as e:
                logger.warning(f"知识库服务初始化失败: {e}")
            
            # 触发所有工作流的 PromptManager 延迟加载
            # 此时数据库连接已建立，可以从数据库加载提示词
            from agentclaw.api.registry import WorkflowRegistry
            for wf in WorkflowRegistry.list_all():
                try:
                    if hasattr(wf, "_ensure_components"):
                        wf._ensure_components()
                        logger.info(f"工作流 {wf.id} 的组件已初始化（MCP/Skills/PromptManager）")
                except Exception as e:
                    logger.warning(f"工作流 {wf.id} 的组件初始化失败: {e}")
                if wf._prompt_manager and hasattr(wf._prompt_manager, '_ensure_db_loaded'):
                    try:
                        await wf._prompt_manager._ensure_db_loaded()
                        logger.info(f"工作流 {wf.id} 的提示词已延迟加载")
                    except Exception as e:
                        logger.warning(f"工作流 {wf.id} 的提示词延迟加载失败: {e}")
            
            # 初始化定时任务调度器
            try:
                if config.scheduler.enabled and db and db.pg_pool:
                    from agentclaw.scheduler.scheduler import (
                        SchedulerConfig as SchedCfg,
                        WorkflowScheduler,
                    )
                    sched_config = SchedCfg(
                        enabled=config.scheduler.enabled,
                        timezone=config.scheduler.timezone,
                        max_workers=config.scheduler.max_workers,
                        coalesce=config.scheduler.coalesce,
                        max_instances=config.scheduler.max_instances,
                    )
                    await WorkflowScheduler.initialize(sched_config, pg_pool=db.pg_pool)
                    logger.info("定时任务调度器已启动")
            except ImportError:
                logger.debug("Scheduler dependencies not installed, skipping")
            except Exception as e:
                logger.warning(f"定时任务调度器启动失败: {e}")

            # 启动独立本机中转并写入配置文件，供 skill 脚本读取
            self._start_internal_relay_server()
            self._write_relay_config()

            # MCP 工具导出
            if self.export_mcp_tools:
                await self._export_mcp_tools()

            # 初始化 Channel 适配器（飞书/钉钉/企业微信/QQ/微信）
            try:
                from agentclaw.channels import ChannelManager, set_message_log_callback
                from agentclaw.channels.routes import set_channel_manager
                from agentclaw.api.auth.token import WorkflowAPIKeyManager

                wf_api_key = WorkflowAPIKeyManager.get_instance().api_key
                server_url = f"http://127.0.0.1:{self.port}"

                # 优先使用数据库存储
                if db and db.pg_pool:
                    from agentclaw.channels.store import ChannelStore
                    from agentclaw.api.routers.admin.channels import set_channel_store

                    ch_store = ChannelStore(db.pg_pool)
                    await ch_store.init()
                    set_channel_store(ch_store)

                    # 一次性从 channels.json 迁移
                    channels_json = self.project_dir / "channels.json" if self.project_dir else None
                    if channels_json and channels_json.exists():
                        channels, _ = await ch_store.list_channels(limit=1)
                        if not channels:
                            imported = await ch_store.import_from_json(str(channels_json))
                            if imported:
                                logger.info(f"已从 channels.json 迁移 {imported} 个渠道到数据库")

                    # 从数据库加载渠道
                    ch_manager = await ChannelManager.from_store(
                        ch_store,
                        server_base_url=server_url,
                        api_key=wf_api_key,
                    )

                    # 注入消息日志回调
                    set_message_log_callback(ch_store.save_message_log)
                else:
                    # 回退到文件模式
                    channels_config = self.project_dir / "channels.json" if self.project_dir else None
                    if channels_config and channels_config.exists():
                        ch_manager = ChannelManager.from_config(
                            config_path=str(channels_config),
                            server_base_url=server_url,
                            api_key=wf_api_key,
                        )
                    else:
                        ch_manager = ChannelManager()

                set_channel_manager(ch_manager)
                await ch_manager.start_all()
                if ch_manager.list_all():
                    logger.info(f"Channel 适配器已启动: {list(ch_manager.list_all().keys())}")
            except ImportError:
                logger.debug("Channel dependencies not installed, skipping")
            except Exception as e:
                logger.warning(f"Channel 适配器启动失败: {e}")

            logger.info(f"AgentClaw 服务启动完成: http://{self.host}:{self.port}")

        @app.on_event("shutdown")
        async def shutdown_event():
            retention_task = getattr(app.state, "maintenance_retention_task", None)
            if retention_task:
                retention_task.cancel()
                try:
                    await retention_task
                except asyncio.CancelledError:
                    pass

            # 停止 Channel 适配器
            try:
                from agentclaw.channels.routes import _channel_manager
                if _channel_manager:
                    await self._run_shutdown_step(
                        "Channel 适配器",
                        _channel_manager.stop_all(),
                        self._get_timeout("CHANNEL_SHUTDOWN_TIMEOUT", 5.0),
                    )
            except Exception:
                pass
            try:
                from agentclaw.scheduler.scheduler import WorkflowScheduler
                scheduler = WorkflowScheduler.get_instance()
                if scheduler:
                    await self._run_shutdown_step(
                        "定时任务调度器",
                        scheduler.stop(),
                        self._get_timeout("SCHEDULER_SHUTDOWN_TIMEOUT", 5.0),
                    )
            except Exception:
                pass
            # 关闭资源管理器
            try:
                from agentclaw.runtime.resource_manager import get_resource_manager
                rm = get_resource_manager()
                resource_timeout = self._get_timeout("RESOURCE_SHUTDOWN_TIMEOUT", 5.0)
                await self._run_shutdown_step(
                    "ResourceManager",
                    rm.shutdown(timeout=resource_timeout),
                    resource_timeout + 1.0,
                )
            except Exception as e:
                logger.warning(f"ResourceManager shutdown failed: {e}")

            # 关闭全局数据库连接
            try:
                from agentclaw.database import close_database
                await self._run_shutdown_step(
                    "数据库连接",
                    close_database(),
                    self._get_timeout("DATABASE_SHUTDOWN_TIMEOUT", 5.0),
                )
            except Exception as e:
                logger.warning(f"Database shutdown failed: {e}")
            # 清理中转配置文件
            self._stop_internal_relay_server()
            self._cleanup_relay_config()

        # CORS 中间件
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=self.cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Health check
        @app.get("/health", tags=["health"])
        async def health_check():
            return {"status": "ok", "version": get_version()}
        
        # Public API routes (workflow execution, confirm, download, etc.)
        from agentclaw.api.routers.public.router import router as public_router
        app.include_router(public_router)

        # Scheduler API routes
        if self.enable_scheduler_api:
            try:
                from agentclaw.scheduler.api import router as scheduler_router
                app.include_router(scheduler_router, prefix="/api")
            except ImportError:
                pass
        
        # Channel routes (飞书/钉钉/企业微信/QQ/微信)
        if self.enable_channel_routes:
            try:
                from agentclaw.channels.routes import router as channels_router, set_channel_manager
                app.include_router(channels_router, prefix="/api")
                # Channel 初始化在 startup 事件中完成
            except ImportError:
                pass

        # Log Workflow API Key
        from agentclaw.api.auth.token import WorkflowAPIKeyManager
        from agentclaw.api.auth.utils import mask_secret
        workflow_api_key_manager = WorkflowAPIKeyManager.get_instance()
        logger.info(f"Workflow API Key: {mask_secret(workflow_api_key_manager.api_key)}")
        
        # MCP Server routes
        if self.enable_mcp_routes:
            self._register_mcp_routes(app)
        
        # Admin API
        if self.enable_admin:
            self._register_admin_routes(app)
        
        # Admin Dashboard 静态文件（挂载到同一端口）
        if self.enable_admin_dashboard:
            self._mount_admin_dashboard(app)
        
        return app
    
    def _register_mcp_routes(self, app) -> None:
        """注册 MCP Server 路由"""
        from agentclaw.mcp.token_manager import (
            MCPTokenManager, MCPServerRegistry,
            get_mcp_input_schema, handle_mcp_tool_call,
        )
        from agentclaw.api.registry import WorkflowRegistry
        
        # 初始化 MCP Token 管理器
        mcp_token_manager = MCPTokenManager.get_instance()
        mcp_registry = MCPServerRegistry.get_instance()
        
        # 注册所有启用 MCP 的工作流
        for wf in WorkflowRegistry.list_all():
            if wf.publish_as_mcp:
                mcp_registry.register(wf)
        
        # 打印 MCP Token
        endpoints = mcp_registry.get_all_mcp_server_names()
        if endpoints:
            from agentclaw.api.auth.utils import mask_secret

            logger.info(f"MCP Token: {mask_secret(mcp_token_manager.token)}")
            logger.info(f"MCP 端点: {endpoints}")
        
        def verify_mcp_token(request: Request) -> bool:
            """验证 MCP Token（默认仅从 Authorization header 获取）。"""
            auth_header = request.headers.get("Authorization", "")
            token = ""
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            if (
                not token
                and os.getenv("AGENTCLAW_ALLOW_QUERY_TOKENS", "").lower() in {"1", "true", "yes"}
            ):
                token = request.query_params.get("token", "")
            return mcp_token_manager.verify(token)
        
        # MCP 端点列表
        @app.get("/mcp")
        async def list_mcp_endpoints(request: Request):
            """列出所有 MCP 端点"""
            if not verify_mcp_token(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid MCP token"}
                )
            return mcp_registry.list_endpoints()
        
        # SSE 端点（独立工作流）
        @app.get("/mcp/{endpoint_name}/sse")
        async def mcp_sse_endpoint(endpoint_name: str, request: Request):
            """MCP SSE 端点"""
            if not verify_mcp_token(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid MCP token"}
                )
            
            workflows, published_tools = mcp_registry.get_endpoint_items(endpoint_name)

            if not workflows and not published_tools:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"MCP endpoint '{endpoint_name}' not found"}
                )
            
            # 返回 SSE 流
            return StreamingResponse(
                self._mcp_sse_handler(endpoint_name, workflows, request),
                media_type="text/event-stream",
            )
        
        # MCP 消息端点（处理 JSON-RPC）
        @app.post("/mcp/{endpoint_name}/message")
        async def mcp_message_endpoint(endpoint_name: str, request: Request):
            """MCP 消息端点（JSON-RPC）"""
            if not verify_mcp_token(request):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid MCP token"}
                )
            
            workflows, published_tools = mcp_registry.get_endpoint_items(endpoint_name)

            if not workflows and not published_tools:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"MCP endpoint '{endpoint_name}' not found"}
                )
            
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid JSON body"}
                )
            
            # 处理 JSON-RPC 请求
            response = await self._handle_mcp_jsonrpc(endpoint_name, workflows, published_tools, body)
            return JSONResponse(content=response)
    
    async def _mcp_sse_handler(self, endpoint_name: str, workflows: list, request: Request):
        """MCP SSE 处理器"""
        import json
        
        # 发送初始化消息
        yield f"event: endpoint\ndata: {json.dumps({'endpoint': endpoint_name})}\n\n"
        
        # 保持连接
        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
        except asyncio.CancelledError:
            pass
    
    async def _handle_mcp_jsonrpc(self, endpoint_name: str, workflows: list, published_tools: list, body: dict) -> dict:
        """处理 MCP JSON-RPC 请求"""
        from agentclaw.mcp.token_manager import get_mcp_input_schema, handle_mcp_tool_call, handle_mcp_published_tool_call
        
        method = body.get("method", "")
        params = body.get("params", {})
        request_id = body.get("id")
        
        # 构建工作流映射
        workflow_map = {wf.id: wf for wf in workflows}
        tool_map = {tool.name: tool for tool in published_tools}
        
        if method == "initialize":
            # 初始化响应
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": f"agentclaw-{endpoint_name}",
                        "version": get_version(),
                    },
                },
            }
        
        elif method == "tools/list":
            # 列出工具
            tools = []
            for wf in workflows:
                tools.append({
                    "name": wf.id,
                    "description": wf.desc or wf.description or f"工作流: {wf.name}",
                    "inputSchema": get_mcp_input_schema(wf),
                })
            for tool in published_tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                })
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools},
            }
        
        elif method == "tools/call":
            # 调用工具
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            
            workflow = workflow_map.get(tool_name)
            published_tool = tool_map.get(tool_name)
            if not workflow and not published_tool:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found",
                    },
                }
            
            if workflow:
                result = await handle_mcp_tool_call(workflow, arguments)
            else:
                assert published_tool is not None
                result = await handle_mcp_published_tool_call(published_tool, arguments)
            
            if result.get("success"):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": result.get("answer", ""),
                            }
                        ],
                    },
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": result.get("error", "Unknown error"),
                    },
                }
        
        elif method == "notifications/initialized":
            # 初始化完成通知，不需要响应
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }

    def _register_error_handlers(self, app) -> None:
        from agentclaw.api.schemas.common import ErrorCode

        @app.exception_handler(Exception)
        async def global_exception_handler(request, exc: Exception):
            import traceback

            error_detail = traceback.format_exc()
            logger.error(f"未捕获的异常: {exc}\n{error_detail}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "服务器内部错误",
                    "code": ErrorCode.UNKNOWN_ERROR,
                },
            )

    def _register_admin_routes(self, app) -> None:
        """注册 Admin API 路由"""
        try:
            from fastapi import HTTPException
            from fastapi.exceptions import RequestValidationError
            from agentclaw.api.auth import AuthMiddleware, AdminTokenManager
            from agentclaw.api.auth.utils import mask_secret
            from agentclaw.api.schemas.common import ErrorCode, APIError

            # 初始化 AdminTokenManager 并打印 token
            manager = AdminTokenManager.get_instance()
            logger.info(f"Admin API Token: {mask_secret(manager.token)}")

            # 注册统一认证中间件
            app.add_middleware(AuthMiddleware)

            from agentclaw.api.routers.admin import router as admin_router

            # 注册 Admin 路由
            app.include_router(admin_router)
            
            # 统一 HTTPException 错误格式
            @app.exception_handler(HTTPException)
            async def http_exception_handler(request, exc: HTTPException):
                # 根据状态码推断错误编码
                code_map = {
                    400: ErrorCode.INVALID_REQUEST,
                    401: ErrorCode.UNAUTHORIZED,
                    403: ErrorCode.FORBIDDEN,
                    404: ErrorCode.NOT_FOUND,
                }
                code = code_map.get(exc.status_code, ErrorCode.UNKNOWN_ERROR)
                
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": str(exc.detail),
                        "code": code,
                    }
                )
            
            # 统一 APIError 错误格式
            @app.exception_handler(APIError)
            async def api_error_handler(request, exc: APIError):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": exc.error,
                        "code": exc.code,
                        "detail": exc.detail,
                    }
                )
            
            # 统一验证错误格式
            @app.exception_handler(RequestValidationError)
            async def validation_exception_handler(request, exc: RequestValidationError):
                errors = exc.errors()
                error_msg = "; ".join([f"{e['loc'][-1]}: {e['msg']}" for e in errors])
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": "请求参数验证失败",
                        "code": ErrorCode.VALIDATION_ERROR,
                        "detail": error_msg,
                    }
                )
            
            logger.info(f"注册 Admin API: /admin/*")
        except ImportError as e:
            logger.warning(f"Admin 模块加载失败，使用简化版 Admin API: {e}")
            self._register_simple_admin_routes(app)
    
    def _register_simple_admin_routes(self, app) -> None:
        """注册简化版 Admin API 路由（兼容旧版）"""
        from fastapi import HTTPException
        from pydantic import BaseModel
        
        class PromptUpdate(BaseModel):
            content: str
            updated_by: str = "admin"
        
        @app.get(f"{self.admin_prefix}/prompts")
        async def list_prompts(workflow_id: Optional[str] = None):
            """列出所有提示词"""
            from agentclaw.api.registry import WorkflowRegistry
            
            result = []
            for wf in WorkflowRegistry.list_all():
                if workflow_id and wf.id != workflow_id:
                    continue
                if wf._prompt_manager:
                    for info in wf._prompt_manager.list_all():
                        info["workflow_id"] = wf.id
                        result.append(info)
            return {"prompts": result}
        
        @app.get(f"{self.admin_prefix}/prompts/{{workflow_id}}/{{prompt_key}}")
        async def get_prompt(workflow_id: str, prompt_key: str):
            """获取单个提示词详情"""
            from agentclaw.api.registry import WorkflowRegistry
            
            wf = WorkflowRegistry.get(workflow_id)
            if not wf:
                raise HTTPException(404, f"工作流 '{workflow_id}' 不存在")
            if not wf._prompt_manager:
                raise HTTPException(404, "工作流未配置 PromptManager")
            
            info = wf._prompt_manager.get_prompt_info(prompt_key)
            if not info:
                raise HTTPException(404, f"提示词 '{prompt_key}' 不存在")
            
            info["workflow_id"] = workflow_id
            return info
        
        @app.put(f"{self.admin_prefix}/prompts/{{workflow_id}}/{{prompt_key}}")
        async def update_prompt(workflow_id: str, prompt_key: str, data: PromptUpdate):
            """更新提示词（热更新）"""
            from agentclaw.api.registry import WorkflowRegistry
            
            wf = WorkflowRegistry.get(workflow_id)
            if not wf:
                raise HTTPException(404, f"工作流 '{workflow_id}' 不存在")
            if not wf._prompt_manager:
                raise HTTPException(404, "工作流未配置 PromptManager")
            
            try:
                result = wf._prompt_manager.update_prompt(prompt_key, data.content, data.updated_by)
                result["workflow_id"] = workflow_id
                return result
            except KeyError as e:
                raise HTTPException(404, str(e))
        
        @app.post(f"{self.admin_prefix}/prompts/{{workflow_id}}/{{prompt_key}}/reset")
        async def reset_prompt(workflow_id: str, prompt_key: str, updated_by: str = "admin"):
            """重置提示词为默认值"""
            from agentclaw.api.registry import WorkflowRegistry
            
            wf = WorkflowRegistry.get(workflow_id)
            if not wf:
                raise HTTPException(404, f"工作流 '{workflow_id}' 不存在")
            if not wf._prompt_manager:
                raise HTTPException(404, "工作流未配置 PromptManager")
            
            try:
                result = wf._prompt_manager.reset_prompt(prompt_key, updated_by)
                result["workflow_id"] = workflow_id
                return result
            except (KeyError, ValueError) as e:
                raise HTTPException(400, str(e))
        
        @app.get(f"{self.admin_prefix}/workflows")
        async def admin_list_workflows():
            from agentclaw.api.registry import WorkflowRegistry
            return {"workflows": WorkflowRegistry.list_info()}
        
        logger.info(f"注册简化版 Admin API: {self.admin_prefix}/*")
    
    def _start_admin_dashboard(self) -> None:
        """构建 Admin Dashboard（如果需要）"""
        import subprocess
        import shutil
        
        dashboard_path = Path(self.admin_dashboard_dir)
        dist_path = dashboard_path / "dist"
        
        if not dashboard_path.exists():
            logger.warning(f"⚠️ Admin Dashboard 目录不存在: {self.admin_dashboard_dir}")
            return
        
        # 如果 dist 目录已存在且不强制重新构建，跳过构建
        if dist_path.exists() and not os.getenv("REBUILD_DASHBOARD", "").lower() in ("true", "1", "yes"):
            logger.info(f"✅ Admin Dashboard 已构建，使用现有文件: {dist_path}")
            return
        
        # 检查是否安装了 npm
        npm_path = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
        if not npm_path:
            logger.warning("⚠️ npm 未安装，无法构建 Admin Dashboard")
            return
        
        # 检查 node_modules 是否存在
        node_modules = dashboard_path / "node_modules"
        if not node_modules.exists():
            logger.info("📦 安装 Admin Dashboard 依赖...")
            try:
                subprocess.run(
                    [npm_path, "install"],
                    cwd=str(dashboard_path),
                    check=True,
                    capture_output=True,
                )
                logger.info("✅ 依赖安装完成")
            except (subprocess.CalledProcessError, OSError) as e:
                stderr = getattr(e, "stderr", None)
                logger.error(f"❌ 依赖安装失败: {stderr.decode() if stderr else e}")
                return
        
        # 构建生产版本
        logger.info("🔨 构建 Admin Dashboard...")
        try:
            subprocess.run(
                [npm_path, "run", "build"],
                cwd=str(dashboard_path),
                check=True,
                capture_output=True,
            )
            logger.info("✅ Admin Dashboard 构建完成")
        except (subprocess.CalledProcessError, OSError) as e:
            stderr = getattr(e, "stderr", None)
            logger.error(f"❌ Admin Dashboard 构建失败: {stderr.decode() if stderr else e}")
    
    def _mount_admin_dashboard(self, app) -> None:
        """挂载 Admin Dashboard 静态文件到 FastAPI"""
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse, RedirectResponse

        class CachedAssetStaticFiles(StaticFiles):
            def file_response(self, full_path, stat_result, scope, status_code=200):
                response = super().file_response(full_path, stat_result, scope, status_code)
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                if "Pragma" in response.headers:
                    del response.headers["Pragma"]
                if "Expires" in response.headers:
                    del response.headers["Expires"]
                return response
        
        dashboard_path = Path(self.admin_dashboard_dir)
        dist_path = dashboard_path / "dist"
        
        if not dist_path.exists():
            logger.warning(f"⚠️ Admin Dashboard 未构建，请先运行 npm run build: {dist_path}")
            return
        
        # 挂载静态资源（JS、CSS、图片等）
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.mount("/dashboard/assets", CachedAssetStaticFiles(directory=str(assets_path)), name="dashboard-assets")
        
        # 根路径重定向到 Dashboard
        @app.get("/")
        async def redirect_to_dashboard():
            """重定向到 Admin Dashboard"""
            return RedirectResponse(url="/dashboard")
        
        # 兼容旧版 /agent/{workflow_id} 入口，重定向到需要登录的 Dashboard 对话页
        @app.get("/agent/{workflow_id}")
        async def serve_public_agent(workflow_id: str):
            """
            Legacy agent entrypoint.

            The chat page is now part of the authenticated Dashboard surface.
            """
            return RedirectResponse(url=f"/dashboard/workflows/{workflow_id}/chat")
        
        # Dashboard 入口页面
        @app.get("/dashboard")
        @app.get("/dashboard/{path:path}")
        async def serve_dashboard(path: str = ""):
            """服务 Admin Dashboard SPA"""
            if self.dashboard_mode == "public-chat":
                normalized = path.strip("/")
                public_chat_path = normalized.startswith("agent/")
                if normalized and not public_chat_path:
                    return JSONResponse(status_code=404, content={"error": "Not found"})
            index_file = dist_path / "index.html"
            if index_file.exists():
                return FileResponse(
                    str(index_file),
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0"
                    }
                )
            return JSONResponse(
                status_code=404,
                content={"error": "Admin Dashboard not found"}
            )

        # Public Square 入口页面（与 /dashboard 后台入口分离）
        @app.get("/square")
        @app.get("/square/{path:path}")
        async def serve_public_square(path: str = ""):
            """服务公开智能体广场 SPA。"""
            normalized = path.strip("/")
            if normalized and not normalized.startswith("agent/"):
                return JSONResponse(status_code=404, content={"error": "Not found"})
            index_file = dist_path / "index.html"
            if index_file.exists():
                return FileResponse(
                    str(index_file),
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0"
                    }
                )
            return JSONResponse(
                status_code=404,
                content={"error": "Public Square not found"}
            )
        
        logger.info(f"✅ Admin Dashboard 已挂载: /dashboard")
        logger.info(f"✅ 智能体 Dashboard 入口: /agent/{{workflow_id}}")
    
    def _stop_admin_dashboard(self) -> None:
        """停止 Admin Dashboard（保留用于兼容性）"""
        pass

    def _get_timeout(self, env_name: str, default: float) -> float:
        """读取超时环境变量，非法值回退默认值。"""
        raw_value = os.getenv(env_name, "").strip()
        if not raw_value:
            return default
        try:
            value = float(raw_value)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            logger.warning(f"{env_name}={raw_value!r} 不是有效超时秒数，使用默认值 {default}")
            return default

    async def _run_shutdown_step(self, name: str, awaitable, timeout: float) -> None:
        """执行单个关闭步骤，避免某个后台资源阻塞 Ctrl+C 退出。"""
        try:
            if timeout == 0:
                await awaitable
            else:
                await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"{name} 关闭超时（{timeout:.1f}s），继续退出")
        except Exception as e:
            logger.warning(f"{name} 关闭失败: {e}")

    def run(self) -> None:
        """启动服务器"""
        # 加载配置
        self._load_config()

        # 构建 Admin Dashboard（如果启用且需要）
        # 必须在创建 FastAPI app 前完成，否则 dist 首次生成后不会被挂载。
        if self.enable_admin_dashboard:
            self._start_admin_dashboard()

        # 创建应用
        self._app = self._create_app()

        # 启动服务器
        try:
            import uvicorn
            import logging
            
            # 配置 uvicorn 访问日志过滤器
            # 过滤掉调试会话轮询请求，减少日志刷屏
            class DebugPollFilter(logging.Filter):
                def filter(self, record):
                    # 过滤 GET /admin/debug/sessions/{id} 请求
                    msg = record.getMessage()
                    if 'GET /admin/debug/sessions/' in msg and 'HTTP/1.1" 200' in msg:
                        return False
                    return True
            
            # 添加过滤器到 uvicorn 访问日志
            uvicorn_access_logger = logging.getLogger("uvicorn.access")
            uvicorn_access_logger.addFilter(DebugPollFilter())
            
        except ImportError:
            raise ImportError("需要安装 uvicorn: pip install uvicorn")
        
        current_log_file = get_current_log_file() or str(self.log_file)
        logger.info(f"启动服务器: http://{self.host}:{self.port}")
        logger.info(f"日志文件: {current_log_file}")
        print(f"INFO | agentclaw.api.server | 启动服务器: http://{self.host}:{self.port}", flush=True)
        print(f"INFO | agentclaw.api.server | 日志文件: {current_log_file}", flush=True)
        
        try:
            uvicorn.run(
                self._app,
                host=self.host,
                port=self.port,
                workers=self.workers if not self.reload else 1,
                reload=self.reload,
                log_config=None,
                loop="asyncio",
                timeout_graceful_shutdown=int(self._get_timeout("SERVER_GRACEFUL_SHUTDOWN_TIMEOUT", 10.0)),
            )
        finally:
            self._stop_internal_relay_server()
            # 停止 Admin Dashboard
            self._stop_admin_dashboard()
    
    @property
    def app(self):
        """获取 FastAPI 应用实例（用于测试或手动配置）"""
        if self._app is None:
            self._load_config()
            self._app = self._create_app()
        return self._app
    
    def start_background(self, wait: float = 1.0) -> "BackgroundServer":
        """
        在后台启动服务器（用于测试或异步场景）
        
        Args:
            wait: 启动后等待时间（秒）
        
        Returns:
            BackgroundServer 对象，可调用 stop() 停止
        
        Example:
            server = AgentClawServer(port=8765, api_keys={...})
            bg = server.start_background()
            
            # 执行测试...
            
            bg.stop()  # 停止服务器
        """
        import threading
        import time
        
        try:
            import uvicorn
        except ImportError:
            raise ImportError("需要安装 uvicorn: pip install uvicorn")
        
        app = self.app
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        uvi_server = uvicorn.Server(config)
        
        thread = threading.Thread(target=uvi_server.run, daemon=True)
        thread.start()
        
        time.sleep(wait)
        logger.info(f"后台服务器已启动: http://{self.host}:{self.port}")
        
        return BackgroundServer(uvi_server, thread, f"http://{self.host}:{self.port}")


class BackgroundServer:
    """后台服务器句柄"""
    
    def __init__(self, server, thread, url: str):
        self._server = server
        self._thread = thread
        self.url = url
    
    def stop(self):
        """停止服务器"""
        self._server.should_exit = True
        self._thread.join(timeout=2)
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.stop()


def create_app(
    agents_dir: str = "agents",
    config: Optional[str] = None,
) -> Any:
    """
    创建 FastAPI 应用（用于 Gunicorn 等部署）
    
    Example:
        # gunicorn agentclaw.api.server:create_app() -w 4
    """
    server = AgentClawServer(
        agents_dir=agents_dir,
        config=config,
    )
    return server.app
