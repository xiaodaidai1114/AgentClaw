"""
PromptManager - 提示词管理组件

支持：
- 数据库/文件多来源加载
- 热更新（Redis 缓存 + 定时同步）
- 模板变量替换
- 默认值兜底
- 版本历史与回滚
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, Optional, Literal
import asyncio
import os
import re
import json
import threading
from string import Template
from datetime import datetime

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


def _get_prompt_reload_interval() -> int:
    """获取提示词热更新间隔（从环境变量读取，单位：秒）"""
    return int(os.getenv("PROMPT_RELOAD_INTERVAL", "60"))


class PromptManager(BaseComponent):
    """
    提示词管理器
    
    支持从数据库或文件加载提示词，支持热更新和模板变量替换
    
    热更新架构：
    - Redis 必须：没有 Redis 则热更新功能禁用
    - 启动时从数据库加载到 Redis
    - 运行时从 Redis 读取（不查数据库）
    - 守护线程定时从数据库同步到 Redis（间隔由 PROMPT_RELOAD_INTERVAL 环境变量控制）
    - API 更新时立即刷新 Redis
    
    Example:
        prompt_manager = PromptManager(
            source="database",
            hot_reload=True,
        )
        
        workflow.use(prompt_manager)
    """
    
    def __init__(
        self,
        source: Literal["database", "file", "memory"] = "memory",
        hot_reload: bool = True,
        reload_interval: Optional[int] = None,  # None 表示使用环境变量
        default_prompts: Optional[Dict[str, str]] = None,
        # 数据库配置
        db_connection: Optional[Any] = None,
        # 文件配置
        prompts_dir: Optional[str] = None,
        # Redis 配置（已废弃，使用 DatabaseManager）
        redis_client: Optional[Any] = None,
    ):
        self.source = source
        self.hot_reload = hot_reload
        # 优先使用传入的值，否则从环境变量读取
        self.reload_interval = reload_interval if reload_interval is not None else _get_prompt_reload_interval()
        self.default_prompts = default_prompts or {}
        
        self.db_connection = db_connection
        self.prompts_dir = prompts_dir
        
        # 内部状态
        self._prompts: Dict[str, PromptEntry] = {}
        self._workflow_id: Optional[str] = None
        self._last_reload: Optional[datetime] = None
        self._reload_task: Optional[asyncio.Task] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_sync = threading.Event()
        
        # 热更新状态
        self._hot_reload_enabled = False  # 实际是否启用热更新
        
        # 延迟加载状态
        self._db_loaded = False  # 是否已从数据库加载
        self._needs_async_load = False  # 是否需要异步加载（事件循环运行时设置）
        
        # DatabaseManager 引用（用于获取 Redis 连接）
        self._db_manager = None

    def on_init(self, workflow: Workflow) -> None:
        """组件初始化"""
        self._workflow_id = workflow.id
        self._workflow = workflow
        
        # 如果使用数据库但没有传入连接，尝试从 workflow 的 DatabaseManager 获取
        if self.source == "database" and not self.db_connection:
            self._init_db_from_workflow(workflow)
        
        # 初始化 Redis 连接（从 DatabaseManager 获取）
        self._init_redis_from_workflow(workflow)
        
        # 检查热更新条件（初始化时可能不可用，延迟加载时会重新检查）
        self._hot_reload_enabled = self.hot_reload and self._db_manager is not None and self._db_manager.is_redis_available()
        
        # 加载提示词（database 模式下会跳过，等待延迟加载）
        self._load_prompts()
        
        # 如果启用热更新，同步到 Redis 并启动守护线程
        if self._hot_reload_enabled:
            self._sync_prompts_to_redis()
            self._start_sync_thread()
        
        # 标记是否已从数据库加载（用于延迟加载）
        self._db_loaded = self.source != "database"  # 如果不是 database 模式，标记为已加载
        
        # 日志输出
        if self.source == "database" and not self._db_loaded:
            logger.info(
                f"PromptManager 初始化完成: workflow={workflow.id}, "
                f"prompts={len(self._prompts)}, source={self.source}, "
                f"延迟加载=True (等待数据库连接)"
            )
        else:
            logger.info(
                f"PromptManager 初始化完成: workflow={workflow.id}, "
                f"prompts={len(self._prompts)}, hot_reload={self._hot_reload_enabled}, "
                f"source={self.source}"
            )
            
            # 打印所有加载的提示词（仅非延迟加载模式）
            for key, entry in self._prompts.items():
                logger.debug(
                    f"  提示词: {key}, source={entry.source}, "
                    f"content_length={len(entry.content)}, version={entry.version}"
                )
    
    def _init_db_from_workflow(self, workflow: Workflow) -> None:
        """从 workflow 的 DatabaseManager 获取数据库连接"""
        from agentclaw.database.manager import DatabaseManager
        
        for component in workflow._components:
            if isinstance(component, DatabaseManager):
                if component._pg_pool:
                    self.db_connection = component._pg_pool
                    logger.info("PromptManager 从 DatabaseManager 获取数据库连接")
                    return
        
        # 如果没有找到 DatabaseManager，尝试从全局获取
        from agentclaw.database.manager import get_database
        global_db = get_database()
        if global_db and global_db.pg_pool:
            self.db_connection = global_db.pg_pool
            logger.info("PromptManager 从全局 DatabaseManager 获取数据库连接")
            return
        
        # 如果还是没有，尝试从环境变量创建（但这需要异步初始化）
        self._init_db_connection_from_env()
    
    def _init_redis_from_workflow(self, workflow: Workflow) -> None:
        """从 workflow 的 DatabaseManager 获取 Redis 连接"""
        from agentclaw.database.manager import DatabaseManager
        
        for component in workflow._components:
            if isinstance(component, DatabaseManager):
                self._db_manager = component
                if component.is_redis_available():
                    logger.debug("PromptManager 从 DatabaseManager 获取 Redis 连接")
                return
        
        # 如果没有找到 DatabaseManager，尝试从全局获取或创建
        from agentclaw.database.manager import get_database
        global_db = get_database()
        if global_db:
            if global_db.is_redis_available():
                self._db_manager = global_db
                logger.debug("PromptManager 从全局 DatabaseManager 获取 Redis 连接")
                return
        
        # 尝试从环境变量初始化
        self._init_db_manager_from_env()
    
    def _init_db_connection_from_env(self) -> None:
        """从环境变量初始化数据库连接"""
        import os
        pg_host = os.getenv("PG_HOST")
        if not pg_host:
            return
        
        # 保存配置，延迟创建连接
        self._pg_config = {
            "host": pg_host,
            "port": int(os.getenv("PG_PORT", "5432")),
            "user": os.getenv("PG_USER", "postgres"),
            "password": os.getenv("PG_PASSWORD", ""),
            "database": os.getenv("PG_DATABASE", "agentclaw"),
        }
        logger.debug(f"PromptManager 已配置数据库连接: {pg_host}")
    
    def _init_db_manager_from_env(self) -> None:
        """从环境变量初始化 DatabaseManager（用于 Redis）"""
        import os
        redis_host = os.getenv("REDIS_HOST")
        if not redis_host:
            return
        
        # 保存 Redis 配置
        from agentclaw.database.manager import RedisConfig, DatabaseManager
        self._redis_config = RedisConfig(
            host=redis_host,
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or "",
            db=int(os.getenv("REDIS_DB", "0")),
        )
        
        # 创建 DatabaseManager（连接在 _ensure_redis_connected 中延迟建立）
        self._db_manager = DatabaseManager(redis=self._redis_config)
        logger.debug(f"PromptManager 已配置 Redis: {redis_host}:{self._redis_config.port}")
    
    async def _ensure_redis_connected(self) -> bool:
        """确保 Redis 已连接，返回是否成功"""
        if not self._db_manager:
            return False
        
        if self._db_manager.is_redis_available():
            return True
        
        try:
            await self._db_manager.connect()
            return self._db_manager.is_redis_available()
        except Exception as e:
            logger.warning(f"Redis 连接失败: {e}")
            return False
    
    async def _get_redis_client(self):
        """
        获取 Redis 客户端（从 DatabaseManager 连接池）
        
        Returns:
            Redis 客户端，如果未配置或连接失败返回 None
        """
        # 优先从 DatabaseManager 获取
        if self._db_manager:
            # 确保已连接
            if not self._db_manager.is_redis_available():
                await self._ensure_redis_connected()
            return await self._db_manager.get_redis_client()
        
        # 如果有延迟初始化的配置，创建 DatabaseManager
        if hasattr(self, '_redis_config') and self._redis_config:
            try:
                from agentclaw.database.manager import DatabaseManager
                self._db_manager = DatabaseManager(redis=self._redis_config)
                await self._db_manager.connect()
                return await self._db_manager.get_redis_client()
            except Exception as e:
                logger.error(f"延迟初始化 Redis 连接失败: {e}")
                return None
        
        return None
    
    def _get_redis_key(self, prompt_key: str) -> str:
        """获取 Redis 缓存 key"""
        return f"ac:prompt:{self._workflow_id}:{prompt_key}"
    
    def _get_redis_index_key(self) -> str:
        """获取 Redis 索引 key（存储所有 prompt_key 列表）"""
        return f"ac:prompt:{self._workflow_id}:__index__"

    # ========================================================================
    # 加载提示词
    # ========================================================================
    
    def _load_prompts(self) -> None:
        """加载提示词"""
        if self.source == "database":
            self._load_from_database()
        elif self.source == "file":
            self._load_from_file()
        
        # 加载默认提示词（作为兜底）
        for key, content in self.default_prompts.items():
            if key not in self._prompts:
                self._prompts[key] = PromptEntry(
                    key=key,
                    content=content,
                    source="default",
                )
        
        self._last_reload = datetime.now()
    
    def _load_from_database(self) -> None:
        """从数据库加载提示词（同步版本，用于初始化）"""
        # 优先从 DatabaseManager 获取连接
        if not self.db_connection and self._db_manager and self._db_manager.pg_pool:
            self.db_connection = self._db_manager.pg_pool
            logger.debug("PromptManager 从 DatabaseManager 获取数据库连接池")
        
        # 如果还是没有，尝试从全局获取
        if not self.db_connection:
            from agentclaw.database.manager import get_database
            global_db = get_database()
            if global_db and global_db.pg_pool:
                self.db_connection = global_db.pg_pool
                logger.debug("从全局 DatabaseManager 获取数据库连接成功")
        
        if not self.db_connection:
            # 数据库模式但连接不可用，等待延迟加载
            logger.debug("数据库连接未配置，跳过初始加载（等待延迟加载）")
            return
        
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # 事件循环正在运行：跳过同步加载，标记为延迟加载
                # 避免死锁问题（run_coroutine_threadsafe 在同一事件循环中会死锁）
                logger.debug("事件循环运行中，跳过同步加载（将在首次使用时异步加载）")
                self._needs_async_load = True
                return
            except RuntimeError:
                # 没有运行中的事件循环，可以安全地创建新循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._async_load_from_database())
                finally:
                    loop.close()
        except Exception as e:
            logger.warning(f"从数据库加载提示词失败，将在首次使用时重试: {e}")
            self._needs_async_load = True
    
    async def _async_load_from_database(self) -> None:
        """从数据库异步加载提示词"""
        # 优先从 DatabaseManager 获取连接
        if not self.db_connection and self._db_manager and self._db_manager.pg_pool:
            self.db_connection = self._db_manager.pg_pool
            logger.debug("PromptManager 从 DatabaseManager 获取数据库连接池")
        
        # 如果还是没有，尝试从全局获取
        if not self.db_connection:
            from agentclaw.database.manager import get_database
            global_db = get_database()
            if global_db and global_db.pg_pool:
                self.db_connection = global_db.pg_pool
                logger.debug("PromptManager 从全局 DatabaseManager 获取数据库连接池")
        
        if not self.db_connection:
            logger.warning("数据库连接不可用，跳过数据库加载")
            return
        
        logger.debug(f"开始从数据库加载提示词: workflow_id={self._workflow_id}")
        
        try:
            rows = await self.db_connection.fetch(
                """SELECT DISTINCT ON (prompt_key) 
                       prompt_key, content, default_content, is_custom, version, created_at, updated_by
                   FROM prompts 
                   WHERE workflow_id = $1
                   ORDER BY prompt_key, created_at DESC""",
                self._workflow_id
            )
            
            logger.debug(f"数据库查询返回 {len(rows)} 条记录")
            
            for row in rows:
                prompt_key = row["prompt_key"]
                content = row["content"]
                logger.debug(f"从数据库加载提示词: key={prompt_key}, content_length={len(content)}, version={row['version']}, is_custom={row['is_custom']}")
                
                self._prompts[prompt_key] = PromptEntry(
                    key=prompt_key,
                    content=content,
                    default_content=row["default_content"],
                    source="database",
                    updated_at=row["created_at"],
                    updated_by=row["updated_by"],
                    version=row["version"] or 1,
                )
            
            if len(rows) > 0:
                logger.info(f"从数据库加载完成，共 {len(rows)} 个提示词")
        except Exception as e:
            logger.error(f"从数据库加载提示词失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _load_from_file(self) -> None:
        """从文件加载提示词"""
        if not self.prompts_dir:
            logger.warning("提示词目录未配置，跳过文件加载")
            return
        
        import os
        
        try:
            import yaml
        except ImportError:
            logger.error("需要安装 pyyaml: pip install pyyaml")
            return
        
        try:
            path = self.prompts_dir
            
            if os.path.isfile(path):
                self._load_yaml_file(path)
            elif os.path.isdir(path):
                for filename in os.listdir(path):
                    if filename.endswith(('.yaml', '.yml')):
                        filepath = os.path.join(path, filename)
                        self._load_yaml_file(filepath)
            else:
                logger.warning(f"提示词路径不存在: {path}")
                
        except Exception as e:
            logger.error(f"从文件加载提示词失败: {e}")
    
    def _load_yaml_file(self, filepath: str) -> None:
        """加载单个 YAML 文件"""
        import yaml
        import os
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if not data or not isinstance(data, dict):
                return
            
            filename = os.path.basename(filepath)
            loaded = 0
            
            for key, value in data.items():
                if isinstance(value, str):
                    self._prompts[key] = PromptEntry(
                        key=key,
                        content=value,
                        source=f"file:{filename}",
                    )
                    loaded += 1
                elif isinstance(value, dict):
                    content = value.get("content", "")
                    if not content:
                        continue
                    self._prompts[key] = PromptEntry(
                        key=key,
                        content=content,
                        variables=value.get("variables"),
                        source=f"file:{filename}",
                    )
                    loaded += 1
            
            if loaded > 0:
                logger.debug(f"从 {filename} 加载了 {loaded} 个提示词")
                
        except Exception as e:
            logger.error(f"加载 YAML 文件失败 {filepath}: {e}")

    # ========================================================================
    # Redis 缓存操作
    # ========================================================================
    
    def _sync_prompts_to_redis(self) -> None:
        """同步所有提示词到 Redis"""
        if not self._hot_reload_enabled:
            return
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_sync_prompts_to_redis())
            else:
                loop.run_until_complete(self._async_sync_prompts_to_redis())
        except Exception as e:
            logger.error(f"同步提示词到 Redis 失败: {e}")
    
    async def _async_sync_prompts_to_redis(self) -> None:
        """异步同步所有提示词到 Redis"""
        redis = await self._get_redis_client()
        if not redis:
            return
        
        try:
            # 同步所有提示词
            pipe = redis.pipeline()
            keys = []
            
            for key, entry in self._prompts.items():
                redis_key = self._get_redis_key(key)
                keys.append(key)
                
                # 存储为 JSON
                data = {
                    "key": entry.key,
                    "content": entry.content,
                    "default_content": entry.default_content,
                    "source": entry.source,
                    "version": entry.version,
                    "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
                    "updated_by": entry.updated_by,
                }
                pipe.set(redis_key, json.dumps(data, ensure_ascii=False))
            
            # 更新索引
            index_key = self._get_redis_index_key()
            pipe.delete(index_key)
            if keys:
                pipe.sadd(index_key, *keys)
            
            await pipe.execute()
            logger.debug(f"已同步 {len(keys)} 个提示词到 Redis")
        except Exception as e:
            logger.error(f"同步提示词到 Redis 失败: {e}")
    
    async def _load_prompt_from_redis(self, key: str) -> Optional[PromptEntry]:
        """从 Redis 加载单个提示词"""
        redis = await self._get_redis_client()
        if not redis:
            return None
        
        try:
            redis_key = self._get_redis_key(key)
            data = await redis.get(redis_key)
            
            if not data:
                return None
            
            parsed = json.loads(data)
            return PromptEntry(
                key=parsed["key"],
                content=parsed["content"],
                default_content=parsed.get("default_content"),
                source=parsed.get("source", "redis"),
                version=parsed.get("version", 1),
                updated_at=datetime.fromisoformat(parsed["updated_at"]) if parsed.get("updated_at") else None,
                updated_by=parsed.get("updated_by"),
            )
        except Exception as e:
            logger.error(f"从 Redis 加载提示词失败: {key}, {e}")
            return None
    
    async def _save_prompt_to_redis(self, entry: PromptEntry) -> None:
        """保存单个提示词到 Redis"""
        redis = await self._get_redis_client()
        if not redis:
            return
        
        try:
            redis_key = self._get_redis_key(entry.key)
            data = {
                "key": entry.key,
                "content": entry.content,
                "default_content": entry.default_content,
                "source": entry.source,
                "version": entry.version,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
                "updated_by": entry.updated_by,
            }
            await redis.set(redis_key, json.dumps(data, ensure_ascii=False))
            
            # 更新索引
            index_key = self._get_redis_index_key()
            await redis.sadd(index_key, entry.key)
            
            logger.debug(f"已保存提示词到 Redis: {entry.key}")
        except Exception as e:
            logger.error(f"保存提示词到 Redis 失败: {entry.key}, {e}")

    # ========================================================================
    # 守护线程：定时同步
    # ========================================================================
    
    def _start_sync_thread(self) -> None:
        """启动守护线程，定时从数据库同步到 Redis"""
        if not self._hot_reload_enabled:
            return

        # 保存数据库配置（用于守护线程创建独立连接）
        db_config = None
        if self.db_connection:
            # 从 asyncpg 连接池获取配置
            try:
                # asyncpg.Pool 没有直接暴露配置，从环境变量或 DatabaseManager 获取
                from agentclaw.database.manager import get_database
                global_db = get_database()
                if global_db and global_db.pg_config:
                    db_config = {
                        "host": global_db.pg_config.host,
                        "port": global_db.pg_config.port,
                        "user": global_db.pg_config.user,
                        "password": global_db.pg_config.password,
                        "database": global_db.pg_config.database,
                    }
            except Exception as e:
                logger.warning(f"无法获取数据库配置，守护线程将跳过: {e}")
                return

        if not db_config:
            logger.warning("数据库配置不可用，守护线程将跳过")
            return

        def sync_loop():
            import asyncio
            import asyncpg

            # 创建新的事件循环（在新线程中）
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 在新线程的事件循环中创建独立的数据库连接
            conn = None
            try:
                conn = loop.run_until_complete(asyncpg.connect(**db_config))
                logger.debug("守护线程已建立独立数据库连接")
            except Exception as e:
                logger.error(f"守护线程无法连接数据库: {e}")
                loop.close()
                return

            while not self._stop_sync.is_set():
                try:
                    # 等待指定间隔
                    self._stop_sync.wait(self.reload_interval)
                    if self._stop_sync.is_set():
                        break

                    # 从数据库同步更新（使用独立连接）
                    loop.run_until_complete(self._sync_from_database_with_conn(conn))
                except Exception as e:
                    logger.error(f"同步线程异常: {e}")

            # 清理
            if conn:
                try:
                    loop.run_until_complete(conn.close())
                except Exception as e:
                    logger.warning(f"关闭守护线程数据库连接失败: {e}")
            loop.close()
            logger.debug("同步线程已停止")

        self._sync_thread = threading.Thread(target=sync_loop, daemon=True, name="PromptSync")
        self._sync_thread.start()
        logger.info(f"提示词同步线程已启动，间隔: {self.reload_interval}s")
    
    def stop_sync(self) -> None:
        """停止同步线程"""
        if self._sync_thread and self._sync_thread.is_alive():
            self._stop_sync.set()
            self._sync_thread.join(timeout=5)
            logger.info("提示词同步线程已停止")
    
    async def _sync_from_database_with_conn(self, conn) -> None:
        """从数据库同步更新到 Redis 和内存（使用指定连接）"""
        if not conn or not self._hot_reload_enabled:
            return

        try:
            rows = await conn.fetch(
                """SELECT DISTINCT ON (prompt_key)
                       prompt_key, content, default_content, is_custom, version, created_at, updated_by
                   FROM prompts
                   WHERE workflow_id = $1 AND created_at > $2
                   ORDER BY prompt_key, created_at DESC""",
                self._workflow_id,
                self._last_reload or datetime.min
            )

            if not rows:
                return

            redis = await self._get_redis_client()

            for row in rows:
                key = row["prompt_key"]
                old_entry = self._prompts.get(key)
                new_version = row["version"] or 1

                if old_entry and old_entry.version >= new_version:
                    continue

                entry = PromptEntry(
                    key=key,
                    content=row["content"],
                    default_content=row["default_content"],
                    source="database",
                    updated_at=row["created_at"],
                    updated_by=row["updated_by"],
                    version=new_version,
                )
                self._prompts[key] = entry

                if redis:
                    await self._save_prompt_to_redis(entry)

                logger.info(f"同步提示词: {key} -> v{new_version}")

            self._last_reload = datetime.now()
            logger.debug(f"同步完成，更新了 {len(rows)} 个提示词")

        except Exception as e:
            logger.error(f"从数据库同步失败: {e}")

    async def _sync_from_database(self) -> None:
        """从数据库同步更新到 Redis 和内存"""
        if not self.db_connection or not self._hot_reload_enabled:
            return

        await self._sync_from_database_with_conn(self.db_connection)

    # ========================================================================
    # 获取提示词
    # ========================================================================
    
    async def _ensure_db_loaded(self) -> None:
        """确保已从数据库加载提示词（延迟加载）"""
        if self._db_loaded:
            return
        
        if self.source != "database":
            self._db_loaded = True
            return
        
        # 尝试从全局获取数据库连接
        if not self.db_connection:
            from agentclaw.database.manager import get_database
            global_db = get_database()
            if global_db and global_db.pg_pool:
                self.db_connection = global_db.pg_pool
                logger.debug("延迟加载: 从全局 DatabaseManager 获取数据库连接")
            
            # 同时获取 DatabaseManager 用于 Redis
            if global_db and not self._db_manager:
                self._db_manager = global_db
                logger.debug("延迟加载: 从全局获取 DatabaseManager（用于 Redis）")
        
        if self.db_connection:
            logger.info("延迟加载: 开始从数据库加载提示词")
            await self._async_load_from_database()
            self._db_loaded = True
            
            # 重新应用 register_default 的逻辑（更新 default_content）
            for node in self._workflow._nodes.values():
                if hasattr(node, 'system_prompt') and node.system_prompt:
                    existing = self._prompts.get(node.id)
                    if existing:
                        existing.default_content = node.system_prompt
                elif hasattr(node, 'prompt') and node.prompt:
                    existing = self._prompts.get(node.id)
                    if existing:
                        existing.default_content = node.prompt
            
            logger.info(f"延迟加载完成，共 {len(self._prompts)} 个提示词")
            
            # 检查并启用热更新（如果 Redis 现在可用）
            if self.hot_reload and not self._hot_reload_enabled:
                if self._db_manager and self._db_manager.is_redis_available():
                    self._hot_reload_enabled = True
                    logger.info("热更新已启用（Redis 可用）")
                    
                    # 同步到 Redis 并启动守护线程
                    await self._async_sync_prompts_to_redis()
                    self._start_sync_thread()
                    logger.info(f"热更新守护线程已启动，同步间隔: {self.reload_interval}s")
        else:
            logger.warning("延迟加载: 数据库连接仍不可用")
            self._db_loaded = True  # 标记为已尝试，避免重复尝试
    
    def get_prompt(
        self, 
        key: str, 
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        获取提示词并替换变量
        
        Args:
            key: 提示词 key
            variables: 模板变量（通常是 state）
        
        Returns:
            替换变量后的提示词
        
        Raises:
            KeyError: 提示词不存在
        """
        entry = self._prompts.get(key)
        
        if not entry:
            if key in self.default_prompts:
                content = self.default_prompts[key]
            else:
                raise KeyError(f"提示词 '{key}' 不存在")
        else:
            content = entry.content
        
        # 替换变量
        if variables:
            content = self._render_template(content, variables)
        
        return content
    
    def get_prompt_info(self, key: str) -> Optional[dict]:
        """获取提示词详细信息"""
        entry = self._prompts.get(key)
        if not entry:
            return None
        return {
            "key": entry.key,
            "content": entry.content,
            "default": entry.default_content,
            "is_custom": entry.is_custom,
            "variables": entry.variables,
            "source": entry.source,
            "version": entry.version,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
            "updated_by": entry.updated_by,
        }
    
    def _render_template(self, template: str, variables: dict) -> str:
        """渲染模板变量"""
        try:
            t = Template(template)
            result = t.safe_substitute(variables)
            
            def replace_braces(match):
                key = match.group(1)
                return str(variables.get(key, match.group(0)))
            
            result = re.sub(r'\{(\w+)\}', replace_braces, result)
            return result
        except Exception:
            return template
    
    def has_prompt(self, key: str) -> bool:
        """检查提示词是否存在"""
        return key in self._prompts or key in self.default_prompts
    
    def list_prompts(self) -> Dict[str, str]:
        """列出所有提示词"""
        return {key: entry.content for key, entry in self._prompts.items()}
    
    async def list_all_async(self) -> list:
        """列出所有提示词详细信息（异步版本，用于管理 API）"""
        await self._ensure_db_loaded()
        return [self.get_prompt_info(key) for key in self._prompts.keys()]
    
    def list_all(self) -> list:
        """列出所有提示词详细信息（用于管理 API）"""
        # 尝试同步触发延迟加载
        if not self._db_loaded and self.source == "database":
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在事件循环中，创建任务但不等待（下次调用会加载完成）
                    asyncio.create_task(self._ensure_db_loaded())
                else:
                    loop.run_until_complete(self._ensure_db_loaded())
            except Exception as e:
                logger.warning(f"延迟加载失败: {e}")
        
        return [self.get_prompt_info(key) for key in self._prompts.keys()]

    # ========================================================================
    # 更新提示词（热更新 API）
    # ========================================================================
    
    def is_hot_reload_enabled(self) -> bool:
        """检查热更新是否启用"""
        # 动态检查：如果有 _db_manager 且 Redis 可用，则启用
        if self._hot_reload_enabled:
            return True
        
        # 延迟检查：可能在初始化后 Redis 才连接成功
        if self.hot_reload and self._db_manager and self._db_manager.is_redis_available():
            self._hot_reload_enabled = True
            return True
        
        return False
    
    async def ensure_hot_reload_ready(self) -> bool:
        """
        确保热更新已就绪（异步版本，会尝试连接 Redis）
        
        Returns:
            热更新是否可用
        """
        if self._hot_reload_enabled:
            return True
        
        if not self.hot_reload:
            return False
        
        # 尝试连接 Redis
        if self._db_manager:
            connected = await self._ensure_redis_connected()
            if connected:
                self._hot_reload_enabled = True
                logger.info("热更新已启用（延迟连接成功）")
                return True
        
        return False
    
    def update_prompt(self, key: str, content: str, updated_by: str = "api") -> dict:
        """
        更新提示词（管理 API）
        
        Args:
            key: 提示词 key
            content: 新内容
            updated_by: 更新者
        
        Returns:
            更新后的提示词信息
            
        Raises:
            KeyError: 提示词不存在
            RuntimeError: 未配置数据库，无法持久化
        
        Note:
            更新流程：
            1. 保存到数据库（必须，持久化）
            2. 更新 Redis（可选，热更新）
            3. 更新内存（必须，当前实例生效）
        """
        # 尝试从全局获取数据库连接
        if not self.db_connection:
            from agentclaw.database.manager import get_database
            global_db = get_database()
            if global_db and global_db.pg_pool:
                self.db_connection = global_db.pg_pool
                logger.debug("从全局 DatabaseManager 获取数据库连接成功")
        
        # 检查是否配置了数据库
        if not self.db_connection:
            logger.error("未配置数据库连接，无法持久化")
            raise RuntimeError("未配置数据库，无法持久化提示词更新")
        
        entry = self._prompts.get(key)
        if not entry:
            raise KeyError(f"提示词 '{key}' 不存在")
        
        # 保留默认值
        default_content = entry.default_content or entry.content
        
        new_version = entry.version + 1
        now = datetime.now()
        
        # 1. 先保存到数据库（持久化）
        self._save_to_database(key, content, default_content, True, new_version, updated_by)
        logger.info(f"提示词已保存到数据库: {key} -> v{new_version} (by {updated_by})")
        
        # 2. 更新内存
        new_entry = PromptEntry(
            key=key,
            content=content,
            default_content=default_content,
            variables=entry.variables,
            source="custom",
            updated_at=now,
            updated_by=updated_by,
            version=new_version,
        )
        self._prompts[key] = new_entry
        
        # 3. 更新 Redis（如果配置了 Redis，实现热更新）
        if self._hot_reload_enabled:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._save_prompt_to_redis(new_entry))
                else:
                    loop.run_until_complete(self._save_prompt_to_redis(new_entry))
                logger.debug(f"提示词已更新到 Redis: {key}")
            except Exception as e:
                logger.warning(f"更新 Redis 失败（不影响持久化）: {e}")
        
        return self.get_prompt_info(key)
    
    def reset_prompt(self, key: str, updated_by: str = "api") -> dict:
        """
        重置提示词为默认值
        
        Args:
            key: 提示词 key
            updated_by: 操作者
        
        Returns:
            重置后的提示词信息
            
        Raises:
            KeyError: 提示词不存在
            ValueError: 提示词没有默认值
            RuntimeError: 未配置数据库，无法持久化
        
        Note:
            重置流程：
            1. 保存到数据库（必须，持久化）
            2. 更新 Redis（可选，热更新）
            3. 更新内存（必须，当前实例生效）
        """
        # 检查是否配置了数据库
        if not self.db_connection:
            raise RuntimeError("未配置数据库，无法持久化提示词重置")
        
        entry = self._prompts.get(key)
        if not entry:
            raise KeyError(f"提示词 '{key}' 不存在")
        
        if not entry.default_content:
            raise ValueError(f"提示词 '{key}' 没有默认值")
        
        new_version = entry.version + 1
        now = datetime.now()
        
        # 1. 先保存到数据库（持久化）
        self._save_to_database(
            key, entry.default_content, entry.default_content, 
            False, new_version, updated_by
        )
        logger.info(f"提示词已重置并保存到数据库: {key} -> v{new_version} (by {updated_by})")
        
        # 2. 更新内存
        new_entry = PromptEntry(
            key=key,
            content=entry.default_content,
            default_content=entry.default_content,
            variables=entry.variables,
            source="default",
            updated_at=now,
            updated_by=updated_by,
            version=new_version,
        )
        self._prompts[key] = new_entry
        
        # 3. 更新 Redis（如果配置了 Redis，实现热更新）
        if self._hot_reload_enabled:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._save_prompt_to_redis(new_entry))
                else:
                    loop.run_until_complete(self._save_prompt_to_redis(new_entry))
                logger.debug(f"提示词已更新到 Redis: {key}")
            except Exception as e:
                logger.warning(f"更新 Redis 失败（不影响持久化）: {e}")
        else:
            logger.debug(f"Redis 未启用，提示词重置需要重启服务才能生效")
        
        return self.get_prompt_info(key)

    # ========================================================================
    # 版本历史与回滚
    # ========================================================================
    
    async def get_history(self, key: str, limit: int = 10) -> list:
        """
        获取提示词的历史版本
        
        Args:
            key: 提示词 key
            limit: 返回的最大版本数
        
        Returns:
            历史版本列表，按版本号降序排列
        """
        if not self.db_connection:
            entry = self._prompts.get(key)
            if entry:
                return [{
                    "version": entry.version,
                    "content": entry.content,
                    "created_at": entry.updated_at.isoformat() if entry.updated_at else None,
                    "updated_by": entry.updated_by,
                }]
            return []
        
        try:
            rows = await self.db_connection.fetch(
                """SELECT version, content, created_at, updated_by
                   FROM prompts 
                   WHERE workflow_id = $1 AND prompt_key = $2
                   ORDER BY version DESC
                   LIMIT $3""",
                self._workflow_id,
                key,
                limit
            )
            
            return [
                {
                    "version": row["version"],
                    "content": row["content"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_by": row["updated_by"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取提示词历史失败: {e}")
            return []
    
    async def rollback_to_version(self, key: str, version: int, updated_by: str = "api") -> dict:
        """
        回滚到指定版本
        
        Args:
            key: 提示词 key
            version: 目标版本号
            updated_by: 操作者
        
        Returns:
            回滚后的提示词信息
        """
        if not self._hot_reload_enabled:
            raise RuntimeError("热更新未启用，需要配置 Redis")
        
        if not self.db_connection:
            raise ValueError("回滚功能需要数据库支持")
        
        try:
            row = await self.db_connection.fetchrow(
                """SELECT content, default_content
                   FROM prompts 
                   WHERE workflow_id = $1 AND prompt_key = $2 AND version = $3""",
                self._workflow_id,
                key,
                version
            )
            
            if not row:
                raise ValueError(f"版本 {version} 不存在")
            
            return self.update_prompt(key, row["content"], updated_by)
        except Exception as e:
            logger.error(f"回滚提示词失败: {e}")
            raise
    
    def _save_to_database(
        self, 
        key: str, 
        content: str, 
        default_content: str, 
        is_custom: bool, 
        version: int, 
        updated_by: str
    ) -> None:
        """保存 prompt 到数据库（插入新版本，保留历史）"""
        import asyncio
        
        async def _do_save():
            try:
                await self.db_connection.execute(
                    """INSERT INTO prompts (workflow_id, prompt_key, content, default_content, is_custom, version, created_at, updated_by)
                       VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7)""",
                    self._workflow_id,
                    key,
                    content,
                    default_content,
                    is_custom,
                    version,
                    updated_by
                )
                logger.debug(f"Prompt 已保存到数据库: {key} v{version}")
            except Exception as e:
                logger.error(f"保存 prompt 到数据库失败: {e}")
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_do_save())
            else:
                loop.run_until_complete(_do_save())
        except RuntimeError as e:
            logger.warning(f"无法获取事件循环，Prompt 未保存到数据库: {e}")

    # ========================================================================
    # 注册提示词
    # ========================================================================
    
    def register(self, key: str, content: str) -> None:
        """
        注册提示词（简便方法）
        
        Args:
            key: 提示词键
            content: 提示词内容
        """
        self._prompts[key] = PromptEntry(
            key=key,
            content=content,
            default_content=content,
            source="code",
        )
    
    def register_default(self, key: str, content: str) -> None:
        """
        注册默认提示词（从代码同步）
        
        行为约定：
        - 若已存在且是自定义版本（is_custom=True）：保留自定义内容，仅更新 default_content
        - 若已存在且非自定义：同步覆盖 content，避免代码更新后仍沿用陈旧默认值
        """
        existing = self._prompts.get(key)
        
        if existing:
            was_custom = existing.is_custom
            # 已存在：总是更新默认值
            existing.default_content = content
            if was_custom:
                # 自定义内容优先，不覆盖
                logger.debug(f"register_default: key={key} 为自定义版本，保留当前内容，更新默认值")
            else:
                # 非自定义默认项：跟随代码更新
                existing.content = content
                logger.debug(f"register_default: key={key} 非自定义，更新内容与默认值")
        else:
            # 不存在：创建新条目
            self._prompts[key] = PromptEntry(
                key=key,
                content=content,
                default_content=content,
                source="default",
            )
            logger.debug(f"register_default: key={key} 不存在，创建新条目（使用默认值）")
    
    def set_prompt(self, key: str, content: str) -> None:
        """设置提示词（运行时，不触发持久化）"""
        self._prompts[key] = PromptEntry(
            key=key,
            content=content,
            source="runtime",
            updated_at=datetime.now(),
        )
    
    async def sync_from_workflow(self, workflow: "Workflow") -> int:
        """
        从工作流同步默认提示词（启动时调用）
        
        收集所有节点的内联 prompt，注册为默认值
        
        Returns:
            同步的提示词数量
        """
        count = 0
        for node in workflow._nodes.values():
            if hasattr(node, 'prompt') and node.prompt:
                self.register_default(node.id, node.prompt)
                count += 1
        
        if count > 0:
            logger.info(f"从工作流同步了 {count} 个默认提示词")
        
        return count


class PromptEntry:
    """提示词条目"""
    
    def __init__(
        self,
        key: str,
        content: str,
        default_content: Optional[str] = None,
        variables: Optional[list] = None,
        source: str = "unknown",
        updated_at: Optional[datetime] = None,
        updated_by: Optional[str] = None,
        version: int = 1,
    ):
        self.key = key
        self.content = content
        self.default_content = default_content
        self.variables = variables or []
        self.source = source
        self.updated_at = updated_at or datetime.now()
        self.updated_by = updated_by
        self.version = version
    
    @property
    def is_custom(self) -> bool:
        """是否已自定义（与默认值不同）"""
        return self.default_content is not None and self.content != self.default_content
