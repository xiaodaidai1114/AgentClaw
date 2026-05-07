"""
定时任务模块 - 进程锁

基于 PostgreSQL advisory lock，防止多进程重复执行同一任务。
"""

from contextlib import asynccontextmanager

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class AdvisoryLock:
    """PostgreSQL advisory lock"""

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def try_acquire(self, key: str) -> bool:
        """尝试获取锁（非阻塞），返回是否成功"""
        lock_key = f"scheduler:job:{key}"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT pg_try_advisory_lock(hashtext($1)) as acquired", lock_key
            )
        acquired = row["acquired"] if row else False
        if acquired:
            logger.debug(f"Advisory lock acquired: {key}")
        return acquired

    async def release(self, key: str) -> None:
        """释放锁"""
        lock_key = f"scheduler:job:{key}"
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtext($1))", lock_key
            )
        logger.debug(f"Advisory lock released: {key}")

    @asynccontextmanager
    async def lock(self, key: str):
        """上下文管理器：自动获取和释放锁"""
        acquired = await self.try_acquire(key)
        if not acquired:
            raise LockNotAcquiredError(key)
        try:
            yield
        finally:
            await self.release(key)


class LockNotAcquiredError(Exception):
    """无法获取锁"""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Failed to acquire lock: {key}")
