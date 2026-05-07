"""
StorageBackend - 文件存储后端抽象

支持本地文件系统和 MinIO 对象存储，通过统一的接口访问文件。

storage key 是相对路径，如 "uploads/{hash}.png" 或 "knowledgebase/{kb_id}/{hash}.pdf"。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def is_safe_storage_key(key: str) -> bool:
    """Return true when a storage key is relative and cannot escape a local root."""
    if not key:
        return False
    path = Path(str(key))
    return not path.is_absolute() and ".." not in path.parts


@runtime_checkable
class StorageBackend(Protocol):
    """文件存储后端协议"""

    async def save(self, key: str, data: bytes) -> str:
        """保存文件，返回 storage key"""
        ...

    async def get(self, key: str) -> Optional[bytes]:
        """读取文件内容，不存在返回 None"""
        ...

    async def delete(self, key: str) -> bool:
        """删除文件，返回是否成功"""
        ...

    async def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        ...

    def get_local_path(self, key: str) -> Optional[str]:
        """获取本地文件路径（仅本地后端可直接返回，MinIO 返回 None）"""
        ...


class LocalStorageBackend:
    """本地文件系统存储后端"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, key: str) -> Optional[Path]:
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 storage key: {key}")
            return None
        path = Path(str(key))
        resolved = (self.base_dir / path).resolve()
        try:
            resolved.relative_to(self.base_dir)
        except ValueError:
            logger.warning(f"拒绝越界 storage key: {key}")
            return None
        return resolved

    async def save(self, key: str, data: bytes) -> str:
        file_path = self._resolve_key(key)
        if file_path is None:
            raise ValueError(f"Invalid storage key: {key}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return key

    async def get(self, key: str) -> Optional[bytes]:
        file_path = self._resolve_key(key)
        if file_path is None:
            return None
        if file_path.exists():
            return file_path.read_bytes()
        return None

    async def delete(self, key: str) -> bool:
        file_path = self._resolve_key(key)
        if file_path is None:
            return False
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    async def exists(self, key: str) -> bool:
        path = self._resolve_key(key)
        return bool(path and path.exists())

    def get_local_path(self, key: str) -> Optional[str]:
        path = self._resolve_key(key)
        if path is None:
            return None
        return str(path) if path.exists() else None


class MinIOStorageBackend:
    """MinIO 对象存储后端"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "agentclaw",
        secure: bool = True,
    ):
        try:
            from minio import Minio
        except ImportError:
            raise ImportError(
                "MinIOStorageBackend 需要 minio 库，请安装: pip install minio"
            )

        self.client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        self.bucket = bucket
        self._ensure_bucket()
        self._cache_dir = Path(tempfile.gettempdir()) / "agentclaw_minio_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info(f"MinIO bucket 已创建: {self.bucket}")

    async def save(self, key: str, data: bytes) -> str:
        import io

        if not is_safe_storage_key(key):
            raise ValueError(f"Invalid storage key: {key}")
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            key,
            io.BytesIO(data),
            len(data),
        )
        return key

    async def get(self, key: str) -> Optional[bytes]:
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 MinIO storage key: {key}")
            return None
        try:
            response = await asyncio.to_thread(
                self.client.get_object, self.bucket, key
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:
            return None

    async def delete(self, key: str) -> bool:
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 MinIO storage key: {key}")
            return False
        try:
            await asyncio.to_thread(
                self.client.remove_object, self.bucket, key
            )
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 MinIO storage key: {key}")
            return False
        try:
            await asyncio.to_thread(self.client.stat_object, self.bucket, key)
            return True
        except Exception:
            return False

    def get_local_path(self, key: str) -> Optional[str]:
        """MinIO 无法直接返回本地路径，需要先下载"""
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 MinIO storage key: {key}")
            return None
        cache_path = self._cache_dir / key
        if cache_path.exists():
            return str(cache_path)
        return None

    async def download_to_local(self, key: str) -> Optional[str]:
        """下载文件到本地缓存并返回路径"""
        if not is_safe_storage_key(key):
            logger.warning(f"拒绝非法 MinIO storage key: {key}")
            return None
        cache_path = self._cache_dir / key
        if cache_path.exists():
            return str(cache_path)

        data = await self.get(key)
        if data is None:
            return None

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        return str(cache_path)


def create_storage_backend() -> StorageBackend:
    """根据配置创建存储后端"""
    from agentclaw.config import get_config

    config = get_config()
    upload_config = config.upload

    if upload_config.use_minio:
        logger.info(f"使用 MinIO 存储后端: {upload_config.minio_endpoint}")
        return MinIOStorageBackend(
            endpoint=upload_config.minio_endpoint,
            access_key=upload_config.minio_access_key,
            secret_key=upload_config.minio_secret_key,
            bucket=upload_config.minio_bucket,
            secure=upload_config.minio_secure,
        )

    # 本地存储
    base_dir = Path(upload_config.upload_dir)
    if not base_dir.is_absolute():
        base_dir = config.project.project_dir / base_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"使用本地存储后端: {base_dir}")
    return LocalStorageBackend(base_dir)
