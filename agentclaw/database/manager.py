"""
Database - 数据库连接管理组件

支持：
- PostgreSQL（主存储）
- MySQL（可选）
- Redis（缓存和消息）
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, Optional
import asyncio
import os
from dataclasses import dataclass

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger
from agentclaw.platform_compat import (
    apply_windows_selector_event_loop_policy,
    get_service_host_fallback,
    is_windows_proactor_event_loop,
    normalize_service_host,
)

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)
apply_windows_selector_event_loop_policy()


def _host_resolution_hint(host: str) -> str:
    if get_service_host_fallback(host):
        return (
            f"主机名 {host} 看起来是 docker-compose 服务名；"
            "如果 AgentClaw 运行在宿主机上，请使用 127.0.0.1 或 localhost"
        )
    return f"请检查主机名 {host} 是否可解析，以及 .env 中的连接配置是否正确"


@dataclass
class PostgresConfig:
    """PostgreSQL 配置"""
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "agentclaw"
    
    @classmethod
    def from_env(cls, prefix: str = "PG_") -> "PostgresConfig":
        """从环境变量加载"""
        host = os.getenv(f"{prefix}HOST", "localhost")
        normalized_host = normalize_service_host(host)
        fallback = get_service_host_fallback(host)
        if fallback and normalized_host == fallback:
            logger.warning(f"检测到 {prefix}HOST={host}，当前为宿主机运行，自动回退到 {fallback}")
        return cls(
            host=normalized_host,
            port=int(os.getenv(f"{prefix}PORT", "5432")),
            user=os.getenv(f"{prefix}USER", "postgres"),
            password=os.getenv(f"{prefix}PASSWORD", ""),
            database=os.getenv(f"{prefix}DATABASE", "agentclaw"),
        )
    
    @property
    def dsn(self) -> str:
        """获取连接字符串"""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class MySQLConfig:
    """MySQL 配置"""
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "agentclaw"
    
    @classmethod
    def from_env(cls, prefix: str = "MYSQL_") -> "MySQLConfig":
        """从环境变量加载"""
        return cls(
            host=os.getenv(f"{prefix}HOST", "localhost"),
            port=int(os.getenv(f"{prefix}PORT", "3306")),
            user=os.getenv(f"{prefix}USER", "root"),
            password=os.getenv(f"{prefix}PASSWORD", ""),
            database=os.getenv(f"{prefix}DATABASE", "agentclaw"),
        )
    
    @property
    def dsn(self) -> str:
        """获取连接字符串"""
        return f"mysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class RedisConfig:
    """Redis 配置"""
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0
    
    @classmethod
    def from_env(cls, prefix: str = "REDIS_") -> "RedisConfig":
        """从环境变量加载"""
        host = os.getenv(f"{prefix}HOST", "localhost")
        normalized_host = normalize_service_host(host)
        fallback = get_service_host_fallback(host)
        if fallback and normalized_host == fallback:
            logger.warning(f"检测到 {prefix}HOST={host}，当前为宿主机运行，自动回退到 {fallback}")
        return cls(
            host=normalized_host,
            port=int(os.getenv(f"{prefix}PORT", "6379")),
            password=os.getenv(f"{prefix}PASSWORD", ""),
            db=int(os.getenv(f"{prefix}DB", "0")),
        )
    
    @property
    def url(self) -> str:
        """获取连接 URL"""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


def _get_pg_pool_size() -> tuple:
    """获取 PostgreSQL 连接池大小（从环境变量读取）"""
    min_size = int(os.getenv("PG_POOL_MIN_SIZE", "2"))
    max_size = int(os.getenv("PG_POOL_MAX_SIZE", "10"))
    return min_size, max_size


def _get_timeout_env(name: str, default: float) -> float:
    """获取连接超时秒数，非法值回退默认值。"""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning(f"{name}={raw_value!r} 不是有效超时秒数，使用默认值 {default}")
        return default


def _get_pg_connect_timeout() -> float:
    """获取 PostgreSQL 连接超时秒数。"""
    return _get_timeout_env("PG_CONNECT_TIMEOUT", 5.0)


def _get_redis_pool_size() -> int:
    """获取 Redis 连接池大小（从环境变量读取）"""
    return int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "20"))


def _get_redis_connect_timeout() -> float:
    """获取 Redis 连接超时秒数。"""
    return _get_timeout_env("REDIS_CONNECT_TIMEOUT", 10.0)


class DatabaseManager(BaseComponent):
    """
    数据库连接管理器
    
    统一管理 PostgreSQL、MySQL、Redis 连接
    
    Example:
        db = DatabaseManager(
            postgres=PostgresConfig.from_env(),
            redis=RedisConfig.from_env(),
        )
        
        workflow.use(db)
        
        # 在节点中使用
        async with db.pg_pool.acquire() as conn:
            result = await conn.fetch("SELECT * FROM users")
    """
    
    def __init__(
        self,
        postgres: Optional[PostgresConfig] = None,
        mysql: Optional[MySQLConfig] = None,
        redis: Optional[RedisConfig] = None,
    ):
        self.pg_config = postgres
        self.mysql_config = mysql
        self.redis_config = redis
        
        # 连接池
        self._pg_pool = None
        self._mysql_pool = None
        self._redis_pool = None  # Redis 连接池
        
        # 每个事件循环的 Redis 客户端缓存（避免跨循环问题）
        self._redis_clients: Dict[int, Any] = {}
        self._sync_redis_client = None
        
        # Checkpointer 专用连接池 (psycopg)
        self._checkpointer_pool = None
        
        self._initialized = False
    
    def on_init(self, workflow: Workflow) -> None:
        """组件初始化"""
        logger.info(f"DatabaseManager 绑定到工作流: {workflow.id}")
    
    async def get_checkpointer_pool(self) -> Any:
        """
        获取或初始化 Checkpointer 专用连接池 (psycopg)
        
        LangGraph Checkpointer 需要 psycopg 连接，而业务逻辑通常使用 asyncpg。
        """
        if self._checkpointer_pool:
            return self._checkpointer_pool
            
        if not self.pg_config:
            raise RuntimeError("PostgreSQL 未配置，无法创建 Checkpointer 连接池")
        if is_windows_proactor_event_loop():
            raise RuntimeError(
                "Windows ProactorEventLoop 与 psycopg async 不兼容，请使用 SelectorEventLoop 或降级为内存 Checkpointer"
            )
            
        try:
            from psycopg_pool import AsyncConnectionPool
            from psycopg.rows import dict_row
            
            # 构建 DSN (复用 PostgresConfig)
            dsn = self.pg_config.dsn
            sep = "&" if "?" in dsn else "?"
            dsn += f"{sep}keepalives=1&keepalives_idle=30&keepalives_interval=10&connect_timeout=10"
            
            self._checkpointer_pool = AsyncConnectionPool(
                conninfo=dsn,
                min_size=2,
                max_size=10,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await self._checkpointer_pool.open()
            logger.info("Checkpointer 专用连接池 (psycopg) 已建立")
            return self._checkpointer_pool
            
        except ImportError:
            logger.error("需要安装 psycopg-pool 以支持 Checkpointer: pip install psycopg-pool psycopg[binary]")
            raise
        except Exception as e:
            logger.error(f"初始化 Checkpointer 连接池失败: {e}")
            raise

    async def connect(self) -> None:
        """建立所有数据库连接"""
        if self._initialized:
            return
        
        # PostgreSQL
        if self.pg_config:
            await self._connect_postgres()
        
        # MySQL
        if self.mysql_config:
            await self._connect_mysql()
        
        # Redis
        if self.redis_config:
            await self._connect_redis()
        
        self._initialized = True
        logger.info("数据库连接已建立")
    
    async def _ensure_database_exists(self) -> None:
        """如果目标数据库不存在则自动创建"""
        import asyncpg

        try:
            # 连接默认的 postgres 库检查目标数据库是否存在
            timeout = _get_pg_connect_timeout()
            sys_conn = await asyncpg.connect(
                host=self.pg_config.host,
                port=self.pg_config.port,
                user=self.pg_config.user,
                password=self.pg_config.password,
                database="postgres",
                timeout=timeout,
            )
            try:
                exists = await sys_conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1",
                    self.pg_config.database,
                )
                if not exists:
                    # CREATE DATABASE 不能在事务内执行
                    await sys_conn.execute(
                        f'CREATE DATABASE "{self.pg_config.database}" OWNER "{self.pg_config.user}"'
                    )
                    logger.info(f"自动创建数据库: {self.pg_config.database}")
            finally:
                await sys_conn.close()
        except asyncio.TimeoutError:
            # 创建失败不阻塞启动，后续连接会报具体错误
            logger.warning(f"检查/创建数据库超时（>{_get_pg_connect_timeout():.1f}s）")
        except Exception as e:
            # 创建失败不阻塞启动，后续连接会报具体错误
            logger.warning(f"检查/创建数据库失败: {e}")

    async def _connect_postgres(self) -> None:
        """连接 PostgreSQL"""
        try:
            import asyncpg

            # 自动创建数据库（如不存在）
            await self._ensure_database_exists()

            min_size, max_size = _get_pg_pool_size()
            timeout = _get_pg_connect_timeout()
            self._pg_pool = await asyncpg.create_pool(
                host=self.pg_config.host,
                port=self.pg_config.port,
                user=self.pg_config.user,
                password=self.pg_config.password,
                database=self.pg_config.database,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
            )
            logger.info(f"PostgreSQL 连接池已建立: {self.pg_config.host}:{self.pg_config.port} (min={min_size}, max={max_size})")

            # 自动创建表
            await self._init_schema()

            # 自动启用 Tracer
            self._setup_tracer()
        except ImportError as e:
            logger.error(f"asyncpg 未安装，请执行: pip install asyncpg  ({e})")
        except asyncio.TimeoutError:
            logger.error(f"PostgreSQL 连接超时（>{_get_pg_connect_timeout():.1f}s）")
        except Exception as e:
            hint = ""
            if "getaddrinfo failed" in str(e).lower():
                hint = f"；{_host_resolution_hint(self.pg_config.host)}"
            logger.error(f"PostgreSQL 连接失败: {e}{hint}")
    
    async def _connect_mysql(self) -> None:
        """连接 MySQL"""
        try:
            import aiomysql
            
            self._mysql_pool = await aiomysql.create_pool(
                host=self.mysql_config.host,
                port=self.mysql_config.port,
                user=self.mysql_config.user,
                password=self.mysql_config.password,
                db=self.mysql_config.database,
                minsize=2,
                maxsize=10,
            )
            logger.info(f"MySQL 连接成功: {self.mysql_config.host}:{self.mysql_config.port}")
        except ImportError:
            logger.warning("aiomysql 未安装，MySQL 异步连接不可用")
        except Exception as e:
            logger.error(f"MySQL 连接失败: {e}")
    
    async def _connect_redis(self) -> None:
        """连接 Redis（使用连接池）"""
        test_client = None
        timeout = _get_redis_connect_timeout()
        try:
            import redis.asyncio as aioredis

            max_connections = _get_redis_pool_size()
            logger.info(
                f"正在连接 Redis: {self.redis_config.host}:{self.redis_config.port} "
                f"(timeout={timeout:.1f}s)"
            )

            # 创建连接池
            self._redis_pool = aioredis.ConnectionPool(
                host=self.redis_config.host,
                port=self.redis_config.port,
                password=self.redis_config.password or None,
                db=self.redis_config.db,
                decode_responses=True,
                max_connections=max_connections,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
            )

            # 创建测试客户端验证连接
            test_client = aioredis.Redis(connection_pool=self._redis_pool)
            await asyncio.wait_for(test_client.ping(), timeout=timeout)

            logger.info(f"Redis 连接池已建立: {self.redis_config.host}:{self.redis_config.port} (max_connections={max_connections})")
        except ImportError:
            logger.warning("redis 库未安装")
        except asyncio.TimeoutError:
            if self._redis_pool:
                try:
                    await self._redis_pool.disconnect()
                except Exception:
                    pass
            self._redis_pool = None
            logger.warning(f"Redis 连接超时（>{timeout:.1f}s），Redis 相关能力将降级")
        except Exception as e:
            if self._redis_pool:
                try:
                    await self._redis_pool.disconnect()
                except Exception:
                    pass
            self._redis_pool = None
            hint = ""
            if "getaddrinfo failed" in str(e).lower():
                hint = f"；{_host_resolution_hint(self.redis_config.host)}"
            logger.warning(f"Redis 连接失败: {e}{hint}，Redis 相关能力将降级")
        finally:
            if test_client:
                try:
                    await test_client.close()
                except Exception:
                    pass
    
    async def get_redis_client(self) -> Optional[Any]:
        """
        获取 Redis 客户端（从连接池）
        
        为每个事件循环创建独立的客户端，避免跨循环问题。
        客户端会自动从连接池获取和释放连接。
        
        Returns:
            Redis 客户端，如果未配置或连接失败返回 None
        """
        if not self._redis_pool:
            return None
        
        try:
            import asyncio
            import redis.asyncio as aioredis
            
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
            
            # 检查是否已有该循环的客户端
            if loop_id not in self._redis_clients:
                # 为当前循环创建新客户端（使用共享连接池）
                self._redis_clients[loop_id] = aioredis.Redis(connection_pool=self._redis_pool)
                logger.debug(f"为事件循环 {loop_id} 创建 Redis 客户端")
            
            return self._redis_clients[loop_id]
        except RuntimeError:
            # 没有运行中的事件循环
            return None
        except Exception as e:
            logger.error(f"获取 Redis 客户端失败: {e}")
            return None

    def get_sync_redis_client(self) -> Optional[Any]:
        """获取同步 Redis 客户端（用于同步路由辅助逻辑）。"""
        if not self.redis_config:
            return None
        try:
            if self._sync_redis_client is None:
                self._sync_redis_client = self.create_sync_redis_client(self.redis_config)
            return self._sync_redis_client
        except Exception as e:
            logger.warning(f"获取同步 Redis 客户端失败: {e}")
            return None
    
    def is_redis_available(self) -> bool:
        """检查 Redis 是否可用"""
        return self._redis_pool is not None
    
    async def _init_schema(self) -> None:
        """自动创建框架所需的表（如果不存在）"""
        if not self._pg_pool:
            return
        
        schema_sql = """
        -- Prompt 热更新表（保留历史版本）
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
        
        CREATE TABLE IF NOT EXISTS prompts (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            workflow_id VARCHAR(100) NOT NULL,
            prompt_key VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            default_content TEXT,
            is_custom BOOLEAN DEFAULT FALSE,
            version INT DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_by VARCHAR(100)
        );
        
        -- 用户长期记忆表
        CREATE TABLE IF NOT EXISTS user_memories (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(100) NOT NULL,
            key VARCHAR(200) NOT NULL,
            value JSONB,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, key)
        );
        
        -- 工作流执行日志表
        CREATE TABLE IF NOT EXISTS workflow_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            workflow_id VARCHAR(100),
            thread_id VARCHAR(100),
            user_id VARCHAR(100),
            name VARCHAR(200),
            run_type VARCHAR(20) DEFAULT 'blocking',  -- blocking / stream
            input_data JSONB,
            output_data JSONB,
            node_log_ids JSONB DEFAULT '[]'::jsonb,  -- 节点日志ID列表（按执行顺序）
            metadata JSONB,
            status VARCHAR(20) DEFAULT 'running',
            error TEXT,
            duration_ms FLOAT DEFAULT 0,  -- 工作流总耗时（毫秒）
            start_time TIMESTAMP DEFAULT NOW(),
            end_time TIMESTAMP
        );
        
        -- 节点执行日志表
        CREATE TABLE IF NOT EXISTS node_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            workflow_log_id UUID,
            parent_node_log_id UUID,
            name VARCHAR(200),
            node_type VARCHAR(50),
            input_data JSONB,
            output_data JSONB,
            metadata JSONB,
            status VARCHAR(20) DEFAULT 'running',
            error TEXT,
            duration_ms FLOAT DEFAULT 0,
            start_time TIMESTAMP DEFAULT NOW(),
            end_time TIMESTAMP
        );
        
        -- LLM 调用日志表
        CREATE TABLE IF NOT EXISTS llm_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            workflow_log_id UUID,
            node_log_id UUID,
            model_id VARCHAR(50),
            model_name VARCHAR(100),
            prompt TEXT,
            completion TEXT,
            prompt_tokens INT DEFAULT 0,
            completion_tokens INT DEFAULT 0,
            total_tokens INT DEFAULT 0,
            latency_ms FLOAT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'success',
            error TEXT,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        -- 创建索引
        CREATE INDEX IF NOT EXISTS idx_prompts_workflow_key ON prompts(workflow_id, prompt_key);
        CREATE INDEX IF NOT EXISTS idx_prompts_created ON prompts(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories(user_id);
        CREATE INDEX IF NOT EXISTS idx_workflow_logs_workflow ON workflow_logs(workflow_id);
        CREATE INDEX IF NOT EXISTS idx_workflow_logs_thread ON workflow_logs(thread_id);
        CREATE INDEX IF NOT EXISTS idx_node_logs_workflow_log ON node_logs(workflow_log_id);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_workflow_log ON llm_logs(workflow_log_id);
        
        -- Admin Dashboard 所需的额外索引
        CREATE INDEX IF NOT EXISTS idx_workflow_logs_time_range ON workflow_logs(workflow_id, start_time DESC);
        CREATE INDEX IF NOT EXISTS idx_workflow_logs_status ON workflow_logs(workflow_id, status);
        CREATE INDEX IF NOT EXISTS idx_node_logs_name ON node_logs(workflow_log_id, name);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_model ON llm_logs(model_id);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_time ON llm_logs(created_at DESC);
        
        -- 提示词历史表（用于版本追踪）
        CREATE TABLE IF NOT EXISTS prompt_history (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            prompt_id UUID NOT NULL,
            workflow_id VARCHAR(100) NOT NULL,
            prompt_key VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            version INT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_by VARCHAR(100)
        );
        CREATE INDEX IF NOT EXISTS idx_prompt_history_key ON prompt_history(workflow_id, prompt_key, version DESC);
        
        -- 文件存储表（图片/文档上传）
        CREATE TABLE IF NOT EXISTS files (
            id VARCHAR(64) PRIMARY KEY,
            original_name VARCHAR(500) NOT NULL,
            file_path VARCHAR(1000) NOT NULL,
            file_hash VARCHAR(64) NOT NULL,
            mime_type VARCHAR(100) NOT NULL,
            size BIGINT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash);
        CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at DESC);
        """
        
        try:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(schema_sql)
                # Migrations for existing databases
                await conn.execute("""
                    ALTER TABLE workflow_logs
                    ADD COLUMN IF NOT EXISTS output_data JSONB
                """)
            logger.info("数据库表结构已初始化")
        except Exception as e:
            logger.error(f"初始化表结构失败: {e}")
    
    def _setup_tracer(self) -> None:
        """自动启用数据库追踪"""
        try:
            from agentclaw.runtime.tracing import setup_db_tracing
            setup_db_tracing(self)
            logger.info("数据库追踪已自动启用")
        except Exception as e:
            logger.warning(f"启用数据库追踪失败: {e}")
    
    async def close(self) -> None:
        """关闭所有连接"""
        if self._pg_pool:
            if hasattr(self._pg_pool, 'close'):
                await self._pg_pool.close()
            logger.info("PostgreSQL 连接已关闭")
        
        if self._mysql_pool:
            self._mysql_pool.close()
            await self._mysql_pool.wait_closed()
            logger.info("MySQL 连接已关闭")
        
        # 关闭所有 Redis 客户端
        for loop_id, client in self._redis_clients.items():
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"关闭 Redis 客户端 {loop_id} 失败: {e}")
        self._redis_clients.clear()
        if self._sync_redis_client:
            try:
                self._sync_redis_client.close()
            except Exception as e:
                logger.warning(f"关闭同步 Redis 客户端失败: {e}")
            self._sync_redis_client = None
        
        # 关闭 Redis 连接池
        if self._redis_pool:
            await self._redis_pool.disconnect()
            logger.info("Redis 连接池已关闭")
        
        self._initialized = False
    
    @property
    def pg_pool(self):
        """获取 PostgreSQL 连接池"""
        return self._pg_pool
    
    @property
    def mysql_pool(self):
        """获取 MySQL 连接池"""
        return self._mysql_pool
    
    @property
    def redis(self):
        """获取 Redis 连接池（兼容旧代码）"""
        return self._redis_pool
    
    @property
    def redis_pool(self):
        """获取 Redis 连接池"""
        return self._redis_pool
    
    # 便捷方法
    async def pg_execute(self, sql: str, *args) -> None:
        """执行 PostgreSQL SQL"""
        if not self._pg_pool:
            raise RuntimeError("PostgreSQL 未连接")
        
        async with self._pg_pool.acquire() as conn:
            await conn.execute(sql, *args)
    
    async def pg_fetch(self, sql: str, *args) -> list:
        """查询 PostgreSQL"""
        if not self._pg_pool:
            raise RuntimeError("PostgreSQL 未连接")
        
        async with self._pg_pool.acquire() as conn:
            return await conn.fetch(sql, *args)
    
    async def pg_fetchrow(self, sql: str, *args) -> Optional[dict]:
        """查询单行"""
        if not self._pg_pool:
            raise RuntimeError("PostgreSQL 未连接")
        
        async with self._pg_pool.acquire() as conn:
            return await conn.fetchrow(sql, *args)
    
    async def redis_get(self, key: str) -> Optional[str]:
        """Redis GET"""
        client = await self.get_redis_client()
        if not client:
            return None
        return await client.get(key)
    
    async def redis_set(self, key: str, value: str, ex: int = None) -> None:
        """Redis SET"""
        client = await self.get_redis_client()
        if not client:
            return
        await client.set(key, value, ex=ex)
    
    async def redis_publish(self, channel: str, message: str) -> None:
        """Redis PUBLISH"""
        client = await self.get_redis_client()
        if not client:
            return
        await client.publish(channel, message)

    @staticmethod
    def create_sync_redis_client(config: RedisConfig):
        """
        创建同步 Redis 客户端（用于子进程或同步上下文）

        Args:
            config: Redis 配置

        Returns:
            redis.Redis 客户端实例

        Example:
            config = RedisConfig.from_env()
            client = DatabaseManager.create_sync_redis_client(config)
            client.publish("channel", "message")
        """
        import redis
        return redis.Redis(
            host=config.host,
            port=config.port,
            password=config.password or None,
            db=config.db,
            decode_responses=True,
        )


# 全局数据库管理器（可选）
_global_db: Optional[DatabaseManager] = None


def get_database() -> Optional[DatabaseManager]:
    """获取全局数据库管理器"""
    return _global_db


async def init_database(
    postgres: Optional[PostgresConfig] = None,
    mysql: Optional[MySQLConfig] = None,
    redis: Optional[RedisConfig] = None,
) -> DatabaseManager:
    """
    初始化全局数据库管理器
    
    Example:
        from dotenv import load_dotenv
        load_dotenv()
        
        db = await init_database(
            postgres=PostgresConfig.from_env(),
            redis=RedisConfig.from_env(),
        )
    """
    global _global_db
    
    _global_db = DatabaseManager(
        postgres=postgres,
        mysql=mysql,
        redis=redis,
    )
    await _global_db.connect()
    
    return _global_db


async def close_database() -> None:
    """
    关闭全局数据库连接
    
    Example:
        await close_database()
    """
    global _global_db
    
    if _global_db:
        await _global_db.close()
        _global_db = None
        logger.info("全局数据库连接已关闭")
