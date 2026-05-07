"""
知识库 PostgreSQL 存储
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from agentclaw.knowledgebase.models import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    SearchLogRecord,
)
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class KnowledgeBaseStore:
    """知识库 PostgreSQL 存储。"""

    def __init__(self, pg_pool):
        self._pool = pg_pool

    async def init(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(128) UNIQUE NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    embedding_model_id VARCHAR(128) NOT NULL DEFAULT '',
                    rerank_model_id VARCHAR(128) NOT NULL DEFAULT '',
                    llm_model_id VARCHAR(128) NOT NULL DEFAULT '',
                    chunk_size INTEGER NOT NULL DEFAULT 1200,
                    chunk_overlap INTEGER NOT NULL DEFAULT 200,
                    is_default BOOLEAN NOT NULL DEFAULT FALSE,
                    vector_collection VARCHAR(256) NOT NULL DEFAULT '',
                    embedding_dim INTEGER,
                    retrieval_config JSONB NOT NULL DEFAULT '{}'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_bases_default
                ON knowledge_bases (is_default)
                WHERE is_default = TRUE
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id VARCHAR(64) PRIMARY KEY,
                    knowledgebase_id VARCHAR(64) NOT NULL,
                    original_name VARCHAR(500) NOT NULL,
                    stored_path VARCHAR(1000) NOT NULL,
                    parsed_path VARCHAR(1000) NOT NULL DEFAULT '',
                    parsed_text TEXT NOT NULL DEFAULT '',
                    mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
                    size BIGINT NOT NULL DEFAULT 0,
                    file_hash VARCHAR(64) NOT NULL DEFAULT '',
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    parser_name VARCHAR(64) NOT NULL DEFAULT 'markitdown',
                    error TEXT NOT NULL DEFAULT '',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    indexed_at TIMESTAMPTZ
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb
                ON knowledge_documents (knowledgebase_id, created_at DESC)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id VARCHAR(64) PRIMARY KEY,
                    knowledgebase_id VARCHAR(64) NOT NULL,
                    document_id VARCHAR(64) NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(document_id, chunk_index)
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_kb
                ON knowledge_chunks (knowledgebase_id, document_id, chunk_index)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_fts
                ON knowledge_chunks
                USING GIN (to_tsvector('simple', content))
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_search_logs (
                    id VARCHAR(64) PRIMARY KEY,
                    knowledgebase_id VARCHAR(64) NOT NULL,
                    query TEXT NOT NULL,
                    mode VARCHAR(32) NOT NULL DEFAULT '',
                    strategy VARCHAR(64) NOT NULL DEFAULT '',
                    top_k INTEGER NOT NULL DEFAULT 8,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    hits JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_search_logs_kb
                ON knowledge_search_logs (knowledgebase_id, created_at DESC)
                """
            )
        logger.info("KnowledgeBase tables initialized")

    async def list_knowledgebases(self) -> List[KnowledgeBaseRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM knowledge_bases ORDER BY is_default DESC, created_at ASC")
        return [self._row_to_kb(row) for row in rows]

    async def get_knowledgebase(self, knowledgebase_id: str) -> Optional[KnowledgeBaseRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM knowledge_bases WHERE id = $1", knowledgebase_id)
        return self._row_to_kb(row) if row else None

    async def get_default_knowledgebase(self) -> Optional[KnowledgeBaseRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM knowledge_bases WHERE is_default = TRUE LIMIT 1")
        return self._row_to_kb(row) if row else None

    async def get_knowledgebase_stats(self, knowledgebase_id: str) -> Dict[str, int]:
        async with self._pool.acquire() as conn:
            document_count = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge_documents WHERE knowledgebase_id = $1",
                knowledgebase_id,
            )
            chunk_count = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE knowledgebase_id = $1",
                knowledgebase_id,
            )
        return {
            "document_count": int(document_count or 0),
            "chunk_count": int(chunk_count or 0),
        }

    async def create_knowledgebase(self, record: KnowledgeBaseRecord) -> KnowledgeBaseRecord:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if record.is_default:
                    await conn.execute("UPDATE knowledge_bases SET is_default = FALSE WHERE is_default = TRUE")
                await conn.execute(
                    """
                    INSERT INTO knowledge_bases (
                        id, name, description, embedding_model_id, rerank_model_id, llm_model_id,
                        chunk_size, chunk_overlap, is_default, vector_collection, embedding_dim,
                        retrieval_config, metadata, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7, $8, $9, $10, $11,
                        $12, $13, $14, $15
                    )
                    """,
                    record.id,
                    record.name,
                    record.description,
                    record.embedding_model_id,
                    record.rerank_model_id,
                    record.llm_model_id,
                    record.chunk_size,
                    record.chunk_overlap,
                    record.is_default,
                    record.vector_collection,
                    record.embedding_dim,
                    json.dumps(record.retrieval_config, ensure_ascii=False),
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.created_at or datetime.utcnow(),
                    record.updated_at or datetime.utcnow(),
                )
        return record

    async def update_knowledgebase(self, knowledgebase_id: str, updates: Dict[str, Any]) -> Optional[KnowledgeBaseRecord]:
        if not updates:
            return await self.get_knowledgebase(knowledgebase_id)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if updates.get("is_default"):
                    await conn.execute("UPDATE knowledge_bases SET is_default = FALSE WHERE is_default = TRUE AND id <> $1", knowledgebase_id)

                params: List[Any] = []
                set_clauses: List[str] = []
                idx = 1
                for field in (
                    "name",
                    "description",
                    "embedding_model_id",
                    "rerank_model_id",
                    "llm_model_id",
                    "chunk_size",
                    "chunk_overlap",
                    "is_default",
                    "vector_collection",
                    "embedding_dim",
                ):
                    if field in updates:
                        set_clauses.append(f"{field} = ${idx}")
                        params.append(updates[field])
                        idx += 1

                for field in ("retrieval_config", "metadata"):
                    if field in updates:
                        set_clauses.append(f"{field} = ${idx}")
                        params.append(json.dumps(updates[field], ensure_ascii=False))
                        idx += 1

                set_clauses.append(f"updated_at = ${idx}")
                params.append(datetime.utcnow())
                idx += 1
                params.append(knowledgebase_id)

                await conn.execute(
                    f"UPDATE knowledge_bases SET {', '.join(set_clauses)} WHERE id = ${idx}",
                    *params,
                )

        return await self.get_knowledgebase(knowledgebase_id)

    async def delete_knowledgebase(self, knowledgebase_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM knowledge_search_logs WHERE knowledgebase_id = $1", knowledgebase_id)
                await conn.execute("DELETE FROM knowledge_chunks WHERE knowledgebase_id = $1", knowledgebase_id)
                await conn.execute("DELETE FROM knowledge_documents WHERE knowledgebase_id = $1", knowledgebase_id)
                result = await conn.execute("DELETE FROM knowledge_bases WHERE id = $1", knowledgebase_id)
        return result == "DELETE 1"

    async def create_document(self, record: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_documents (
                    id, knowledgebase_id, original_name, stored_path, parsed_path, parsed_text,
                    mime_type, size, file_hash, status, chunk_count, parser_name, error, metadata,
                    created_at, updated_at, indexed_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10, $11, $12, $13, $14,
                    $15, $16, $17
                )
                """,
                record.id,
                record.knowledgebase_id,
                record.original_name,
                record.stored_path,
                record.parsed_path,
                record.parsed_text,
                record.mime_type,
                record.size,
                record.file_hash,
                record.status,
                record.chunk_count,
                record.parser_name,
                record.error,
                json.dumps(record.metadata, ensure_ascii=False),
                record.created_at or datetime.utcnow(),
                record.updated_at or datetime.utcnow(),
                record.indexed_at,
            )
        return record

    async def get_document(self, document_id: str) -> Optional[KnowledgeDocumentRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM knowledge_documents WHERE id = $1", document_id)
        return self._row_to_document(row) if row else None

    async def list_documents(self, knowledgebase_id: str) -> List[KnowledgeDocumentRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM knowledge_documents WHERE knowledgebase_id = $1 ORDER BY created_at DESC",
                knowledgebase_id,
            )
        return [self._row_to_document(row) for row in rows]

    async def list_chunks(self, document_id: str) -> List[KnowledgeChunkRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM knowledge_chunks WHERE document_id = $1 ORDER BY chunk_index ASC, created_at ASC",
                document_id,
            )
        return [self._row_to_chunk(row) for row in rows]

    async def get_chunk(self, chunk_id: str) -> Optional[KnowledgeChunkRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM knowledge_chunks WHERE id = $1", chunk_id)
        return self._row_to_chunk(row) if row else None

    async def update_document(self, document_id: str, updates: Dict[str, Any]) -> Optional[KnowledgeDocumentRecord]:
        if not updates:
            return await self.get_document(document_id)

        params: List[Any] = []
        set_clauses: List[str] = []
        idx = 1
        for field in (
            "original_name",
            "stored_path",
            "parsed_path",
            "parsed_text",
            "mime_type",
            "size",
            "file_hash",
            "status",
            "chunk_count",
            "parser_name",
            "error",
            "indexed_at",
        ):
            if field in updates:
                set_clauses.append(f"{field} = ${idx}")
                params.append(updates[field])
                idx += 1

        if "metadata" in updates:
            set_clauses.append(f"metadata = ${idx}")
            params.append(json.dumps(updates["metadata"], ensure_ascii=False))
            idx += 1

        set_clauses.append(f"updated_at = ${idx}")
        params.append(datetime.utcnow())
        idx += 1
        params.append(document_id)

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE knowledge_documents SET {', '.join(set_clauses)} WHERE id = ${idx}",
                *params,
            )

        return await self.get_document(document_id)

    async def delete_document(self, document_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM knowledge_chunks WHERE document_id = $1", document_id)
                result = await conn.execute("DELETE FROM knowledge_documents WHERE id = $1", document_id)
        return result == "DELETE 1"

    async def replace_document_chunks(
        self,
        *,
        knowledgebase_id: str,
        document_id: str,
        chunks: List[KnowledgeChunkRecord],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM knowledge_chunks WHERE document_id = $1", document_id)
                for chunk in chunks:
                    await conn.execute(
                        """
                        INSERT INTO knowledge_chunks (
                            id, knowledgebase_id, document_id, chunk_index, content,
                            token_count, metadata, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        chunk.id,
                        knowledgebase_id,
                        document_id,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.token_count,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.created_at or datetime.utcnow(),
                    )

    async def create_chunk(self, record: KnowledgeChunkRecord) -> KnowledgeChunkRecord:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_chunks (
                    id, knowledgebase_id, document_id, chunk_index, content,
                    token_count, metadata, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                record.id,
                record.knowledgebase_id,
                record.document_id,
                record.chunk_index,
                record.content,
                record.token_count,
                json.dumps(record.metadata, ensure_ascii=False),
                record.created_at or datetime.utcnow(),
            )
        return record

    async def update_chunk(self, chunk_id: str, updates: Dict[str, Any]) -> Optional[KnowledgeChunkRecord]:
        if not updates:
            return await self.get_chunk(chunk_id)

        params: List[Any] = []
        set_clauses: List[str] = []
        idx = 1
        for field in ("chunk_index", "content", "token_count"):
            if field in updates:
                set_clauses.append(f"{field} = ${idx}")
                params.append(updates[field])
                idx += 1
        if "metadata" in updates:
            set_clauses.append(f"metadata = ${idx}")
            params.append(json.dumps(updates["metadata"], ensure_ascii=False))
            idx += 1
        params.append(chunk_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE knowledge_chunks SET {', '.join(set_clauses)} WHERE id = ${idx}",
                *params,
            )
        return await self.get_chunk(chunk_id)

    async def delete_chunk(self, chunk_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM knowledge_chunks WHERE id = $1", chunk_id)
        return result == "DELETE 1"

    async def get_document_chunk_ids(self, document_id: str) -> List[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM knowledge_chunks WHERE document_id = $1 ORDER BY chunk_index ASC", document_id)
        return [str(row["id"]) for row in rows]

    async def get_chunks_by_ids(self, chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not chunk_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.*, d.original_name, d.stored_path
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE c.id = ANY($1::varchar[])
                """,
                chunk_ids,
            )
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            result[str(row["id"])] = {
                "chunk_id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "knowledgebase_id": str(row["knowledgebase_id"]),
                "chunk_index": int(row["chunk_index"]),
                "content": row["content"],
                "token_count": int(row["token_count"] or 0),
                "metadata": self._coerce_json_object(row["metadata"], field_name="metadata"),
                "document_name": row["original_name"],
                "stored_path": row["stored_path"],
            }
        return result

    async def keyword_search(self, knowledgebase_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        async with self._pool.acquire() as conn:
            # Primary: tsvector full-text search (works for space-delimited languages)
            rows = await conn.fetch(
                """
                SELECT
                    c.id,
                    c.document_id,
                    c.chunk_index,
                    c.content,
                    c.metadata,
                    d.original_name,
                    d.stored_path,
                    ts_rank_cd(
                        to_tsvector('simple', c.content),
                        plainto_tsquery('simple', $2)
                    ) AS keyword_score
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE c.knowledgebase_id = $1
                  AND to_tsvector('simple', c.content) @@ plainto_tsquery('simple', $2)
                ORDER BY keyword_score DESC, c.chunk_index ASC
                LIMIT $3
                """,
                knowledgebase_id,
                query,
                limit,
            )

            # Fallback: segment query into keywords, match with ILIKE, score by hit count
            if not rows:
                keywords = self._segment_keywords(query)
                if keywords:
                    # Build: (CASE WHEN content ILIKE '%kw1%' THEN 1 ELSE 0 END + ...) AS keyword_score
                    # WHERE: (content ILIKE '%kw1%' OR content ILIKE '%kw2%' OR ...)
                    where_parts = []
                    score_parts = []
                    params = [knowledgebase_id]
                    for i, kw in enumerate(keywords):
                        idx = i + 2  # $2, $3, ...
                        params.append(f"%{kw}%")
                        where_parts.append(f"c.content ILIKE ${idx}")
                        score_parts.append(f"CASE WHEN c.content ILIKE ${idx} THEN 1 ELSE 0 END")
                    params.append(limit)
                    limit_idx = len(params)
                    score_expr = " + ".join(score_parts)
                    where_expr = " OR ".join(where_parts)
                    sql = f"""
                        SELECT
                            c.id, c.document_id, c.chunk_index, c.content, c.metadata,
                            d.original_name, d.stored_path,
                            ({score_expr})::float / {len(keywords)}::float AS keyword_score
                        FROM knowledge_chunks c
                        JOIN knowledge_documents d ON d.id = c.document_id
                        WHERE c.knowledgebase_id = $1 AND ({where_expr})
                        ORDER BY keyword_score DESC, c.chunk_index ASC
                        LIMIT ${limit_idx}
                    """
                    rows = await conn.fetch(sql, *params)

        return [
            {
                "chunk_id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "chunk_index": int(row["chunk_index"]),
                "content": row["content"],
                "metadata": self._coerce_json_object(row["metadata"], field_name="metadata"),
                "document_name": row["original_name"],
                "stored_path": row["stored_path"],
                "keyword_score": float(row["keyword_score"] or 0.0),
            }
            for row in rows
        ]

    # ---- Keyword Segmentation ----

    def _segment_keywords(self, query: str) -> List[str]:
        """将查询拆分为关键词片段，用于 ILIKE 匹配。

        对中文按 2-gram 滑窗切分，对英文按空格分词。
        """
        import re
        tokens: List[str] = []
        # 按中文/非中文边界拆分
        parts = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]+|[a-zA-Z0-9]+', query)
        for part in parts:
            if re.match(r'^[\u4e00-\u9fff\u3400-\u4dbf]+$', part):
                # 中文：2-gram 滑窗
                n = 2
                if len(part) <= n:
                    tokens.append(part)
                else:
                    for i in range(len(part) - n + 1):
                        tokens.append(part[i:i + n])
            else:
                # 英文/数字：整词
                if len(part) >= 2:
                    tokens.append(part)
        # 去重保��
        seen: set[str] = set()
        result: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    # ---- Search Logs ----

    async def create_search_log(self, record: SearchLogRecord) -> SearchLogRecord:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_search_logs (
                    id, knowledgebase_id, query, mode, strategy,
                    top_k, hit_count, latency_ms, hits, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                record.id,
                record.knowledgebase_id,
                record.query,
                record.mode,
                record.strategy,
                record.top_k,
                record.hit_count,
                record.latency_ms,
                json.dumps(record.hits, ensure_ascii=False),
                record.created_at or datetime.utcnow(),
            )
        return record

    async def list_search_logs(self, knowledgebase_id: str, limit: int = 50) -> List[SearchLogRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM knowledge_search_logs
                WHERE knowledgebase_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                knowledgebase_id,
                limit,
            )
        return [self._row_to_search_log(row) for row in rows]

    async def clear_search_logs(self, knowledgebase_id: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge_search_logs WHERE knowledgebase_id = $1",
                knowledgebase_id,
            )
        # result is like "DELETE 5"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    def _row_to_search_log(self, row) -> SearchLogRecord:
        return SearchLogRecord(
            id=str(row["id"]),
            knowledgebase_id=str(row["knowledgebase_id"]),
            query=row["query"],
            mode=row["mode"] or "",
            strategy=row["strategy"] or "",
            top_k=int(row["top_k"] or 8),
            hit_count=int(row["hit_count"] or 0),
            latency_ms=int(row["latency_ms"] or 0),
            hits=self._coerce_json_list(row["hits"]),
            created_at=row["created_at"],
        )

    def _coerce_json_list(self, value: Any) -> List[Dict[str, Any]]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return list(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8", errors="ignore")
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return parsed
            return []
        return []

    def _row_to_kb(self, row) -> KnowledgeBaseRecord:
        return KnowledgeBaseRecord(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"] or "",
            embedding_model_id=row["embedding_model_id"] or "",
            rerank_model_id=row["rerank_model_id"] or "",
            llm_model_id=row["llm_model_id"] or "",
            chunk_size=int(row["chunk_size"] or 1200),
            chunk_overlap=int(row["chunk_overlap"] or 200),
            is_default=bool(row["is_default"]),
            vector_collection=row["vector_collection"] or "",
            embedding_dim=int(row["embedding_dim"]) if row["embedding_dim"] is not None else None,
            retrieval_config=self._coerce_json_object(row["retrieval_config"], field_name="retrieval_config"),
            metadata=self._coerce_json_object(row["metadata"], field_name="metadata"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_document(self, row) -> KnowledgeDocumentRecord:
        return KnowledgeDocumentRecord(
            id=str(row["id"]),
            knowledgebase_id=str(row["knowledgebase_id"]),
            original_name=row["original_name"],
            stored_path=row["stored_path"],
            parsed_path=row["parsed_path"] or "",
            parsed_text=row["parsed_text"] or "",
            mime_type=row["mime_type"] or "application/octet-stream",
            size=int(row["size"] or 0),
            file_hash=row["file_hash"] or "",
            status=row["status"] or "pending",
            chunk_count=int(row["chunk_count"] or 0),
            parser_name=row["parser_name"] or "markitdown",
            error=row["error"] or "",
            metadata=self._coerce_json_object(row["metadata"], field_name="metadata"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            indexed_at=row["indexed_at"],
        )

    def _row_to_chunk(self, row) -> KnowledgeChunkRecord:
        return KnowledgeChunkRecord(
            id=str(row["id"]),
            knowledgebase_id=str(row["knowledgebase_id"]),
            document_id=str(row["document_id"]),
            chunk_index=int(row["chunk_index"]),
            content=row["content"],
            token_count=int(row["token_count"] or 0),
            metadata=self._coerce_json_object(row["metadata"], field_name="metadata"),
            created_at=row["created_at"],
        )

    def _coerce_json_object(self, value: Any, *, field_name: str) -> Dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8", errors="ignore")
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"知识库字段 {field_name} 不是合法 JSON 对象，已回退为空对象: {value[:120]}")
                return {}
            if isinstance(parsed, dict):
                return parsed
            logger.warning(f"知识库字段 {field_name} JSON 解析后不是对象，已回退为空对象: {type(parsed).__name__}")
            return {}
        try:
            return dict(value)
        except (TypeError, ValueError):
            logger.warning(f"知识库字段 {field_name} 无法转换为对象，已回退为空对象: {type(value).__name__}")
            return {}
