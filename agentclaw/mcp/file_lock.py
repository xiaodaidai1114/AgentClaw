from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from agentclaw.database.manager import RedisConfig
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)
_LOCK_TIMEOUT = float(os.getenv("AGENTCLAW_FILE_LOCK_TIMEOUT", "30"))
_LOCK_TTL = int(os.getenv("AGENTCLAW_FILE_LOCK_TTL", "120"))
_REDIS_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
_backends: dict[int, object] = {}


class InMemoryFileLockBackend:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: str):
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
        await asyncio.wait_for(lock.acquire(), timeout=_LOCK_TIMEOUT)
        try:
            yield
        finally:
            lock.release()


class RedisFileLockBackend:
    def __init__(self, client):
        self._client = client

    @asynccontextmanager
    async def lock(self, key: str):
        token = secrets.token_hex(16)
        lock_key = f"agentclaw:file-lock:{key}"
        deadline = asyncio.get_running_loop().time() + _LOCK_TIMEOUT
        while True:
            acquired = await self._client.set(lock_key, token, ex=_LOCK_TTL, nx=True)
            if acquired:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"timed out waiting for file lock: {key}")
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            try:
                await self._client.eval(_REDIS_RELEASE_LUA, 1, lock_key, token)
            except Exception:
                pass


async def _build_backend():
    try:
        import redis.asyncio as aioredis

        config = RedisConfig.from_env()
        client = aioredis.Redis(
            host=config.host,
            port=config.port,
            password=config.password or None,
            db=config.db,
            decode_responses=True,
        )
        await client.ping()
        logger.info(f"文件锁使用 Redis: {config.host}:{config.port}")
        return RedisFileLockBackend(client)
    except Exception as e:
        logger.debug(f"文件锁退回内存模式: {e}")
        return InMemoryFileLockBackend()


async def _get_backend():
    loop_id = id(asyncio.get_running_loop())
    backend = _backends.get(loop_id)
    if backend is None:
        backend = await _build_backend()
        _backends[loop_id] = backend
    return backend


@asynccontextmanager
async def file_write_lock(path: str | Path):
    key = str(Path(path).resolve())
    backend = await _get_backend()
    async with backend.lock(key):
        yield
