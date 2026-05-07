"""
FileStorage - 统一文件存储服务

所有文件（通用上传、知识库文档）统一通过此服���管理。
支持本地文件系统和 MinIO 存储后端，由配置决定。
文件元数据统一记录到 PostgreSQL `files` 表。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from pathlib import Path
import hashlib
import mimetypes

from agentclaw.database.storage_backend import (
    StorageBackend,
    LocalStorageBackend,
    create_storage_backend,
)
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.database.manager import DatabaseManager

logger = get_logger(__name__)


def _resolve_configured_path(path_value: str, project_dir: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


def allowed_legacy_file_roots() -> list[Path]:
    """Return local roots that may contain legacy absolute file paths."""
    from agentclaw.config import get_config

    config = get_config()
    project_dir = config.project.project_dir
    candidates = [
        config.upload.upload_dir,
        config.knowledgebase.storage_dir,
        config.knowledgebase.parser_cache_dir,
    ]
    roots: list[Path] = []
    for candidate in candidates:
        try:
            root = _resolve_configured_path(str(candidate), project_dir)
        except Exception:
            continue
        if root not in roots:
            roots.append(root)
    return roots


def resolve_allowed_legacy_file_path(file_path: str) -> Optional[Path]:
    """Resolve an old absolute path only when it is contained by an allowed root."""
    path = Path(str(file_path)).expanduser()
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve()
    except Exception:
        return None
    for root in allowed_legacy_file_roots():
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    logger.warning(f"拒绝访问越界旧文件路径: {file_path}")
    return None


@dataclass
class StoredFile:
    """存储的文件信息"""
    id: str                    # hash 前 32 位
    original_name: str         # 原始文件名
    file_path: str             # 存储 key（如 uploads/{hash}.png）或旧数据的绝对路径
    file_hash: str             # 文件内容 SHA256
    mime_type: str             # MIME 类型
    size: int                  # 文件大小（字节）

    @property
    def url(self) -> str:
        """获取可在浏览器中直接展示的短期签名 URL"""
        from agentclaw.api.files.signing import get_signed_file_url

        return get_signed_file_url(self.id)


class FileStorage:
    """
    统一文件存储服务

    Example:
        storage = FileStorage(db_manager)

        # 保存文件（默认 uploads/ 前缀）
        stored = await storage.save(file_bytes, "image.png")
        print(stored.url)  # /api/files/{id}?token=...

        # 保存知识库文档（指定前缀）
        stored = await storage.save_with_prefix(data, "doc.pdf", prefix="knowledgebase/kb123")

        # 获取文件内容
        data = await storage.get_file_bytes(file_id)

        # 获取本地路径（给 parser 等需要磁盘路径的组件用）
        path = await storage.get_local_path(file_id)
    """

    def __init__(self, db: Optional["DatabaseManager"] = None, backend: Optional[StorageBackend] = None):
        self.db = db
        self._backend = backend

    @property
    def backend(self) -> StorageBackend:
        if self._backend is None:
            self._backend = create_storage_backend()
        return self._backend

    # ── 工具方法 ──────────────────────────────────────────

    def _compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _get_extension(self, filename: str, mime_type: Optional[str] = None) -> str:
        ext = Path(filename).suffix.lower()
        if ext:
            return ext
        if mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                return guessed
        return ""

    def _guess_mime_type(self, filename: str, data: Optional[bytes] = None) -> str:
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            return mime_type
        if data and len(data) >= 8:
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                return "image/png"
            if data[:2] == b'\xff\xd8':
                return "image/jpeg"
            if data[:6] in (b'GIF87a', b'GIF89a'):
                return "image/gif"
            if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                return "image/webp"
            if data[:4] == b'%PDF':
                return "application/pdf"
        return "application/octet-stream"

    # ── 核心存储方法 ─────────────────────────────────────

    async def save(
        self,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> StoredFile:
        """保存文件（默认 uploads/ 前缀）"""
        return await self.save_with_prefix(data, filename, prefix="uploads", mime_type=mime_type)

    async def save_with_prefix(
        self,
        data: bytes,
        filename: str,
        prefix: str = "uploads",
        mime_type: Optional[str] = None,
    ) -> StoredFile:
        """保存文件到指定前缀路径"""
        file_hash = self._compute_hash(data)
        ext = self._get_extension(filename, mime_type)
        if not mime_type:
            mime_type = self._guess_mime_type(filename, data)

        file_id = file_hash[:32]
        storage_key = f"{prefix}/{file_hash}{ext}"

        # 去重：数据库查找
        existing = await self.find_by_hash(file_hash)
        if existing:
            # 验证文件仍然存在于存储后端（防止数据库与文件系统不同步）
            if await self.backend.exists(existing.file_path):
                return existing
            logger.warning(f"数据库记录存在但文件已丢失，清理脏记录: {existing.file_path}")
            await self._delete_from_db(existing.id)

        # 去重：后端查找
        if await self.backend.exists(storage_key):
            logger.debug(f"文件已存在（后端 hash 匹配）: {storage_key}")
            stored = StoredFile(
                id=file_id,
                original_name=filename,
                file_path=storage_key,
                file_hash=file_hash,
                mime_type=mime_type,
                size=len(data),
            )
            await self._save_to_db(stored)
            return stored

        # 写入后端
        await self.backend.save(storage_key, data)
        logger.info(f"文件已保存: {storage_key}")

        stored = StoredFile(
            id=file_id,
            original_name=filename,
            file_path=storage_key,
            file_hash=file_hash,
            mime_type=mime_type,
            size=len(data),
        )
        await self._save_to_db(stored)
        return stored

    async def save_base64(
        self,
        base64_data: str,
        filename: str = "file",
        mime_type: Optional[str] = None,
    ) -> StoredFile:
        """保存 base64 编码的文件"""
        import base64

        if base64_data.startswith("data:"):
            header, data = base64_data.split(",", 1)
            if not mime_type and ";" in header:
                mime_type = header.split(":")[1].split(";")[0]
        else:
            data = base64_data

        file_bytes = base64.b64decode(data)
        return await self.save(file_bytes, filename, mime_type)

    # ── 读取方法 ─────────────────────────────────────────

    async def get_file_bytes(self, file_id: str) -> Optional[bytes]:
        """通过文件 ID 获取文件内容"""
        stored = await self.find_by_id(file_id)
        if not stored:
            return None
        stored = await self._migrate_legacy_absolute_file(stored)
        return await self._read_file(stored.file_path)

    async def get_file_bytes_by_key(self, storage_key: str) -> Optional[bytes]:
        """通过 storage key 获取文件内容"""
        return await self._read_file(storage_key)

    async def get_local_path(self, file_id: str) -> Optional[str]:
        """通过文件 ID 获取本地路径（MinIO 时会下载到临时目录）"""
        stored = await self.find_by_id(file_id)
        if not stored:
            return None
        return await self._resolve_local_path(stored.file_path)

    async def get_local_path_by_key(self, storage_key: str) -> Optional[str]:
        """通过 storage key 获取本地路径"""
        return await self._resolve_local_path(storage_key)

    async def _read_file(self, file_path: str) -> Optional[bytes]:
        """读取文件内容，兼容旧数据（绝对路径）和新数据（storage key）"""
        # 旧数据：绝对路径直接读
        if Path(file_path).is_absolute():
            p = resolve_allowed_legacy_file_path(file_path)
            if not p:
                return None
            if p.exists():
                return p.read_bytes()
            return None
        # 新数据：通过后端读取
        return await self.backend.get(file_path)

    async def _migrate_legacy_absolute_file(self, stored: StoredFile) -> StoredFile:
        """Copy an allowed legacy absolute path into storage and persist its storage key."""
        if not Path(stored.file_path).is_absolute():
            return stored
        source_path = resolve_allowed_legacy_file_path(stored.file_path)
        if not source_path or not source_path.exists() or not source_path.is_file():
            return stored
        try:
            data = source_path.read_bytes()
        except OSError as exc:
            logger.warning(f"读取旧文件路径失败，跳过迁移: {exc}")
            return stored

        file_hash = stored.file_hash or self._compute_hash(data)
        suffix = source_path.suffix.lower() or self._get_extension(stored.original_name, stored.mime_type)
        storage_key = f"uploads/{file_hash}{suffix}"
        try:
            if not await self.backend.exists(storage_key):
                await self.backend.save(storage_key, data)
            if self.db and self.db.pg_pool:
                await self.db.pg_execute(
                    "UPDATE files SET file_path = $1 WHERE id = $2",
                    storage_key,
                    stored.id,
                )
            return StoredFile(
                id=stored.id,
                original_name=stored.original_name,
                file_path=storage_key,
                file_hash=file_hash,
                mime_type=stored.mime_type,
                size=stored.size or len(data),
            )
        except Exception as exc:
            logger.warning(f"迁移旧文件路径失败，继续使用旧路径: {exc}")
            return stored

    async def _resolve_local_path(self, file_path: str) -> Optional[str]:
        """获取本地文件路径，兼容旧数据和新数据"""
        # 旧数据：绝对路径直接返回
        if Path(file_path).is_absolute():
            p = resolve_allowed_legacy_file_path(file_path)
            if not p:
                return None
            return str(p) if p.exists() else None

        # 新数据：先尝试后端的 get_local_path
        local = self.backend.get_local_path(file_path)
        if local:
            return local

        # MinIO 后端：需要下载到本地
        from agentclaw.database.storage_backend import MinIOStorageBackend
        if isinstance(self.backend, MinIOStorageBackend):
            return await self.backend.download_to_local(file_path)

        return None

    # ── 查找方法 ─────────────────────────────────────────

    async def find_by_hash(self, file_hash: str) -> Optional[StoredFile]:
        """通过 hash 查找文件（用于去重）"""
        if not self.db or not self.db.pg_pool:
            return None
        try:
            row = await self.db.pg_fetchrow(
                "SELECT * FROM files WHERE file_hash = $1", file_hash
            )
            if row:
                return self._row_to_stored(row)
        except Exception as e:
            logger.warning(f"查询文件失败: {e}")
        return None

    async def find_by_id(self, file_id: str) -> Optional[StoredFile]:
        """通过 ID 查找文件"""
        if self.db and self.db.pg_pool:
            try:
                row = await self.db.pg_fetchrow(
                    "SELECT * FROM files WHERE id = $1", file_id
                )
                if row:
                    return self._row_to_stored(row)
            except Exception as e:
                logger.warning(f"查询文件失败: {e}")
        return None

    @staticmethod
    def _row_to_stored(row) -> StoredFile:
        return StoredFile(
            id=str(row["id"]),
            original_name=row["original_name"],
            file_path=row["file_path"],
            file_hash=row["file_hash"],
            mime_type=row["mime_type"],
            size=row["size"],
        )

    # ── 删除方法 ─────────────────────────────────────────

    async def delete(self, file_id: str) -> bool:
        """删除文件"""
        stored = await self.find_by_id(file_id)
        if not stored:
            return False

        # 删除存储
        file_path = stored.file_path
        if Path(file_path).is_absolute():
            p = resolve_allowed_legacy_file_path(file_path)
            if p:
                p.unlink(missing_ok=True)
        else:
            await self.backend.delete(file_path)

        # 删除数据库记录
        if self.db and self.db.pg_pool:
            try:
                await self.db.pg_execute("DELETE FROM files WHERE id = $1", file_id)
            except Exception as e:
                logger.warning(f"删除文件记录失败: {e}")

        return True

    async def delete_by_key(self, storage_key: str) -> bool:
        """通过 storage key 删除文件（不删数据库记录）"""
        if Path(storage_key).is_absolute():
            p = resolve_allowed_legacy_file_path(storage_key)
            if not p:
                return False
            p.unlink(missing_ok=True)
            return True
        return await self.backend.delete(storage_key)

    # ── 数据库 ─────────────────────��─────────────────────

    async def _save_to_db(self, stored: StoredFile) -> None:
        if not self.db or not self.db.pg_pool:
            return
        try:
            await self.db.pg_execute(
                """
                INSERT INTO files (id, original_name, file_path, file_hash, mime_type, size)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO NOTHING
                """,
                stored.id,
                stored.original_name,
                stored.file_path,
                stored.file_hash,
                stored.mime_type,
                stored.size,
            )
        except Exception as e:
            logger.warning(f"保存文件记录失败: {e}")

    async def _delete_from_db(self, file_id: str) -> None:
        if not self.db or not self.db.pg_pool:
            return
        try:
            await self.db.pg_execute("DELETE FROM files WHERE id = $1", file_id)
        except Exception as e:
            logger.warning(f"删除文件记录失败: {e}")


# ── 全局实例 ─────────────────────────────────────────────

_global_storage: Optional[FileStorage] = None


def get_file_storage() -> Optional[FileStorage]:
    """获取全局文件存储实例"""
    return _global_storage


def init_file_storage(db: Optional["DatabaseManager"] = None) -> FileStorage:
    """初始化全局文件存储"""
    global _global_storage
    _global_storage = FileStorage(db)
    return _global_storage


# ── process_file_inputs ──────────────────────────────────

async def process_file_inputs(
    input_data: dict,
    workflow_inputs: Optional[list] = None,
) -> dict:
    """处理输入数据中的文件字段，将 base64 数据保存为本地文件"""
    storage = get_file_storage()
    if not storage:
        storage = FileStorage()
        logger.debug("使用临时 FileStorage 实例")

    result = input_data.copy()

    file_fields = set()
    if workflow_inputs:
        for inp in workflow_inputs:
            if hasattr(inp, "type"):
                type_name = (
                    inp.type.__name__ if hasattr(inp.type, "__name__") else str(inp.type)
                )
                if type_name in ("Image", "File", "Audio", "Files"):
                    file_fields.add(inp.name)

    for key, value in input_data.items():
        if not value:
            continue

        is_file_field = key in file_fields
        is_base64_data = isinstance(value, str) and (
            value.startswith("data:") or _looks_like_base64(value)
        )

        if is_file_field or is_base64_data:
            if isinstance(value, str) and (value.startswith("data:") or _looks_like_base64(value)):
                try:
                    stored = await storage.save_base64(value, filename=key)
                    result[key] = stored.file_path
                except Exception as e:
                    logger.warning(f"保存文件字段 '{key}' 失败: {e}")
            elif isinstance(value, list):
                paths = []
                for i, item in enumerate(value):
                    if isinstance(item, str) and (item.startswith("data:") or _looks_like_base64(item)):
                        try:
                            stored = await storage.save_base64(item, filename=f"{key}_{i}")
                            paths.append(stored.file_path)
                        except Exception as e:
                            logger.warning(f"保存文件列表项 '{key}[{i}]' 失败: {e}")
                            paths.append(item)
                    else:
                        paths.append(item)
                result[key] = paths

    return result


def _looks_like_base64(s: str) -> bool:
    if not s or len(s) < 100:
        return False
    import re
    if not re.match(r'^[A-Za-z0-9+/=]+$', s[:1000]):
        return False
    return len(s) > 500
