"""
状态检查点管理

提供 LangGraph 状态持久化功能（参考 ref/app/utils/checkpointer.py）
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
import asyncio
import os

from ..platform_compat import (
    apply_windows_selector_event_loop_policy,
    get_service_host_fallback,
    is_windows_proactor_event_loop,
    normalize_service_host,
)
from agentclaw.logger.config import get_logger
from langgraph.checkpoint.base import BaseCheckpointSaver

apply_windows_selector_event_loop_policy()

logger = get_logger(__name__)

# 全局实例
_checkpointer = None
_connection_pool = None
_keepalive_task = None


async def _run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _close_pool(pool: Any) -> None:
    close = getattr(pool, "close", None)
    if close is None:
        return
    if asyncio.iscoroutinefunction(close):
        await close()
    else:
        await _run_blocking(close)


class ThreadedPostgresSaver(BaseCheckpointSaver):
    """Windows-safe async facade over the sync PostgresSaver."""

    def __init__(self, saver: Any):
        super().__init__(serde=getattr(saver, "serde", None))
        self._saver = saver
        self.conn = getattr(saver, "conn", None)

    async def async_setup(self) -> None:
        await _run_blocking(self._saver.setup)

    @property
    def config_specs(self):
        return getattr(self._saver, "config_specs", [])

    def get_tuple(self, config: Dict[str, Any]) -> Any:
        return self._saver.get_tuple(config)

    def list(self, *args, **kwargs):
        return self._saver.list(*args, **kwargs)

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Dict[str, Any],
        new_versions: Dict[str, Any],
    ) -> Any:
        return self._saver.put(config, checkpoint, metadata, new_versions)

    def put_writes(
        self,
        config: Dict[str, Any],
        writes: List[Any],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._saver.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        self._saver.delete_thread(thread_id)

    async def aget_tuple(self, config: Dict[str, Any]) -> Any:
        return await _run_blocking(self._saver.get_tuple, config)

    async def aget(self, config: Dict[str, Any]) -> Any:
        return await _run_blocking(self._saver.get, config)

    async def alist(self, *args, **kwargs):
        items = await _run_blocking(lambda: list(self._saver.list(*args, **kwargs)))
        for item in items:
            yield item

    async def aput(self, config: Dict[str, Any], checkpoint: Dict[str, Any], metadata: Dict[str, Any], new_versions: Dict[str, Any]) -> Any:
        return await _run_blocking(self._saver.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: Dict[str, Any], writes: List[Any], task_id: str, task_path: str = "") -> None:
        await _run_blocking(self._saver.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await _run_blocking(self._saver.delete_thread, thread_id)

    async def aping(self) -> None:
        def _ping():
            with self.conn.connection() as conn:
                conn.execute("SELECT 1")
        await _run_blocking(_ping)


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """获取环境变量，空字符串视为未设置"""
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def _normalize_pg_host(host: Optional[str]) -> Optional[str]:
    if host is None:
        return None
    normalized = normalize_service_host(host)
    fallback = get_service_host_fallback(host)
    if fallback and normalized == fallback:
        logger.warning(f"检测到 PG_HOST={host}，当前为宿主机运行，自动回退到 {fallback}")
    return normalized


async def _ensure_database_exists(host: str, port: str, user: str, password: str, database: str) -> bool:
    """
    确保数据库存在，不存在则自动创建
    
    Args:
        host: 数据库主机
        port: 端口
        user: 用户名
        password: 密码
        database: 数据库名
    
    Returns:
        是否成功
    """
    import psycopg
    
    # 连接到 postgres 默认数据库来创建目标数据库
    admin_conn_string = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    
    try:
        # 使用同步连接检查和创建数据库
        conn = psycopg.connect(admin_conn_string, autocommit=True)
        try:
            cursor = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
            )
            exists = cursor.fetchone() is not None
            
            if not exists:
                # 数据库不存在，创建它
                conn.execute(f'CREATE DATABASE "{database}"')
                logger.info(f"✅ 自动创建数据库: {database}")
            
            return True
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"检查/创建数据库失败: {e}")
        return False


async def setup_checkpointer(connection_string: Optional[str] = None) -> Any:
    """
    设置状态检查点器
    
    Args:
        connection_string: PostgreSQL 连接字符串（可选，也可从环境变量构造）
    
    Returns:
        AsyncPostgresSaver 实例
    """
    global _checkpointer, _connection_pool
    
    # 单例模式
    if _checkpointer is not None:
        logger.debug("复用已存在的 checkpointer 实例")
        return _checkpointer
    
    from psycopg_pool import AsyncConnectionPool, ConnectionPool
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    
    # 获取连接参数
    host = _normalize_pg_host(_get_env("PG_HOST"))
    if not host:
        logger.warning("未配置 PG_HOST，状态持久化已禁用")
        return None
    
    user = _get_env("PG_USER", "postgres")
    password = quote_plus(_get_env("PG_PASSWORD", ""))  # URL 编码特殊字符
    database = _get_env("PG_DATABASE", "agentclaw")
    port = _get_env("PG_PORT", "5432")
    
    # 确保数据库存在
    await _ensure_database_exists(host, port, user, password, database)
    
    # 构造连接字符串
    if not connection_string:
        connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    
    # 连接池配置
    pool_min_size = int(_get_env("PG_POOL_MIN_SIZE", "2"))
    pool_max_size = int(_get_env("PG_POOL_MAX_SIZE", "10"))
    pool_timeout = float(_get_env("PG_POOL_TIMEOUT", "30"))
    
    try:
        if is_windows_proactor_event_loop():
            _connection_pool = ConnectionPool(
                conninfo=connection_string,
                min_size=pool_min_size,
                max_size=pool_max_size,
                timeout=pool_timeout,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await _run_blocking(_connection_pool.open, wait=True, timeout=pool_timeout)
            _checkpointer = ThreadedPostgresSaver(PostgresSaver(conn=_connection_pool))
            await _checkpointer.async_setup()
            logger.info(
                f"✅ 状态检查点器已初始化 (pool: {pool_min_size}-{pool_max_size}, mode: windows-threaded)"
            )
            return _checkpointer

        # 创建连接池
        _connection_pool = AsyncConnectionPool(
            conninfo=connection_string,
            min_size=pool_min_size,
            max_size=pool_max_size,
            timeout=pool_timeout,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,  # 禁用 prepared statements
                "row_factory": dict_row,
            },
        )
        await _connection_pool.open()
        
        # 创建 checkpointer
        _checkpointer = AsyncPostgresSaver(conn=_connection_pool)
        await _checkpointer.setup()
        
        logger.info(f"✅ 状态检查点器已初始化 (pool: {pool_min_size}-{pool_max_size})")
        return _checkpointer
        
    except Exception as e:
        message = str(e)
        if "proactoreventloop" in message.lower():
            logger.warning(
                "Windows 当前事件循环仍为 ProactorEventLoop，"
                "PostgreSQL Checkpointer 已自动降级为内存模式"
            )
        else:
            logger.error(f"初始化检查点器失败: {e}")
        if _connection_pool:
            try:
                await _close_pool(_connection_pool)
            except:
                pass
            _connection_pool = None
        return None


def get_checkpointer() -> Optional[Any]:
    """获取全局检查点器"""
    return _checkpointer


async def close_checkpointer() -> None:
    """关闭检查点器和连接池"""
    global _checkpointer, _connection_pool
    
    await stop_keepalive_task()
    
    if _connection_pool:
        try:
            await _close_pool(_connection_pool)
            logger.info("✅ 连接池已关闭")
        except Exception as e:
            logger.warning(f"关闭连接池失败: {e}")
        finally:
            _connection_pool = None
            _checkpointer = None


async def start_keepalive_task(interval: int = 60) -> None:
    """启动连接保活任务"""
    global _keepalive_task
    
    if _keepalive_task is not None:
        return
    
    async def keepalive():
        while True:
            await asyncio.sleep(interval)
            if _checkpointer and hasattr(_checkpointer, "aping"):
                try:
                    await _checkpointer.aping()
                except Exception:
                    pass
            elif _checkpointer and hasattr(_checkpointer, 'conn'):
                try:
                    await _checkpointer.conn.execute("SELECT 1")
                except Exception:
                    pass
    
    _keepalive_task = asyncio.create_task(keepalive())


async def stop_keepalive_task() -> None:
    """停止保活任务"""
    global _keepalive_task
    
    if _keepalive_task:
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass
        _keepalive_task = None


async def get_state_by_thread(thread_id: str) -> Optional[Dict]:
    """
    获取指定线程的状态
    
    Args:
        thread_id: 线程 ID
    
    Returns:
        状态字典或 None
    """
    if not _checkpointer:
        return None
    
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = await _checkpointer.aget(config)
        return state
    except Exception as e:
        logger.warning(f"获取状态失败: {e}")
        return None


async def list_thread_states(limit: int = 100) -> List[Dict]:
    """
    列出所有线程状态
    
    Args:
        limit: 返回数量限制
    
    Returns:
        状态列表
    """
    if not _checkpointer:
        return []
    
    try:
        # 这个功能依赖于具体的 checkpointer 实现
        states = []
        async for state in _checkpointer.alist(limit=limit):
            states.append(state)
        return states
    except Exception as e:
        logger.warning(f"列出状态失败: {e}")
        return []


def create_memory_checkpointer() -> Any:
    """
    创建内存检查点器（用于开发/测试）
    
    Returns:
        MemorySaver 实例
    """
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()


async def save_checkpoint(thread_id: str, state: Dict, node_id: str = "") -> bool:
    """
    保存检查点
    
    Args:
        thread_id: 线程 ID
        state: 状态数据
        node_id: 当前节点名（可选）
    
    Returns:
        是否保存成功
    """
    if not _checkpointer:
        return False
    
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint = {
            "v": 1,
            "ts": asyncio.get_event_loop().time(),
            "channel_values": state,
            "channel_versions": {},
            "versions_seen": {},
        }
        await _checkpointer.aput(config, checkpoint, {}, {})
        logger.debug(f"检查点已保存: thread_id={thread_id}, node={node_id}")
        return True
    except Exception as e:
        logger.warning(f"保存检查点失败: {e}")
        return False
