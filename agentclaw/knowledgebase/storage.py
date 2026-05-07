"""
知识库文件存储

文档文件委托给统一 FileStorage 管理（支持本地/MinIO）。
解析后的 Markdown 缓存仍存本地。
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


@dataclass
class StoredKnowledgeFile:
    original_name: str
    stored_path: str      # storage key 或旧数据的绝对路径
    mime_type: str
    size: int
    file_hash: str
    file_id: str = ""     # 对应 files 表的 ID


class KnowledgeBaseStorage:
    """知识库文件存储。"""

    def __init__(self, root_dir: Path, parsed_dir: Path):
        self.root_dir = root_dir
        self.parsed_dir = parsed_dir
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

    async def save_document(
        self,
        *,
        knowledgebase_id: str,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> StoredKnowledgeFile:
        from agentclaw.database.file_storage import get_file_storage

        file_storage = get_file_storage()

        if file_storage:
            stored = await file_storage.save_with_prefix(
                data, filename,
                prefix=f"knowledgebase/{knowledgebase_id}",
                mime_type=mime_type,
            )
            return StoredKnowledgeFile(
                original_name=stored.original_name,
                stored_path=stored.file_path,
                mime_type=stored.mime_type,
                size=stored.size,
                file_hash=stored.file_hash,
                file_id=stored.id,
            )

        # Fallback：无 FileStorage 时直接写本地
        kb_dir = self.root_dir / knowledgebase_id
        kb_dir.mkdir(parents=True, exist_ok=True)

        file_hash = hashlib.sha256(data).hexdigest()
        suffix = Path(filename).suffix.lower()
        safe_name = f"{file_hash}{suffix}"
        stored_path = kb_dir / safe_name
        stored_path.write_bytes(data)

        if not mime_type:
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        return StoredKnowledgeFile(
            original_name=filename,
            stored_path=str(stored_path),
            mime_type=mime_type,
            size=len(data),
            file_hash=file_hash,
        )

    async def write_parsed_markdown(
        self,
        *,
        knowledgebase_id: str,
        document_id: str,
        markdown: str,
    ) -> str:
        kb_dir = self.parsed_dir / knowledgebase_id
        kb_dir.mkdir(parents=True, exist_ok=True)
        target = kb_dir / f"{document_id}.md"
        target.write_text(markdown, encoding="utf-8")
        return str(target)

    async def delete_document_assets(self, stored_path: str, parsed_path: str = "") -> None:
        from agentclaw.database.file_storage import get_file_storage

        file_storage = get_file_storage()

        if stored_path:
            if file_storage and not Path(stored_path).is_absolute():
                await file_storage.delete_by_key(stored_path)
            else:
                from agentclaw.database.file_storage import resolve_allowed_legacy_file_path

                safe_path = resolve_allowed_legacy_file_path(stored_path) if Path(stored_path).is_absolute() else None
                if safe_path:
                    safe_path.unlink(missing_ok=True)

        if parsed_path:
            from agentclaw.database.file_storage import resolve_allowed_legacy_file_path

            safe_parsed_path = resolve_allowed_legacy_file_path(parsed_path) if Path(parsed_path).is_absolute() else None
            if safe_parsed_path:
                safe_parsed_path.unlink(missing_ok=True)
