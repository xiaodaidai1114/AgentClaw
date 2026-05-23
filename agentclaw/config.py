"""
AgentClaw 统一配置管理

从环境变量和配置文件中加载配置，提供统一的访问接口。
支持：
- .env 文件自动加载
- models.json 模型配置
- mcp.json MCP 工具配置
- skills/ 目录发现
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from agentclaw.logger.config import get_logger
from agentclaw.platform_compat import get_service_host_fallback, normalize_service_host

logger = get_logger(__name__)


def _data_dir_child(*parts: str) -> str:
    """Return a path under AGENTCLAW_DATA_DIR, or an empty string when unset."""
    data_dir = os.getenv("AGENTCLAW_DATA_DIR", "").strip()
    if not data_dir:
        return ""
    return str(Path(data_dir).expanduser().joinpath(*parts))


def _looks_like_venv_entry_dir(path: Path) -> bool:
    """Whether a path looks like a virtualenv Scripts/bin directory."""
    name = path.name.lower()
    if name not in {"scripts", "bin"}:
        return False
    parent = path.parent
    return (
        (parent / "pyvenv.cfg").exists()
        or parent.name.lower() in {".venv", "venv"}
        or (parent / "lib").exists()
        or (parent / "lib64").exists()
    )


def _has_project_markers(path: Path) -> bool:
    """Whether a directory looks like an AgentClaw project root."""
    return any(
        (path / marker).exists()
        for marker in ("server.py", "agents", "skills", "models.json", "mcp.json", ".env")
    )


@dataclass
class DatabaseConfig:
    """数据库配置"""
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "agentclaw"
    pool_min_size: int = 2
    pool_max_size: int = 10

    @classmethod
    def from_env(cls) -> Optional["DatabaseConfig"]:
        """从环境变量加载"""
        if not os.getenv("PG_HOST"):
            return None
        host = os.getenv("PG_HOST", "127.0.0.1")
        normalized_host = normalize_service_host(host)
        fallback = get_service_host_fallback(host)
        if fallback and normalized_host == fallback:
            logger.warning(f"检测到 PG_HOST={host}，当前为宿主机运行，自动回退到 {fallback}")
        return cls(
            host=normalized_host,
            port=int(os.getenv("PG_PORT", "5432")),
            user=os.getenv("PG_USER", "postgres"),
            password=os.getenv("PG_PASSWORD", ""),
            database=os.getenv("PG_DATABASE", "agentclaw"),
            pool_min_size=int(os.getenv("PG_POOL_MIN_SIZE", "2")),
            pool_max_size=int(os.getenv("PG_POOL_MAX_SIZE", "10")),
        )


@dataclass
class RedisConfig:
    """Redis 配置"""
    host: str = "127.0.0.1"
    port: int = 6379
    password: str = ""
    pool_max_connections: int = 20

    @classmethod
    def from_env(cls) -> Optional["RedisConfig"]:
        """从环境变量加载"""
        if not os.getenv("REDIS_HOST"):
            return None
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        normalized_host = normalize_service_host(host)
        fallback = get_service_host_fallback(host)
        if fallback and normalized_host == fallback:
            logger.warning(f"检测到 REDIS_HOST={host}，当前为宿主机运行，自动回退到 {fallback}")
        return cls(
            host=normalized_host,
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD", ""),
            pool_max_connections=int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "20")),
        )


@dataclass
class AuthConfig:
    """认证配置"""
    admin_token: Optional[str] = None
    workflow_api_key: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AuthConfig":
        """从环境变量加载"""
        return cls(
            admin_token=os.getenv("ADMIN_TOKEN"),
            workflow_api_key=os.getenv("WORKFLOW_API_KEY"),
        )


@dataclass
class WorkflowConfig:
    """工作流配置"""
    timeout: int = 300
    recursion_limit: int = 0
    max_tool_rounds: int = 0  # 0 = 不限制
    max_context_messages: int = 0  # 0 = 不限制
    tool_result_max_length: int = 20000
    max_message_length: int = 0

    @classmethod
    def from_env(cls) -> "WorkflowConfig":
        """从环境变量加载"""
        return cls(
            timeout=int(os.getenv("WORKFLOW_TIMEOUT", "300")),
            recursion_limit=int(os.getenv("WORKFLOW_RECURSION_LIMIT", "0")),
            max_tool_rounds=int(os.getenv("MAX_TOOL_ROUNDS", "0")),
            max_context_messages=int(os.getenv("MAX_CONTEXT_MESSAGES", "0")),
            tool_result_max_length=int(os.getenv("TOOL_RESULT_MAX_LENGTH", "20000")),
            max_message_length=int(os.getenv("MAX_MESSAGE_LENGTH", "0")),
        )


@dataclass
class UploadConfig:
    """文件上传与存储配置"""
    upload_dir: str = "./.storage"
    max_size_mb: int = 20
    # MinIO (可选)
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "agentclaw"
    minio_secure: bool = True

    @classmethod
    def from_env(cls) -> "UploadConfig":
        """从环境变量加载"""
        return cls(
            upload_dir=(
                os.getenv("UPLOAD_DIR")
                or os.getenv("FILE_STORAGE_DIR")
                or _data_dir_child("storage")
                or "./.storage"
            ),
            max_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", ""),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", ""),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", ""),
            minio_bucket=os.getenv("MINIO_BUCKET", "agentclaw"),
            minio_secure=os.getenv("MINIO_SECURE", "true").lower() in ("true", "1", "yes"),
        )

    @property
    def max_size_bytes(self) -> int:
        """最大文件大小（字节）"""
        return self.max_size_mb * 1024 * 1024

    @property
    def use_minio(self) -> bool:
        """是否使用 MinIO 存储"""
        return bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key)


@dataclass
class KnowledgeBaseConfig:
    """知识库配置"""
    enabled: bool = True
    storage_dir: str = "./.knowledgebase"
    parser_cache_dir: str = "./.knowledgebase/parsed"
    backend: str = "milvus"
    default_retrieval_mode: str = "hybrid"
    prefer_builtin_hybrid: bool = True
    dense_candidate_multiplier: int = 3
    keyword_candidate_multiplier: int = 3
    rerank_candidate_multiplier: int = 3
    milvus_uri: str = ""
    milvus_token: str = ""
    milvus_collection_prefix: str = "agentclaw_kb"
    milvus_metric_type: str = "COSINE"
    milvus_index_type: str = "AUTOINDEX"
    default_top_k: int = 8
    chunk_size: int = 1200
    chunk_overlap: int = 200
    default_knowledgebase_id: str = ""
    default_embedding_model: str = ""
    default_rerank_model: str = ""
    default_llm_model: str = ""

    @classmethod
    def from_env(cls) -> "KnowledgeBaseConfig":
        """从环境变量加载"""
        return cls(
            enabled=os.getenv("KNOWLEDGEBASE_ENABLED", "true").lower() in ("true", "1", "yes"),
            storage_dir=os.getenv("KNOWLEDGEBASE_STORAGE_DIR") or _data_dir_child("knowledgebase") or "./.knowledgebase",
            parser_cache_dir=(
                os.getenv("KNOWLEDGEBASE_PARSER_CACHE_DIR")
                or _data_dir_child("knowledgebase", "parsed")
                or "./.knowledgebase/parsed"
            ),
            backend=os.getenv("KNOWLEDGEBASE_BACKEND", "milvus"),
            default_retrieval_mode=os.getenv("KNOWLEDGEBASE_RETRIEVAL_MODE", "hybrid"),
            prefer_builtin_hybrid=os.getenv("KNOWLEDGEBASE_PREFER_BUILTIN_HYBRID", "true").lower() in ("true", "1", "yes"),
            dense_candidate_multiplier=int(os.getenv("KNOWLEDGEBASE_DENSE_CANDIDATE_MULTIPLIER", "3")),
            keyword_candidate_multiplier=int(os.getenv("KNOWLEDGEBASE_KEYWORD_CANDIDATE_MULTIPLIER", "3")),
            rerank_candidate_multiplier=int(os.getenv("KNOWLEDGEBASE_RERANK_CANDIDATE_MULTIPLIER", "3")),
            milvus_uri=os.getenv("MILVUS_URI", "").strip(),
            milvus_token=os.getenv("MILVUS_TOKEN", ""),
            milvus_collection_prefix=os.getenv("MILVUS_COLLECTION_PREFIX", "agentclaw_kb"),
            milvus_metric_type=os.getenv("MILVUS_METRIC_TYPE", "COSINE"),
            milvus_index_type=os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX"),
            default_top_k=int(os.getenv("KNOWLEDGEBASE_DEFAULT_TOP_K", "8")),
            chunk_size=int(os.getenv("KNOWLEDGEBASE_CHUNK_SIZE", "1200")),
            chunk_overlap=int(os.getenv("KNOWLEDGEBASE_CHUNK_OVERLAP", "200")),
            default_knowledgebase_id=os.getenv("DEFAULT_KNOWLEDGEBASE_ID", ""),
            default_embedding_model=os.getenv("KNOWLEDGEBASE_DEFAULT_EMBEDDING_MODEL", ""),
            default_rerank_model=os.getenv("KNOWLEDGEBASE_DEFAULT_RERANK_MODEL", ""),
            default_llm_model=os.getenv("KNOWLEDGEBASE_DEFAULT_LLM_MODEL", ""),
        )


@dataclass
class ProjectConfig:
    """项目配置（自动发现）"""
    project_dir: Path
    skills_dir: Optional[Path] = None
    mcp_config: Optional[Path] = None
    models_config: Optional[Path] = None
    env_file: Optional[Path] = None

    @classmethod
    def discover(cls, base_dir: Optional[Path] = None) -> "ProjectConfig":
        """
        自动发现项目配置文件

        查找顺序：
        1. 入口脚本所在目录（sys.argv[0]）
        2. 当前工作目录（CWD）
        3. 指定的 base_dir
        """
        import sys

        candidates = []

        # 入口脚本目录
        if sys.argv and sys.argv[0]:
            script_path = Path(sys.argv[0]).expanduser()
            try:
                script_dir = script_path.resolve().parent
            except Exception:
                script_dir = script_path.parent
            if not _looks_like_venv_entry_dir(script_dir):
                candidates.append(script_dir)

        # CWD
        cwd = Path.cwd().resolve()
        if cwd not in candidates:
            candidates.append(cwd)

        # 指定目录
        if base_dir:
            base_dir = Path(base_dir).resolve()
            if base_dir not in candidates:
                candidates.append(base_dir)

        # 查找配置文件
        project_dir = next((d for d in candidates if _has_project_markers(d)), None)
        if project_dir is None:
            project_dir = base_dir if base_dir else (candidates[0] if candidates else cwd)
        skills_dir = None
        mcp_config = None
        models_config = None
        env_file = None

        for d in candidates:
            if skills_dir is None and (d / "skills").exists():
                skills_dir = d / "skills"

            if mcp_config is None:
                for name in ("mcp.json", ".kiro/mcp.json"):
                    if (d / name).exists():
                        mcp_config = d / name
                        break

            if models_config is None and (d / "models.json").exists():
                models_config = d / "models.json"

            if env_file is None and (d / ".env").exists():
                env_file = d / ".env"

        config = cls(
            project_dir=project_dir,
            skills_dir=skills_dir,
            mcp_config=mcp_config,
            models_config=models_config,
            env_file=env_file,
        )

        logger.info(f"项目配置发现: {project_dir}")
        if skills_dir:
            logger.info(f"  - skills: {skills_dir}")
        if mcp_config:
            logger.info(f"  - mcp: {mcp_config}")
        if models_config:
            logger.info(f"  - models: {models_config}")
        if env_file:
            logger.info(f"  - env: {env_file}")

        return config


@dataclass
class SchedulerConfig:
    """定时任务配置"""
    enabled: bool = True
    timezone: str = "Asia/Shanghai"
    max_workers: int = 10
    coalesce: bool = True
    max_instances: int = 1

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        """从环境变量加载"""
        return cls(
            enabled=os.getenv("SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes"),
            timezone=os.getenv("SCHEDULER_TIMEZONE", "Asia/Shanghai"),
            max_workers=int(os.getenv("SCHEDULER_MAX_WORKERS", "10")),
            coalesce=os.getenv("SCHEDULER_COALESCE", "true").lower() in ("true", "1", "yes"),
            max_instances=int(os.getenv("SCHEDULER_MAX_INSTANCES", "1")),
        )


@dataclass
class AgentClawConfig:
    """AgentClaw 全局配置"""
    database: Optional[DatabaseConfig] = None
    redis: Optional[RedisConfig] = None
    auth: AuthConfig = field(default_factory=AuthConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    knowledgebase: KnowledgeBaseConfig = field(default_factory=KnowledgeBaseConfig)
    project: ProjectConfig = field(default_factory=lambda: ProjectConfig.discover())
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    _instance: Optional["AgentClawConfig"] = None

    @classmethod
    def load(cls, env_file: Optional[str] = None, reload: bool = False) -> "AgentClawConfig":
        """
        加载配置（单例模式）

        Args:
            env_file: .env 文件路径，None 表示自动查找
            reload: 是否强制重新加载
        """
        if cls._instance is not None and not reload:
            return cls._instance

        # 加载 .env 文件
        from dotenv import load_dotenv

        if env_file:
            env_path = Path(env_file)
            if env_path.exists():
                load_dotenv(env_path)
                logger.info(f"加载环境变量: {env_path}")
        else:
            # 自动查找 .env
            project = ProjectConfig.discover()
            if project.env_file:
                load_dotenv(project.env_file)
                logger.info(f"加载环境变量: {project.env_file}")
            else:
                load_dotenv()  # 从 CWD 加载

        # 创建配置实例
        config = cls(
            database=DatabaseConfig.from_env(),
            redis=RedisConfig.from_env(),
            auth=AuthConfig.from_env(),
            workflow=WorkflowConfig.from_env(),
            upload=UploadConfig.from_env(),
            knowledgebase=KnowledgeBaseConfig.from_env(),
            project=ProjectConfig.discover(),
            scheduler=SchedulerConfig.from_env(),
        )

        try:
            from agentclaw.api.services.settings_service import apply_saved_system_settings
            apply_saved_system_settings(config)
        except Exception as e:
            logger.warning(f"加载本地系统设置覆盖失败: {e}")

        cls._instance = config
        logger.info("AgentClaw 配置加载完成")

        return config

    @classmethod
    def get(cls) -> "AgentClawConfig":
        """获取配置实例（如果未加载则自动加载）"""
        if cls._instance is None:
            return cls.load()
        return cls._instance

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于调试）"""
        return {
            "database": {
                "host": self.database.host if self.database else None,
                "port": self.database.port if self.database else None,
                "database": self.database.database if self.database else None,
            } if self.database else None,
            "redis": {
                "host": self.redis.host if self.redis else None,
                "port": self.redis.port if self.redis else None,
            } if self.redis else None,
            "auth": {
                "admin_token": "***" if self.auth.admin_token else None,
                "workflow_api_key": "***" if self.auth.workflow_api_key else None,
            },
            "workflow": {
                "timeout": self.workflow.timeout,
                "recursion_limit": self.workflow.recursion_limit,
                "max_tool_rounds": self.workflow.max_tool_rounds,
            },
            "upload": {
                "upload_dir": self.upload.upload_dir,
                "max_size_mb": self.upload.max_size_mb,
            },
            "project": {
                "project_dir": str(self.project.project_dir),
                "skills_dir": str(self.project.skills_dir) if self.project.skills_dir else None,
                "mcp_config": str(self.project.mcp_config) if self.project.mcp_config else None,
                "models_config": str(self.project.models_config) if self.project.models_config else None,
            },
            "scheduler": {
                "enabled": self.scheduler.enabled,
                "timezone": self.scheduler.timezone,
            },
        }


# 便捷访问函数
def get_config() -> AgentClawConfig:
    """获取全局配置"""
    return AgentClawConfig.get()


def load_config(env_file: Optional[str] = None, reload: bool = False) -> AgentClawConfig:
    """加载配置"""
    return AgentClawConfig.load(env_file=env_file, reload=reload)
