"""
知识库检索后端抽象。

目标：
- service 只负责导入、编排与结果组装
- 检索策略收敛到 backend，避免在 service 层手工拼逻辑
- 默认后端优先使用 Milvus 的内建能力，必要时再降级
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Iterable, List

from agentclaw.config import KnowledgeBaseConfig
from agentclaw.knowledgebase.models import (
    KnowledgeBaseRecord,
    SearchCandidate,
    SearchExecution,
)
from agentclaw.knowledgebase.vector_store import MilvusVectorStore

EmbedQueryFn = Callable[[str, str], Awaitable[List[float]]]
KeywordSearchFn = Callable[[str, str, int], Awaitable[List[Dict[str, Any]]]]


class KnowledgeRetrievalBackend(ABC):
    """知识库检索后端抽象。"""

    @abstractmethod
    def ensure_collection(self, *, knowledgebase: KnowledgeBaseRecord, dimension: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_chunks(self, *, knowledgebase: KnowledgeBaseRecord, rows: Iterable[Dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_chunks(self, *, knowledgebase: KnowledgeBaseRecord, chunk_ids: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def drop_collection(self, *, knowledgebase: KnowledgeBaseRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        *,
        knowledgebase: KnowledgeBaseRecord,
        query: str,
        limit: int,
        embed_query: EmbedQueryFn,
        keyword_search: KeywordSearchFn,
        overrides: Dict[str, Any] | None = None,
    ) -> SearchExecution:
        raise NotImplementedError


class MilvusKnowledgeRetrievalBackend(KnowledgeRetrievalBackend):
    """Milvus 检索后端。

    默认策略：
    1. 优先尝试 Milvus built-in hybrid search
    2. 若不可用，再降级为 dense + keyword 的兼容混合检索
    """

    def __init__(self, *, vector_store: MilvusVectorStore, config: KnowledgeBaseConfig):
        self.vector_store = vector_store
        self.config = config

    def ensure_collection(self, *, knowledgebase: KnowledgeBaseRecord, dimension: int) -> None:
        retrieval_config = self._merged_retrieval_config(knowledgebase)
        enable_hybrid = retrieval_config.get("mode") == "hybrid"
        self.vector_store.ensure_collection(
            collection_name=knowledgebase.vector_collection,
            dimension=dimension,
            enable_hybrid=bool(enable_hybrid),
        )

    def upsert_chunks(self, *, knowledgebase: KnowledgeBaseRecord, rows: Iterable[Dict[str, Any]]) -> None:
        self.vector_store.upsert_chunks(knowledgebase.vector_collection, rows)

    def delete_chunks(self, *, knowledgebase: KnowledgeBaseRecord, chunk_ids: List[str]) -> None:
        self.vector_store.delete_chunks(knowledgebase.vector_collection, chunk_ids)

    def drop_collection(self, *, knowledgebase: KnowledgeBaseRecord) -> None:
        self.vector_store.drop_collection(knowledgebase.vector_collection)

    async def search(
        self,
        *,
        knowledgebase: KnowledgeBaseRecord,
        query: str,
        limit: int,
        embed_query: EmbedQueryFn,
        keyword_search: KeywordSearchFn,
        overrides: Dict[str, Any] | None = None,
    ) -> SearchExecution:
        query_text = (query or "").strip()
        if not query_text:
            return SearchExecution(strategy="empty", candidates=[])

        retrieval_config = self._merged_retrieval_config(knowledgebase)
        # Apply caller overrides (e.g. prefer_builtin_hybrid from admin test panel)
        if overrides:
            retrieval_config.update(overrides)
        mode = str(retrieval_config.get("mode") or "hybrid").strip().lower()

        if mode in {"keyword", "sparse"}:
            keyword_hits = await keyword_search(knowledgebase.id, query_text, self._keyword_limit(retrieval_config, limit))
            return SearchExecution(
                strategy="keyword",
                candidates=self._keyword_candidates(keyword_hits)[:limit],
            )

        query_vector: List[float] = []
        if knowledgebase.embedding_model_id:
            query_vector = await embed_query(query_text, knowledgebase.embedding_model_id)

        if mode == "dense":
            dense_hits = self.vector_store.search_dense(
                knowledgebase.vector_collection,
                query_vector,
                limit=self._dense_limit(retrieval_config, limit),
            ) if query_vector else []
            return SearchExecution(
                strategy="dense",
                candidates=self._dense_candidates(dense_hits)[:limit],
            )

        # Hybrid: always do dense + keyword separately, then weighted merge
        dense_hits = self.vector_store.search_dense(
            knowledgebase.vector_collection,
            query_vector,
            limit=self._dense_limit(retrieval_config, limit),
        ) if query_vector else []
        keyword_hits = await keyword_search(knowledgebase.id, query_text, self._keyword_limit(retrieval_config, limit))

        vector_weight = float(retrieval_config.get("vector_weight") or 0.7)
        keyword_weight = float(retrieval_config.get("keyword_weight") or 0.3)
        candidates = self._weighted_merge(dense_hits, keyword_hits, limit, vector_weight, keyword_weight)

        if candidates:
            return SearchExecution(strategy="hybrid", candidates=candidates)
        if dense_hits:
            return SearchExecution(strategy="dense_only_fallback", candidates=self._dense_candidates(dense_hits)[:limit])
        if keyword_hits:
            return SearchExecution(strategy="keyword_only_fallback", candidates=self._keyword_candidates(keyword_hits)[:limit])
        return SearchExecution(strategy="hybrid", candidates=[])

    def _merged_retrieval_config(self, knowledgebase: KnowledgeBaseRecord) -> Dict[str, Any]:
        return {
            "backend": self.config.backend,
            "mode": self.config.default_retrieval_mode,
            "prefer_builtin_hybrid": self.config.prefer_builtin_hybrid,
            "dense_candidate_multiplier": self.config.dense_candidate_multiplier,
            "keyword_candidate_multiplier": self.config.keyword_candidate_multiplier,
            **(knowledgebase.retrieval_config or {}),
        }

    def _dense_limit(self, retrieval_config: Dict[str, Any], limit: int) -> int:
        multiplier = int(retrieval_config.get("dense_candidate_multiplier") or 3)
        return max(limit, limit * max(multiplier, 1))

    def _keyword_limit(self, retrieval_config: Dict[str, Any], limit: int) -> int:
        multiplier = int(retrieval_config.get("keyword_candidate_multiplier") or 3)
        return max(limit, limit * max(multiplier, 1))

    def _dense_candidates(self, hits: List[Dict[str, Any]]) -> List[SearchCandidate]:
        return [
            SearchCandidate(
                chunk_id=str(item.get("chunk_id") or ""),
                score=float(item.get("score") or 0.0),
                dense_score=float(item.get("score") or 0.0),
            )
            for item in hits
            if item.get("chunk_id")
        ]

    def _keyword_candidates(self, hits: List[Dict[str, Any]]) -> List[SearchCandidate]:
        return [
            SearchCandidate(
                chunk_id=str(item.get("chunk_id") or ""),
                score=float(item.get("keyword_score") or 0.0),
                keyword_score=float(item.get("keyword_score") or 0.0),
            )
            for item in hits
            if item.get("chunk_id")
        ]

    def _weighted_merge(
        self,
        dense_hits: List[Dict[str, Any]],
        keyword_hits: List[Dict[str, Any]],
        limit: int,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[SearchCandidate]:
        dense_score_map: Dict[str, float] = {}
        keyword_score_map: Dict[str, float] = {}
        all_ids: set[str] = set()

        for item in dense_hits:
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            dense_score_map[chunk_id] = float(item.get("score") or 0.0)
            all_ids.add(chunk_id)

        for item in keyword_hits:
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            keyword_score_map[chunk_id] = float(item.get("keyword_score") or 0.0)
            all_ids.add(chunk_id)

        candidates = []
        for chunk_id in all_ids:
            ds = dense_score_map.get(chunk_id, 0.0)
            ks = keyword_score_map.get(chunk_id, 0.0)
            score = ds * vector_weight + ks * keyword_weight
            candidates.append(SearchCandidate(
                chunk_id=chunk_id,
                score=score,
                dense_score=ds,
                keyword_score=ks,
            ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:limit]
