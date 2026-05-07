"""
知识库服务层
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentclaw.config import KnowledgeBaseConfig
from agentclaw.knowledgebase.backend import KnowledgeRetrievalBackend
from agentclaw.knowledgebase.model_gateway import KnowledgeBaseModelGateway
from agentclaw.knowledgebase.models import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    SearchHit,
    SearchResult,
)
from agentclaw.knowledgebase.parser import DocumentParseError, MarkItDownParser
from agentclaw.knowledgebase.splitter import TextChunker
from agentclaw.knowledgebase.storage import KnowledgeBaseStorage
from agentclaw.knowledgebase.store import KnowledgeBaseStore
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class KnowledgeBaseService:
    """知识库核心服务。"""

    def __init__(
        self,
        *,
        store: KnowledgeBaseStore,
        storage: KnowledgeBaseStorage,
        parser: MarkItDownParser,
        model_gateway: KnowledgeBaseModelGateway,
        retrieval_backend: KnowledgeRetrievalBackend,
        config: KnowledgeBaseConfig,
    ):
        self.store = store
        self.storage = storage
        self.parser = parser
        self.model_gateway = model_gateway
        self.retrieval_backend = retrieval_backend
        self.config = config

    async def init(self) -> None:
        await self.store.init()

    async def list_knowledgebases(self) -> List[KnowledgeBaseRecord]:
        return await self.store.list_knowledgebases()

    async def create_knowledgebase(
        self,
        *,
        name: str,
        description: str = "",
        embedding_model_id: str = "",
        rerank_model_id: Optional[str] = None,
        llm_model_id: str = "",
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        is_default: bool = False,
        retrieval_config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeBaseRecord:
        kb_id = uuid.uuid4().hex
        record = KnowledgeBaseRecord(
            id=kb_id,
            name=name.strip(),
            description=description.strip(),
            embedding_model_id=(embedding_model_id or self.model_gateway.get_default_model_id("embedding")).strip(),
            rerank_model_id=(
                self.model_gateway.get_default_model_id("rerank")
                if rerank_model_id is None
                else str(rerank_model_id)
            ).strip(),
            llm_model_id=(llm_model_id or self.model_gateway.get_default_model_id("llm")).strip(),
            chunk_size=int(chunk_size or self.config.chunk_size),
            chunk_overlap=int(chunk_overlap if chunk_overlap is not None else self.config.chunk_overlap),
            is_default=is_default,
            vector_collection=self._build_collection_name(name=name, knowledgebase_id=kb_id),
            retrieval_config={**self._default_retrieval_config(), **(retrieval_config or {})},
            metadata=metadata or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        return await self.store.create_knowledgebase(record)

    async def get_knowledgebase(self, knowledgebase_id: str) -> Optional[KnowledgeBaseRecord]:
        return await self.store.get_knowledgebase(knowledgebase_id)

    async def update_knowledgebase(self, knowledgebase_id: str, updates: Dict[str, Any]) -> Optional[KnowledgeBaseRecord]:
        payload = dict(updates)
        if "name" in payload:
            payload["name"] = str(payload["name"]).strip()
        if "description" in payload:
            payload["description"] = str(payload["description"]).strip()
        return await self.store.update_knowledgebase(knowledgebase_id, payload)

    async def delete_knowledgebase(self, knowledgebase_id: str) -> bool:
        kb = await self.store.get_knowledgebase(knowledgebase_id)
        if not kb:
            return False
        for document in await self.store.list_documents(knowledgebase_id):
            await self.storage.delete_document_assets(document.stored_path, document.parsed_path)
        try:
            self.retrieval_backend.drop_collection(knowledgebase=kb)
        except Exception as exc:
            logger.warning(f"删除知识库向量集合失败: {exc}")
        return await self.store.delete_knowledgebase(knowledgebase_id)

    async def list_documents(self, knowledgebase_id: str) -> List[KnowledgeDocumentRecord]:
        return await self.store.list_documents(knowledgebase_id)

    async def get_document(self, knowledgebase_id: str, document_id: str) -> Optional[KnowledgeDocumentRecord]:
        document = await self.store.get_document(document_id)
        if not document or document.knowledgebase_id != knowledgebase_id:
            return None
        return document

    async def list_chunks(self, knowledgebase_id: str, document_id: str) -> List[KnowledgeChunkRecord]:
        document = await self.get_document(knowledgebase_id, document_id)
        if document is None:
            raise FileNotFoundError(f"文档不存在: {document_id}")
        return await self.store.list_chunks(document_id)

    async def upload_document(
        self,
        *,
        knowledgebase_id: str,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        index_now: bool = True,
    ) -> KnowledgeDocumentRecord:
        kb = await self._require_knowledgebase(knowledgebase_id)
        stored = await self.storage.save_document(
            knowledgebase_id=knowledgebase_id,
            data=data,
            filename=filename,
            mime_type=mime_type,
        )

        document = KnowledgeDocumentRecord(
            id=uuid.uuid4().hex,
            knowledgebase_id=knowledgebase_id,
            original_name=stored.original_name,
            stored_path=stored.stored_path,
            mime_type=stored.mime_type,
            size=stored.size,
            file_hash=stored.file_hash,
            status="processing",
            metadata=metadata or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.store.create_document(document)

        if not index_now:
            return document

        return await self._index_document_with_failure_status(
            kb,
            document,
            failure_log_message="知识库文档入库失败",
        )

    async def process_document(self, document_id: str) -> Optional[KnowledgeDocumentRecord]:
        """Run parser/chunking/vector indexing for an already-created document."""
        document = await self.store.get_document(document_id)
        if not document:
            logger.warning(f"知识库文档后台入库跳过：文档不存在 {document_id}")
            return None
        kb = await self._require_knowledgebase(document.knowledgebase_id)
        processing = await self.store.update_document(
            document.id,
            {
                "status": "processing",
                "error": "",
            },
        )
        return await self._index_document_with_failure_status(
            kb,
            processing or document,
            failure_log_message="知识库文档后台入库失败",
        )

    async def import_local_document(
        self,
        *,
        knowledgebase_id: str,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocumentRecord:
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        data = path.read_bytes()
        return await self.upload_document(
            knowledgebase_id=knowledgebase_id,
            data=data,
            filename=path.name,
            mime_type=None,
            metadata={"import_path": str(path), **(metadata or {})},
        )

    async def reindex_document(self, document_id: str) -> KnowledgeDocumentRecord:
        document = await self.store.get_document(document_id)
        if not document:
            raise FileNotFoundError(f"文档不存在: {document_id}")
        kb = await self._require_knowledgebase(document.knowledgebase_id)
        processing = await self.store.update_document(document.id, {"status": "processing", "error": ""})
        return await self._index_document_with_failure_status(
            kb,
            processing or document,
            failure_log_message="知识库文档重新入库失败",
        )

    async def replace_document(
        self,
        *,
        knowledgebase_id: str,
        document_id: str,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocumentRecord:
        kb = await self._require_knowledgebase(knowledgebase_id)
        document = await self.store.get_document(document_id)
        if not document or document.knowledgebase_id != kb.id:
            raise FileNotFoundError(f"文档不存在: {document_id}")

        stored = await self.storage.save_document(
            knowledgebase_id=knowledgebase_id,
            data=data,
            filename=filename,
            mime_type=mime_type,
        )
        old_stored_path = document.stored_path
        old_parsed_path = document.parsed_path
        updated = await self.store.update_document(
            document.id,
            {
                "original_name": stored.original_name,
                "stored_path": stored.stored_path,
                "parsed_path": "",
                "parsed_text": "",
                "mime_type": stored.mime_type,
                "size": stored.size,
                "file_hash": stored.file_hash,
                "status": "processing",
                "parser_name": document.parser_name,
                "error": "",
                "metadata": {**document.metadata, **(metadata or {})},
            },
        )
        if updated is None:
            raise RuntimeError("替换文档失败：无法更新文档记录")

        result = await self._index_document_with_failure_status(
            kb,
            updated,
            failure_log_message="知识库文档替换失败",
        )
        if result.status != "ready":
            return result

        cleanup_stored_path = old_stored_path if old_stored_path != result.stored_path else ""
        cleanup_parsed_path = old_parsed_path if old_parsed_path != result.parsed_path else ""
        await self.storage.delete_document_assets(cleanup_stored_path, cleanup_parsed_path)
        return result

    async def delete_document(self, knowledgebase_id: str, document_id: str) -> bool:
        kb = await self._require_knowledgebase(knowledgebase_id)
        document = await self.store.get_document(document_id)
        if not document or document.knowledgebase_id != kb.id:
            return False

        try:
            chunk_ids = await self.store.get_document_chunk_ids(document_id)
            if chunk_ids:
                self.retrieval_backend.delete_chunks(knowledgebase=kb, chunk_ids=chunk_ids)
        except Exception as exc:
            logger.warning(f"删除知识库向量失败: {exc}")

        await self.storage.delete_document_assets(document.stored_path, document.parsed_path)
        return await self.store.delete_document(document_id)

    async def create_chunk(
        self,
        *,
        knowledgebase_id: str,
        document_id: str,
        content: str,
        chunk_index: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeChunkRecord:
        document = await self.get_document(knowledgebase_id, document_id)
        if document is None:
            raise FileNotFoundError(f"文档不存在: {document_id}")
        existing = await self.store.list_chunks(document_id)
        next_index = max((item.chunk_index for item in existing), default=-1) + 1 if chunk_index is None else int(chunk_index)
        record = KnowledgeChunkRecord(
            id=uuid.uuid4().hex,
            knowledgebase_id=knowledgebase_id,
            document_id=document_id,
            chunk_index=next_index,
            content=(content or "").strip(),
            token_count=self._estimate_token_count(content),
            metadata=metadata or {},
            created_at=datetime.utcnow(),
        )
        await self.store.create_chunk(record)
        await self._sync_document_chunks(knowledgebase_id, document_id)
        updated = await self.store.get_chunk(record.id)
        if updated is None:
            raise RuntimeError("创建分块后读取失败")
        return updated

    async def update_chunk(
        self,
        *,
        knowledgebase_id: str,
        document_id: str,
        chunk_id: str,
        updates: Dict[str, Any],
    ) -> Optional[KnowledgeChunkRecord]:
        document = await self.get_document(knowledgebase_id, document_id)
        if document is None:
            raise FileNotFoundError(f"文档不存在: {document_id}")
        chunk = await self.store.get_chunk(chunk_id)
        if chunk is None or chunk.document_id != document_id:
            return None
        payload = dict(updates)
        if "content" in payload and payload["content"] is not None:
            payload["content"] = str(payload["content"]).strip()
            payload["token_count"] = self._estimate_token_count(payload["content"])
        updated = await self.store.update_chunk(chunk_id, payload)
        await self._sync_document_chunks(knowledgebase_id, document_id)
        return updated

    async def delete_chunk(self, *, knowledgebase_id: str, document_id: str, chunk_id: str) -> bool:
        document = await self.get_document(knowledgebase_id, document_id)
        if document is None:
            raise FileNotFoundError(f"文档不存在: {document_id}")
        chunk = await self.store.get_chunk(chunk_id)
        if chunk is None or chunk.document_id != document_id:
            return False
        ok = await self.store.delete_chunk(chunk_id)
        if ok:
            await self._sync_document_chunks(knowledgebase_id, document_id)
        return ok

    async def search(
        self,
        *,
        query: str,
        knowledgebase_id: str = "",
        top_k: Optional[int] = None,
        mode: Optional[str] = None,
        score_threshold: Optional[float] = None,
        rerank_model_id: Optional[str] = None,
        prefer_builtin_hybrid: Optional[bool] = None,
    ) -> SearchResult:
        kb = await self._resolve_search_knowledgebase(knowledgebase_id)
        query_text = (query or "").strip()
        if not query_text:
            return SearchResult(query=query, knowledgebase_id=kb.id, hits=[], total=0, strategy="empty")

        # Allow caller to override rerank model (e.g. admin search test panel)
        effective_rerank_model_id = kb.rerank_model_id
        if rerank_model_id is not None:
            effective_rerank_model_id = rerank_model_id

        limit = int(top_k or self.config.default_top_k)
        candidate_limit = self._candidate_limit_for_search(kb, limit) if effective_rerank_model_id else limit

        # Allow caller to override search params
        search_overrides: Dict[str, Any] = {}
        if prefer_builtin_hybrid is not None:
            search_overrides["prefer_builtin_hybrid"] = prefer_builtin_hybrid
        if mode is not None:
            search_overrides["mode"] = mode

        execution = await self.retrieval_backend.search(
            knowledgebase=kb,
            query=query_text,
            limit=candidate_limit,
            embed_query=self._embed_query,
            keyword_search=self.store.keyword_search,
            overrides=search_overrides,
        )
        candidate_ids = [item.chunk_id for item in execution.candidates]
        chunk_map = await self.store.get_chunks_by_ids(candidate_ids)

        merged: List[SearchHit] = []
        for item in execution.candidates:
            chunk = chunk_map.get(item.chunk_id)
            if not chunk:
                continue
            merged.append(
                SearchHit(
                    chunk_id=item.chunk_id,
                    document_id=chunk["document_id"],
                    document_name=chunk["document_name"],
                    chunk_index=int(chunk["chunk_index"]),
                    content=chunk["content"],
                    score=float(item.score),
                    dense_score=float(item.dense_score),
                    keyword_score=float(item.keyword_score),
                    rerank_score=float(item.rerank_score) if item.rerank_score is not None else None,
                    source_path=chunk["stored_path"],
                    metadata=chunk.get("metadata", {}),
                )
            )

        strategy = execution.strategy
        rerank_applied = False
        if effective_rerank_model_id and merged:
            merged, rerank_applied = await self._rerank_hits(
                rerank_model_id=effective_rerank_model_id,
                query=query_text,
                hits=merged,
                limit=limit,
            )
            if rerank_applied:
                strategy = f"{strategy}+rerank"
        else:
            merged = merged[:limit]

        merged = self._apply_score_threshold(kb, merged, score_threshold_override=score_threshold)

        return SearchResult(
            query=query_text,
            knowledgebase_id=kb.id,
            hits=merged,
            total=len(merged),
            strategy=strategy,
            rerank_applied=rerank_applied,
        )

    async def _index_document(
        self,
        kb: KnowledgeBaseRecord,
        document: KnowledgeDocumentRecord,
    ) -> KnowledgeDocumentRecord:
        document = await self._migrate_legacy_document_stored_path(kb, document)
        # 获取本地路径供 parser 使用（兼容旧数据绝对路径和新数据 storage key）
        from agentclaw.database.file_storage import get_file_storage
        file_storage = get_file_storage()
        if file_storage and not Path(document.stored_path).is_absolute():
            local_path = await file_storage.get_local_path_by_key(document.stored_path)
        else:
            from agentclaw.database.file_storage import resolve_allowed_legacy_file_path

            safe_path = resolve_allowed_legacy_file_path(document.stored_path)
            local_path = str(safe_path) if safe_path else None
        if not local_path:
            raise FileNotFoundError(f"无法获取文档本地路径: {document.stored_path}")

        parsed = await self.parser.parse(local_path, display_name=document.original_name)
        parsed_path = await self.storage.write_parsed_markdown(
            knowledgebase_id=kb.id,
            document_id=document.id,
            markdown=parsed.markdown,
        )

        chunker = TextChunker(chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap)
        chunk_payloads = chunker.split(parsed.text)
        if not chunk_payloads:
            raise RuntimeError("文档解析成功，但未生成可索引的文本块")

        vectors = await self.model_gateway.embed_texts(
            [chunk.content for chunk in chunk_payloads],
            model_id=kb.embedding_model_id,
        )
        if len(vectors) != len(chunk_payloads):
            raise RuntimeError("embedding 结果数量与 chunk 数量不一致")

        embedding_dim = len(vectors[0]) if vectors else None
        if embedding_dim is None:
            raise RuntimeError("embedding 返回为空")

        if kb.embedding_dim != embedding_dim:
            kb = await self.store.update_knowledgebase(kb.id, {"embedding_dim": embedding_dim}) or kb
        self.retrieval_backend.ensure_collection(knowledgebase=kb, dimension=embedding_dim)

        chunk_records: List[KnowledgeChunkRecord] = []
        vector_rows: List[Dict[str, Any]] = []
        for chunk_payload, vector in zip(chunk_payloads, vectors):
            chunk_id = uuid.uuid4().hex
            chunk_records.append(
                KnowledgeChunkRecord(
                    id=chunk_id,
                    knowledgebase_id=kb.id,
                    document_id=document.id,
                    chunk_index=chunk_payload.chunk_index,
                    content=chunk_payload.content,
                    token_count=chunk_payload.token_count,
                    metadata=chunk_payload.metadata,
                    created_at=datetime.utcnow(),
                )
            )
            vector_rows.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document.id,
                    "knowledgebase_id": kb.id,
                    "chunk_index": chunk_payload.chunk_index,
                    "content": chunk_payload.content,
                    "embedding": vector,
                }
            )

        existing_chunk_ids = await self.store.get_document_chunk_ids(document.id)
        if existing_chunk_ids:
            try:
                self.retrieval_backend.delete_chunks(knowledgebase=kb, chunk_ids=existing_chunk_ids)
            except Exception as exc:
                logger.warning(f"重建索引时删除旧向量失败: {exc}")

        await self.store.replace_document_chunks(
            knowledgebase_id=kb.id,
            document_id=document.id,
            chunks=chunk_records,
        )
        self.retrieval_backend.upsert_chunks(knowledgebase=kb, rows=vector_rows)

        updated = await self.store.update_document(
            document.id,
            {
                "parsed_path": parsed_path,
                "parsed_text": parsed.text,
                "parser_name": parsed.parser_name,
                "status": "ready",
                "chunk_count": len(chunk_records),
                "error": "",
                "indexed_at": datetime.utcnow(),
                "metadata": {**document.metadata, **parsed.metadata},
            },
        )
        if updated is None:
            raise RuntimeError("文档索引完成后更新状态失败")
        return updated

    async def _index_document_with_failure_status(
        self,
        kb: KnowledgeBaseRecord,
        document: KnowledgeDocumentRecord,
        *,
        failure_log_message: str,
    ) -> KnowledgeDocumentRecord:
        try:
            return await self._index_document(kb, document)
        except DocumentParseError as exc:
            logger.warning(f"知识库文档解析失败: {exc}")
            return await self._mark_document_failed(document.id, str(exc))
        except Exception as exc:
            logger.exception(failure_log_message)
            return await self._mark_document_failed(document.id, str(exc))

    async def _mark_document_failed(self, document_id: str, error: str) -> KnowledgeDocumentRecord:
        failed = await self.store.update_document(
            document_id,
            {
                "status": "failed",
                "error": error,
            },
        )
        if failed is None:
            raise RuntimeError(f"文档失败状态写入失败：文档不存在 {document_id}")
        return failed

    async def _migrate_legacy_document_stored_path(
        self,
        kb: KnowledgeBaseRecord,
        document: KnowledgeDocumentRecord,
    ) -> KnowledgeDocumentRecord:
        """Copy an allowed legacy local document path into FileStorage and store its key."""
        if not Path(document.stored_path).is_absolute():
            return document

        from agentclaw.database.file_storage import get_file_storage, resolve_allowed_legacy_file_path

        file_storage = get_file_storage()
        safe_path = resolve_allowed_legacy_file_path(document.stored_path)
        if not file_storage or not safe_path or not safe_path.exists() or not safe_path.is_file():
            return document

        data = safe_path.read_bytes()
        stored = await file_storage.save_with_prefix(
            data,
            document.original_name or safe_path.name,
            prefix=f"knowledgebase/{kb.id}",
            mime_type=document.mime_type,
        )
        updated = await self.store.update_document(
            document.id,
            {
                "stored_path": stored.file_path,
                "file_hash": stored.file_hash,
                "mime_type": stored.mime_type,
                "size": stored.size,
            },
        )
        return updated or replace(
            document,
            stored_path=stored.file_path,
            file_hash=stored.file_hash,
            mime_type=stored.mime_type,
            size=stored.size,
        )

    async def _sync_document_chunks(self, knowledgebase_id: str, document_id: str) -> None:
        kb = await self._require_knowledgebase(knowledgebase_id)
        document = await self.store.get_document(document_id)
        if document is None or document.knowledgebase_id != knowledgebase_id:
            raise FileNotFoundError(f"文档不存在: {document_id}")

        chunks = await self.store.list_chunks(document_id)
        existing_chunk_ids = await self.store.get_document_chunk_ids(document_id)
        if existing_chunk_ids:
            try:
                self.retrieval_backend.delete_chunks(knowledgebase=kb, chunk_ids=existing_chunk_ids)
            except Exception as exc:
                logger.warning(f"同步文档分块时删除旧向量失败: {exc}")

        if chunks:
            vectors = await self.model_gateway.embed_texts(
                [chunk.content for chunk in chunks],
                model_id=kb.embedding_model_id,
            )
            embedding_dim = len(vectors[0]) if vectors else None
            if embedding_dim:
                if kb.embedding_dim != embedding_dim:
                    kb = await self.store.update_knowledgebase(kb.id, {"embedding_dim": embedding_dim}) or kb
                self.retrieval_backend.ensure_collection(knowledgebase=kb, dimension=embedding_dim)
                rows = []
                for chunk, vector in zip(chunks, vectors):
                    rows.append(
                        {
                            "chunk_id": chunk.id,
                            "document_id": document_id,
                            "knowledgebase_id": knowledgebase_id,
                            "chunk_index": chunk.chunk_index,
                            "content": chunk.content,
                            "embedding": vector,
                        }
                    )
                self.retrieval_backend.upsert_chunks(knowledgebase=kb, rows=rows)

        await self.store.update_document(document_id, {"chunk_count": len(chunks), "indexed_at": datetime.utcnow()})

    async def _resolve_search_knowledgebase(self, knowledgebase_id: str) -> KnowledgeBaseRecord:
        if knowledgebase_id:
            return await self._require_knowledgebase(knowledgebase_id)

        if self.config.default_knowledgebase_id:
            kb = await self.store.get_knowledgebase(self.config.default_knowledgebase_id)
            if kb:
                return kb

        default_kb = await self.store.get_default_knowledgebase()
        if default_kb:
            return default_kb

        knowledgebases = await self.store.list_knowledgebases()
        if knowledgebases:
            return knowledgebases[0]
        raise RuntimeError("当前没有可用的知识库")

    async def _require_knowledgebase(self, knowledgebase_id: str) -> KnowledgeBaseRecord:
        kb = await self.store.get_knowledgebase(knowledgebase_id)
        if kb is None:
            raise FileNotFoundError(f"知识库不存在: {knowledgebase_id}")
        return kb

    async def _embed_query(self, query: str, model_id: str) -> List[float]:
        vectors = await self.model_gateway.embed_texts([query], model_id=model_id)
        return list(vectors[0]) if vectors else []

    async def _rerank_hits(
        self,
        *,
        rerank_model_id: str,
        query: str,
        hits: List[SearchHit],
        limit: int,
    ) -> tuple[List[SearchHit], bool]:
        if not rerank_model_id or not hits:
            return hits[:limit], False

        try:
            ranked = await self.model_gateway.rerank_texts(
                query=query,
                texts=[hit.content for hit in hits],
                model_id=rerank_model_id,
                top_n=min(limit, len(hits)),
            )
        except Exception as exc:
            logger.warning(f"知识库 rerank 执行失败，回退原始排序: {exc}")
            return hits[:limit], False

        reranked_hits: List[SearchHit] = []
        used_indexes = set()
        for item in ranked:
            index = int(item.get("index", -1))
            if index < 0 or index >= len(hits) or index in used_indexes:
                continue
            used_indexes.add(index)
            reranked_hits.append(hits[index])

        if not reranked_hits:
            return hits[:limit], False

        for index, hit in enumerate(hits):
            if len(reranked_hits) >= limit:
                break
            if index in used_indexes:
                continue
            reranked_hits.append(hit)

        return reranked_hits[:limit], True

    def _candidate_limit_for_search(self, kb: KnowledgeBaseRecord, limit: int) -> int:
        """Calculate expanded candidate limit for rerank. Caller must ensure rerank is needed."""
        multiplier = int(
            (kb.retrieval_config or {}).get(
                "rerank_candidate_multiplier",
                self.config.rerank_candidate_multiplier,
            ) or 1
        )
        return max(limit, limit * max(multiplier, 1))

    def _apply_score_threshold(
        self,
        kb: KnowledgeBaseRecord,
        hits: List[SearchHit],
        *,
        score_threshold_override: Optional[float] = None,
    ) -> List[SearchHit]:
        # Caller override takes precedence over KB config
        if score_threshold_override is not None:
            threshold = score_threshold_override
        else:
            threshold = self._score_threshold(kb)
        if threshold is None:
            return hits

        return [hit for hit in hits if float(hit.score) >= threshold]

    def _score_threshold(self, kb: KnowledgeBaseRecord) -> Optional[float]:
        raw_value = (kb.retrieval_config or {}).get("score_threshold")
        if raw_value in (None, "", False):
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            logger.warning(f"知识库 score_threshold 配置无效，已忽略: {raw_value}")
            return None

    def _build_collection_name(self, *, name: str, knowledgebase_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()) or "knowledgebase"
        kb_suffix = knowledgebase_id.replace("-", "_")[:16]
        return f"{self.config.milvus_collection_prefix}_{slug}_{kb_suffix}"

    def _estimate_token_count(self, content: str) -> int:
        text = (content or "").strip()
        if not text:
            return 0
        return max(1, len(text.split()))

    def _default_retrieval_config(self) -> Dict[str, Any]:
        return {
            "backend": self.config.backend,
            "mode": self.config.default_retrieval_mode,
            "prefer_builtin_hybrid": self.config.prefer_builtin_hybrid,
            "dense_candidate_multiplier": self.config.dense_candidate_multiplier,
            "keyword_candidate_multiplier": self.config.keyword_candidate_multiplier,
            "rerank_candidate_multiplier": self.config.rerank_candidate_multiplier,
        }
