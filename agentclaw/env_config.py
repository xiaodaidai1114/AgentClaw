"""Central registry for AgentClaw environment configuration.

This module is the single source used to render project ``.env`` files. Runtime
readers still live in their owning modules, but every user-facing environment
variable should be described here so new projects can discover what is
configurable and what each setting affects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class EnvVarSpec:
    """One environment variable shown in generated .env files."""

    name: str
    default: str = ""
    description: str = ""
    commented: bool = True
    show_in_env: bool = True
    extra_comments: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class EnvSection:
    """A logical group of environment variables."""

    title: str
    description: Sequence[str] = field(default_factory=tuple)
    variables: Sequence[EnvVarSpec] = field(default_factory=tuple)


ENV_SECTIONS: tuple[EnvSection, ...] = (
    EnvSection(
        title="模型配置说明",
        description=(
            "模型 API Key、Base URL 和模型名统一写在 models.json 中。",
            "如确实需要通过环境变量注入模型密钥，可在 models.json 中写成 \"api_key\": \"${YOUR_MODEL_API_KEY}\"。",
            "默认 .env 不提供 OPENAI_API_KEY / ANTHROPIC_API_KEY 占位，避免假 key 被误加载。",
        ),
    ),
    EnvSection(
        title="Server",
        description=(
            "HTTP 服务基础配置。CLI 显式参数优先级高于这里的值。",
        ),
        variables=(
            EnvVarSpec("PORT", "8000", "HTTP Server 端口；agentclaw serve/up 未传 --port 时读取。", commented=False),
            EnvVarSpec("HOST", "0.0.0.0", "HTTP Server 监听地址；agentclaw serve/up 未传 --host 时读取。", commented=False),
            EnvVarSpec("AGENTCLAW_URL", "http://127.0.0.1:8000", "AgentClaw 对自身 API 的可访问地址；远程部署、反向代理或工具回调地址不同时配置。"),
            EnvVarSpec("AGENTCLAW_MAX_REQUEST_BODY_BYTES", "4194304", "非上传 API 请求体最大字节数；超限会在进入业务处理前返回 413。"),
            EnvVarSpec("ADMIN_DASHBOARD_PORT", "5173", "开发模式下管理后台前端端口；当前发行包默认使用已构建静态资源。", show_in_env=False),
            EnvVarSpec("REBUILD_DASHBOARD", "false", "设为 true/1/yes 时启动时强制重新构建 Admin Dashboard。", show_in_env=False),
            EnvVarSpec("EXPORT_MCP_TOOLS", "false", "设为 true/1/yes 时启动时导出 MCP 工具元信息。", show_in_env=False),
            EnvVarSpec("SERVER_GRACEFUL_SHUTDOWN_TIMEOUT", "10", "收到 Ctrl+C 后 server 等待优雅退出的最长秒数。", show_in_env=False),
            EnvVarSpec("CHANNEL_SHUTDOWN_TIMEOUT", "5", "收到 Ctrl+C 后渠道适配器关闭超时秒数。", show_in_env=False),
            EnvVarSpec("SCHEDULER_SHUTDOWN_TIMEOUT", "5", "收到 Ctrl+C 后定时任务调度器关闭超时秒数。", show_in_env=False),
            EnvVarSpec("RESOURCE_SHUTDOWN_TIMEOUT", "5", "收到 Ctrl+C 后后台资源管理器关闭超时秒数。", show_in_env=False),
            EnvVarSpec("DATABASE_SHUTDOWN_TIMEOUT", "5", "收到 Ctrl+C 后数据库连接池关闭超时秒数。", show_in_env=False),
            EnvVarSpec("AgentClaw_SERVER_BASE_URL", "http://127.0.0.1:8000", "兼容旧变量；新配置请使用 AGENTCLAW_URL。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_PROJECT_DIR", "", "内部变量：显式指定 AgentClaw 项目目录；通常由 CLI 自动设置。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_ALLOW_GLOBAL_RELAY_CONFIG", "false", "兼容旧内部工具：设为 true/1/yes 时允许读取全局 /tmp relay 配置；多实例或公网部署不建议启用。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Auth",
        description=(
            "服务鉴权配置。agentclaw init/up 会自动生成并写入稳定值。",
        ),
        variables=(
            EnvVarSpec("ADMIN_TOKEN", "your-admin-token", "管理后台认证 Token。"),
            EnvVarSpec("WORKFLOW_API_KEY", "sk-your-workflow-key", "默认工作流执行 API 的 Bearer Key；不具备 Admin 权限，工作流可单独配置 workflow_api_key。"),
            EnvVarSpec("MCP_TOKEN", "your-mcp-token", "聚合 MCP SSE/HTTP 入口的鉴权令牌。"),
            EnvVarSpec("AGENTCLAW_TRUST_PROXY_HEADERS", "false", "仅在可信反向代理会清理 X-Forwarded-* 头时开启；用于 Public Agent 同源校验和限流客户端识别。"),
            EnvVarSpec("AGENTCLAW_CONTENT_SECURITY_POLICY", "", "覆盖默认 Content-Security-Policy；留空使用内置安全头策略。"),
            EnvVarSpec("AGENTCLAW_PUBLIC_SESSION_SECRET", "", "Public Agent 匿名会话签名密钥；留空时使用 Admin Token，多实例部署建议固定。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_ALLOW_QUERY_TOKENS", "false", "兼容旧客户端：设为 true/1/yes 时允许 MCP token 从 URL query 读取；公网部署不建议启用。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Data Directory",
        description=(
            "可选。用于将项目代码与运行时持久化数据分离。",
            "通过 agentclaw up 配置后，会同步派生日志、上传、知识库缓存和 Docker 基础设施挂载路径。",
            "留空时保持默认行为：本地文件写入项目目录，Docker 基础设施使用 named volumes。",
        ),
        variables=(
            EnvVarSpec("AGENTCLAW_DATA_DIR", "", "AgentClaw 运行时数据根目录；留空表示不启用统一数据目录。"),
            EnvVarSpec("AGENTCLAW_DOCKER_STORAGE_TYPE", "volume", "Docker 基础设施存储类型：volume 或 bind。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_DOCKER_PGDATA_DIR", "pgdata", "PostgreSQL Docker 数据卷或 bind mount 路径。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_DOCKER_REDISDATA_DIR", "redisdata", "Redis Docker 数据卷或 bind mount 路径。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_DOCKER_ETCDDATA_DIR", "etcddata", "etcd Docker 数据卷或 bind mount 路径。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_DOCKER_MINIODATA_DIR", "miniadata", "MinIO Docker 数据卷或 bind mount 路径。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_DOCKER_MILVUSDATA_DIR", "milvusdata", "Milvus Docker 数据卷或 bind mount 路径。", show_in_env=False),
            EnvVarSpec("MINIO_API_PORT", "9000", "MinIO API Docker 映射到宿主机的端口；端口冲突时可改为 19000 等。", show_in_env=False),
            EnvVarSpec("MINIO_CONSOLE_PORT", "9001", "MinIO Console Docker 映射到宿主机的端口；端口冲突时可改为 19001 等。", show_in_env=False),
            EnvVarSpec("MILVUS_PORT", "19530", "Milvus Docker 映射到宿主机的端口。", show_in_env=False),
            EnvVarSpec("MILVUS_HTTP_PORT", "9091", "Milvus HTTP/metrics 端口映射；端口冲突时可改为 9092 等。", show_in_env=False),
            EnvVarSpec("ADMINER_PORT", "8080", "Adminer Docker 映射到宿主机的端口；端口冲突时可改为 18080 等。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Logging",
        description=(
            "日志输出配置。文件日志会按日期落盘。",
        ),
        variables=(
            EnvVarSpec("AGENTCLAW_LOG_FILE", "logs/agentclaw.log", "主日志文件基础路径；实际会写入带日期后缀的文件。"),
            EnvVarSpec("LOG_FILE", "logs/agentclaw.log", "兼容旧变量；未设置 AGENTCLAW_LOG_FILE 时生效。", show_in_env=False),
            EnvVarSpec("LOG_CONSOLE_LEVEL", "WARNING", "控制台日志级别：DEBUG/INFO/WARNING/ERROR。"),
            EnvVarSpec("AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD", "false", "调试用：设为 true/1/yes 时才落盘失败的 LLM 请求载荷；默认关闭且会脱敏。"),
            EnvVarSpec("AGENTCLAW_LLM_FAILURE_DUMP_DIR", "/tmp", "LLM 失败请求载荷 dump 目录，仅在 AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD 开启时使用。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="PostgreSQL",
        description=(
            "可选。启用后提供执行追踪、日志、对话、Prompt 管理、定时任务和持久化 checkpointer。",
            "PG_HOST 留空或保持注释时，相关数据库能力不可用，系统以内存能力降级运行。",
        ),
        variables=(
            EnvVarSpec("PG_HOST", "127.0.0.1", "PostgreSQL 地址。"),
            EnvVarSpec("PG_PORT", "5432", "PostgreSQL 端口；Docker 模式下也是映射到宿主机的端口。"),
            EnvVarSpec("PG_DATABASE", "agentclaw", "PostgreSQL 数据库名。"),
            EnvVarSpec("PG_USER", "postgres", "PostgreSQL 用户名。"),
            EnvVarSpec("PG_PASSWORD", "password", "PostgreSQL 密码。"),
            EnvVarSpec("PG_CONNECT_TIMEOUT", "5", "PostgreSQL 启动连接超时秒数；超时后降级继续启动。", show_in_env=False),
            EnvVarSpec("PG_POOL_MIN_SIZE", "2", "PostgreSQL 连接池最小连接数。", show_in_env=False),
            EnvVarSpec("PG_POOL_MAX_SIZE", "10", "PostgreSQL 连接池最大连接数。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Redis",
        description=(
            "可选。启用后提供 Prompt 热更新、多实例同步、分布式锁和缓存能力。",
            "REDIS_HOST 留空或保持注释时，相关能力不可用或退回进程内实现。",
        ),
        variables=(
            EnvVarSpec("REDIS_HOST", "127.0.0.1", "Redis 地址。"),
            EnvVarSpec("REDIS_PORT", "6379", "Redis 端口；Docker 模式下也是映射到宿主机的端口，端口异常时可改为 6380 等。"),
            EnvVarSpec("REDIS_PASSWORD", "", "Redis 密码；无密码时留空。"),
            EnvVarSpec("REDIS_DB", "0", "Redis 数据库编号。"),
            EnvVarSpec("REDIS_CONNECT_TIMEOUT", "10", "Redis 启动连接超时秒数；超时后降级继续启动。", show_in_env=False),
            EnvVarSpec("REDIS_POOL_MAX_CONNECTIONS", "20", "Redis 连接池最大连接数。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Workflow Runtime",
        description=(
            "工作流执行、上下文和工具结果限制。",
        ),
        variables=(
            EnvVarSpec("WORKFLOW_TIMEOUT", "300", "单次工作流执行超时秒数。", commented=False),
            EnvVarSpec("WORKFLOW_RECURSION_LIMIT", "0", "LangGraph 递归/步数限制；0 表示不限制。", commented=False),
            EnvVarSpec("MAX_TOOL_ROUNDS", "0", "普通模式最大工具轮数；0 表示不限制。", commented=False),
            EnvVarSpec("MAX_CONTEXT_MESSAGES", "0", "普通模式最大上下文消息数；0 表示不限制。", commented=False),
            EnvVarSpec("TOOL_RESULT_MAX_LENGTH", "20000", "注入 LLM 的单条工具结果最大字符数。", commented=False),
            EnvVarSpec("MAX_MESSAGE_LENGTH", "0", "单条消息最大字符数；0 表示不限制。", commented=False),
            EnvVarSpec("HARNESS_POST_TOOL_TIMEOUT", "60", "Agentic Harness 工具后处理控制模型调用硬超时秒数。", commented=False),
            EnvVarSpec("TRACE_STALE_TIMEOUT_SECONDS", "300", "数据库追踪中运行中记录的过期判定秒数。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Prompt And Skills",
        description=(
            "Prompt 热更新与 skill 使用记录相关配置。",
        ),
        variables=(
            EnvVarSpec("PROMPT_RELOAD_INTERVAL", "60", "PromptManager 从数据库/缓存检查更新的间隔秒数。"),
            EnvVarSpec("SKILL_ATTESTATION_MAX_SESSIONS", "512", "skill 使用证明缓存保留的最大会话数。", show_in_env=False),
            EnvVarSpec("SKILL_ATTESTATION_TTL_SECONDS", "43200", "skill 使用证明缓存 TTL，默认 12 小时。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Upload And Storage",
        description=(
            "文件上传、本地存储与可选 MinIO 对象存储。",
        ),
        variables=(
            EnvVarSpec("UPLOAD_DIR", "./.storage", "本地上传文件存储目录。", commented=False),
            EnvVarSpec("MAX_UPLOAD_SIZE_MB", "20", "单文件最大上传大小，单位 MB。", commented=False),
            EnvVarSpec("FILE_STORAGE_DIR", "./.storage", "兼容旧变量；未设置 UPLOAD_DIR 时生效。", show_in_env=False),
            EnvVarSpec("MINIO_ENDPOINT", "", "MinIO endpoint；留空表示不启用 MinIO。"),
            EnvVarSpec("MINIO_ACCESS_KEY", "", "MinIO Access Key。"),
            EnvVarSpec("MINIO_SECRET_KEY", "", "MinIO Secret Key。"),
            EnvVarSpec("MINIO_BUCKET", "agentclaw", "MinIO bucket 名称。"),
            EnvVarSpec("MINIO_SECURE", "true", "MinIO 是否使用 HTTPS。"),
        ),
    ),
    EnvSection(
        title="Knowledge Base",
        description=(
            "知识库、检索与向量后端配置。模型相关配置仍来自 models.json。",
        ),
        variables=(
            EnvVarSpec("KNOWLEDGEBASE_ENABLED", "true", "是否启用知识库能力。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_STORAGE_DIR", "./.knowledgebase", "知识库本地元数据/文件目录。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_PARSER_CACHE_DIR", "./.knowledgebase/parsed", "文档解析缓存目录。", show_in_env=False),
            EnvVarSpec("KNOWLEDGEBASE_BACKEND", "milvus", "知识库后端类型。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_RETRIEVAL_MODE", "hybrid", "默认检索模式。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_PREFER_BUILTIN_HYBRID", "true", "优先使用内置 hybrid 检索。", show_in_env=False),
            EnvVarSpec("KNOWLEDGEBASE_DENSE_CANDIDATE_MULTIPLIER", "3", "向量候选数量倍率。", show_in_env=False),
            EnvVarSpec("KNOWLEDGEBASE_KEYWORD_CANDIDATE_MULTIPLIER", "3", "关键词候选数量倍率。", show_in_env=False),
            EnvVarSpec("KNOWLEDGEBASE_RERANK_CANDIDATE_MULTIPLIER", "3", "重排候选数量倍率。", show_in_env=False),
            EnvVarSpec("MILVUS_URI", "", "Milvus 连接 URI；Docker 模式默认写入 http://127.0.0.1:19530。留空时 Linux/macOS 自动使用本地 Milvus Lite；Windows 请使用 Docker/远程 Milvus 并配置此项。"),
            EnvVarSpec("MILVUS_TOKEN", "", "Milvus token。"),
            EnvVarSpec("MILVUS_COLLECTION_PREFIX", "agentclaw_kb", "Milvus collection 前缀。"),
            EnvVarSpec("MILVUS_METRIC_TYPE", "COSINE", "Milvus 向量距离度量。", show_in_env=False),
            EnvVarSpec("MILVUS_INDEX_TYPE", "AUTOINDEX", "Milvus 索引类型。", show_in_env=False),
            EnvVarSpec("KNOWLEDGEBASE_DEFAULT_TOP_K", "8", "默认检索 top_k。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_CHUNK_SIZE", "1200", "默认文档分块大小。", commented=False),
            EnvVarSpec("KNOWLEDGEBASE_CHUNK_OVERLAP", "200", "默认文档分块重叠。", commented=False),
            EnvVarSpec("DEFAULT_KNOWLEDGEBASE_ID", "", "默认知识库 ID；留空表示不指定。"),
            EnvVarSpec("KNOWLEDGEBASE_DEFAULT_EMBEDDING_MODEL", "", "默认 embedding 模型 ID，对应 models.json。"),
            EnvVarSpec("KNOWLEDGEBASE_DEFAULT_RERANK_MODEL", "", "默认 rerank 模型 ID，对应 models.json。"),
            EnvVarSpec("KNOWLEDGEBASE_DEFAULT_LLM_MODEL", "", "默认知识库 LLM 模型 ID，对应 models.json。"),
        ),
    ),
    EnvSection(
        title="Scheduler",
        description=(
            "定时任务调度器配置。",
        ),
        variables=(
            EnvVarSpec("SCHEDULER_ENABLED", "true", "是否启用定时调度。", commented=False),
            EnvVarSpec("SCHEDULER_TIMEZONE", "Asia/Shanghai", "调度器时区。", commented=False),
            EnvVarSpec("SCHEDULER_MAX_WORKERS", "10", "调度器线程池最大 worker 数。", commented=False),
            EnvVarSpec("SCHEDULER_COALESCE", "true", "错过多次执行时是否合并为一次。", commented=False),
            EnvVarSpec("SCHEDULER_MAX_INSTANCES", "1", "同一任务允许同时运行的最大实例数。", commented=False),
        ),
    ),
    EnvSection(
        title="MCP And Builtin Tools",
        description=(
            "MCP 连接、内置工具和工具执行边界配置。",
        ),
        variables=(
            EnvVarSpec("AGENTCLAW_MCP_CONNECT_TIMEOUT", "10.0", "连接单个 MCP Server 的超时秒数。", commented=False),
            EnvVarSpec("AGENTCLAW_MCP_TOOL_TIMEOUT", "30", "单次 MCP 工具调用硬超时秒数，避免远程或异常 MCP Server 长期无响应。", commented=False),
            EnvVarSpec("AGENTCLAW_MCP_PROXY", "", "远程 MCP 连接代理；localhost/127.0.0.1 会自动跳过。"),
            EnvVarSpec("SEARXNG_BASE_URL", "", "search-tools 使用的 SearXNG 地址；留空不启用 search-tools。"),
            EnvVarSpec("DOWNLOAD_BASE_URL", "/api/download", "download-tools 暴露下载文件时使用的 URL 前缀。"),
            EnvVarSpec("DOWNLOAD_MAX_FILE_SIZE_MB", "50", "download-tools 可发布文件的最大大小，单位 MB。"),
            EnvVarSpec("DOWNLOAD_MAX_TTL_SECONDS", "86400", "download-tools 签名下载链接最大 TTL 秒数。"),
            EnvVarSpec("DOWNLOAD_MAX_FILE_SIZE_BYTES", "", "download-tools 文件大小字节级覆盖值；设置后优先于 DOWNLOAD_MAX_FILE_SIZE_MB。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_FILE_LOCK_TIMEOUT", "30", "文件写入锁获取超时秒数。", show_in_env=False),
            EnvVarSpec("AGENTCLAW_FILE_LOCK_TTL", "120", "Redis 文件写入锁 TTL 秒数。", show_in_env=False),
            EnvVarSpec("SKILL_TOOLS_WRITE_FILE_MAX_BYTES", "200000", "skill-tools write_file 单次写入最大字节数。", show_in_env=False),
            EnvVarSpec("SKILL_TOOLS_DOCUMENT_READ_TIMEOUT", "30", "skill-tools read_file 文档转换超时秒数。", show_in_env=False),
            EnvVarSpec("SUDO_COMMAND_TIMEOUT", "60", "skill-tools sudo 命令超时秒数。", show_in_env=False),
            EnvVarSpec("CODING_TOOLS_DEFAULT_MAX_REPLACEMENTS", "40", "coding-tools 单文件默认最大替换次数。", show_in_env=False),
            EnvVarSpec("CODING_TOOLS_DEFAULT_MAX_TOTAL_REPLACEMENTS", "200", "coding-tools 批量替换默认总替换次数。", show_in_env=False),
        ),
    ),
    EnvSection(
        title="Browser Tools",
        description=(
            "内置 browser-tools / Playwright 浏览器连接配置。",
        ),
        variables=(
            EnvVarSpec("CDP_PORT", "9222", "Chromium DevTools Protocol 端口。"),
            EnvVarSpec("BROWSER_HEADLESS", "true", "是否以 headless 模式启动浏览器。"),
        ),
    ),
)


def _render_comment(text: str) -> list[str]:
    return [f"# {line}" if line else "#" for line in text.splitlines()]


def render_env_file(overrides: Mapping[str, str] | None = None, include_hidden: bool = False) -> str:
    """Render a complete project .env file from the central registry."""

    overrides = dict(overrides or {})
    lines: list[str] = [
        "# AgentClaw 环境配置",
        "# 由 agentclaw init / agentclaw up 生成；这里展示建议用户直接配置的运行项。",
        "# 取消某个配置项前面的 # 可启用或覆盖默认值。模型连接信息请配置 models.json。",
        "",
    ]

    for section in ENV_SECTIONS:
        visible_variables = [
            variable for variable in section.variables
            if include_hidden or variable.show_in_env or variable.name in overrides
        ]
        if not visible_variables and section.variables:
            continue
        if not visible_variables and not section.description:
            continue
        lines.append("# ============================================================")
        lines.append(f"# {section.title}")
        lines.append("# ============================================================")
        for paragraph in section.description:
            lines.extend(_render_comment(paragraph))
        if section.description and visible_variables:
            lines.append("#")
        for variable in visible_variables:
            if variable.description:
                lines.extend(_render_comment(variable.description))
            for comment in variable.extra_comments:
                lines.extend(_render_comment(comment))

            has_override = variable.name in overrides and overrides[variable.name] != ""
            value = str(overrides[variable.name]) if has_override else variable.default
            prefix = "" if has_override or not variable.commented else "# "
            lines.append(f"{prefix}{variable.name}={value}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def env_var_names() -> set[str]:
    """Return all environment variable names described by the registry."""

    return {
        variable.name
        for section in ENV_SECTIONS
        for variable in section.variables
    }


def visible_env_var_names() -> set[str]:
    """Return environment variable names shown in generated .env files."""

    return {
        variable.name
        for section in ENV_SECTIONS
        for variable in section.variables
        if variable.show_in_env
    }


def resolve_data_dir(data_dir: str | Path, project_dir: str | Path | None = None) -> Path:
    """Resolve a user-provided data directory.

    Relative paths are resolved against the project directory when available.
    """

    path = Path(data_dir).expanduser()
    if not path.is_absolute() and project_dir is not None:
        path = Path(project_dir).expanduser() / path
    return path.resolve()


def build_data_dir_env_vars(
    data_dir: str | Path,
    *,
    project_dir: str | Path | None = None,
    include_docker: bool = True,
) -> dict[str, str]:
    """Build the env vars derived from a unified AgentClaw data directory."""

    root = resolve_data_dir(data_dir, project_dir)
    env_vars = {
        "AGENTCLAW_DATA_DIR": str(root),
        "AGENTCLAW_LOG_FILE": str(root / "logs" / "agentclaw.log"),
        "UPLOAD_DIR": str(root / "storage"),
        "KNOWLEDGEBASE_STORAGE_DIR": str(root / "knowledgebase"),
        "KNOWLEDGEBASE_PARSER_CACHE_DIR": str(root / "knowledgebase" / "parsed"),
    }
    if include_docker:
        env_vars.update({
            "AGENTCLAW_DOCKER_STORAGE_TYPE": "bind",
            "AGENTCLAW_DOCKER_PGDATA_DIR": str(root / "docker" / "postgres"),
            "AGENTCLAW_DOCKER_REDISDATA_DIR": str(root / "docker" / "redis"),
            "AGENTCLAW_DOCKER_ETCDDATA_DIR": str(root / "docker" / "etcd"),
            "AGENTCLAW_DOCKER_MINIODATA_DIR": str(root / "docker" / "minio"),
            "AGENTCLAW_DOCKER_MILVUSDATA_DIR": str(root / "docker" / "milvus"),
        })
    return env_vars
