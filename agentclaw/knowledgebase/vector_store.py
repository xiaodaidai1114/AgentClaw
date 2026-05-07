"""
知识库向量存储

默认优先：
- Milvus built-in hybrid search（dense + BM25）
- 若当前环境不支持，再降级为 dense 检索
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, List, Optional

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

_MILVUS_GRPC_OPTIONS = {
    "grpc.keepalive_time_ms": 60000,
    "grpc.keepalive_timeout_ms": 10000,
    "grpc.keepalive_permit_without_calls": False,
}


class MilvusVectorStore:
    """Milvus 稠密向量存储。"""

    def __init__(
        self,
        *,
        uri: str,
        token: str = "",
        metric_type: str = "COSINE",
        index_type: str = "AUTOINDEX",
    ):
        self.uri = uri
        self.token = token
        self.metric_type = metric_type
        self.index_type = index_type
        self.sparse_field_name = "sparse_embedding"
        self._client = None
        self._builtin_hybrid_supported: Optional[bool] = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pymilvus 未安装，无法使用知识库向量索引。请安装知识库依赖：pip install 'agentclaw[knowledgebase]'"
            ) from exc

        kwargs = {"uri": self.uri}
        if self.token:
            kwargs["token"] = self.token
        kwargs["grpc_options"] = dict(_MILVUS_GRPC_OPTIONS)
        self._client = MilvusClient(**kwargs)
        return self._client

    def _has_collection(self, collection_name: str) -> bool:
        client = self._get_client()
        if hasattr(client, "has_collection"):
            return bool(client.has_collection(collection_name=collection_name))
        if hasattr(client, "list_collections"):
            return collection_name in set(client.list_collections())
        return False

    def supports_builtin_hybrid(self) -> bool:
        if self._builtin_hybrid_supported is not None:
            return self._builtin_hybrid_supported

        try:
            from pymilvus import DataType  # type: ignore
        except ImportError:
            self._builtin_hybrid_supported = False
            return False

        client = self._get_client()
        self._builtin_hybrid_supported = hasattr(client, "hybrid_search") and hasattr(DataType, "SPARSE_FLOAT_VECTOR")
        return self._builtin_hybrid_supported

    def ensure_collection(self, collection_name: str, dimension: int, enable_hybrid: bool = False) -> None:
        client = self._get_client()
        if self._has_collection(collection_name):
            if hasattr(client, "load_collection"):
                try:
                    client.load_collection(collection_name=collection_name)
                except Exception:
                    pass
            return

        if enable_hybrid and self.supports_builtin_hybrid():
            try:
                self._create_hybrid_collection(client, collection_name, dimension)
                return
            except Exception as exc:
                logger.warning(f"Milvus hybrid collection 创建失败，将降级为 dense collection: {exc}")

        self._create_dense_collection(client, collection_name, dimension)

    def _create_dense_collection(self, client, collection_name: str, dimension: int) -> None:
        try:
            from pymilvus import DataType, MilvusClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pymilvus 未安装，无法创建知识库集合。请安装知识库依赖：pip install 'agentclaw[knowledgebase]'"
            ) from exc

        if hasattr(MilvusClient, "create_schema") and hasattr(MilvusClient, "prepare_index_params"):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="knowledgebase_id", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
            schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
            schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dimension)

            index_params = MilvusClient.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type=self.index_type,
                metric_type=self.metric_type,
                params={},
            )

            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
        else:
            client.create_collection(
                collection_name=collection_name,
                dimension=dimension,
                metric_type=self.metric_type,
                auto_id=False,
                primary_field_name="chunk_id",
                vector_field_name="embedding",
                id_type="string",
                max_length=64,
            )

        if hasattr(client, "load_collection"):
            try:
                client.load_collection(collection_name=collection_name)
            except Exception:
                pass

    def _create_hybrid_collection(self, client, collection_name: str, dimension: int) -> None:
        try:
            from pymilvus import DataType, Function, FunctionType, MilvusClient  # type: ignore
        except ImportError as exc:
            raise RuntimeError("当前 pymilvus 不支持 hybrid search 相关类型") from exc

        if not hasattr(MilvusClient, "create_schema") or not hasattr(MilvusClient, "prepare_index_params"):
            raise RuntimeError("当前 MilvusClient 不支持 schema/index API，无法创建 hybrid collection")

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="knowledgebase_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535, enable_analyzer=True)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field(field_name=self.sparse_field_name, datatype=DataType.SPARSE_FLOAT_VECTOR)

        if not hasattr(schema, "add_function"):
            raise RuntimeError("当前 pymilvus schema 不支持 add_function，无法启用 BM25 built-in")

        schema.add_function(
            Function(
                name="bm25_text_function",
                function_type=FunctionType.BM25,
                input_field_names=["content"],
                output_field_names=[self.sparse_field_name],
            )
        )

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type=self.index_type,
            metric_type=self.metric_type,
            params={},
        )
        index_params.add_index(
            field_name=self.sparse_field_name,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={},
        )

        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

        if hasattr(client, "load_collection"):
            try:
                client.load_collection(collection_name=collection_name)
            except Exception:
                pass

    def upsert_chunks(self, collection_name: str, rows: Iterable[Dict[str, Any]]) -> None:
        client = self._get_client()
        payload = list(rows)
        if not payload:
            return
        client.upsert(collection_name=collection_name, data=payload)

    def search_dense(self, collection_name: str, vector: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        if not vector:
            return []
        if not self._has_collection(collection_name):
            logger.warning(f"Milvus collection 不存在，跳过 dense 检索: {collection_name}")
            return []
        client = self._get_client()
        try:
            results = client.search(
                collection_name=collection_name,
                data=[vector],
                anns_field="embedding",
                limit=limit,
                search_params={"metric_type": self.metric_type, "params": {}},
                output_fields=["chunk_id", "document_id", "knowledgebase_id", "chunk_index"],
            )
        except Exception as exc:
            logger.warning(f"Milvus dense 检索执行失败，返回空结果以便上层继续降级: {exc}")
            return []
        return self._normalize_hits(results)

    def search(self, collection_name: str, vector: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        return self.search_dense(collection_name, vector, limit)

    def hybrid_search(
        self,
        *,
        collection_name: str,
        query_text: str,
        vector: List[float],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        if not query_text or not vector or not self.supports_builtin_hybrid():
            return []
        if not self._has_collection(collection_name):
            logger.warning(f"Milvus collection 不存在，跳过 hybrid 检索: {collection_name}")
            return []

        client = self._get_client()
        if not hasattr(client, "hybrid_search"):
            return []

        try:
            from pymilvus import AnnSearchRequest, RRFRanker  # type: ignore
        except ImportError:
            return []

        request_limit = max(limit * 2, limit)
        requests = [
            AnnSearchRequest(
                data=[vector],
                anns_field="embedding",
                param={"metric_type": self.metric_type, "params": {}},
                limit=request_limit,
            ),
            AnnSearchRequest(
                data=[query_text],
                anns_field=self.sparse_field_name,
                param={"metric_type": "BM25", "params": {}},
                limit=request_limit,
            ),
        ]

        kwargs: Dict[str, Any] = {
            "collection_name": collection_name,
            "limit": limit,
            "output_fields": ["chunk_id", "document_id", "knowledgebase_id", "chunk_index"],
        }
        try:
            signature = inspect.signature(client.hybrid_search)
            if "reqs" in signature.parameters:
                kwargs["reqs"] = requests
            elif "requests" in signature.parameters:
                kwargs["requests"] = requests
            else:
                kwargs["reqs"] = requests

            if "ranker" in signature.parameters:
                kwargs["ranker"] = RRFRanker()
            elif "rerank" in signature.parameters:
                kwargs["rerank"] = RRFRanker()
        except Exception:
            kwargs["reqs"] = requests
            kwargs["ranker"] = RRFRanker()

        try:
            results = client.hybrid_search(**kwargs)
        except Exception as exc:
            logger.warning(f"Milvus hybrid_search 执行失败，将使用兼容降级路径: {exc}")
            return []

        return self._normalize_hits(results)

    def delete_chunks(self, collection_name: str, chunk_ids: List[str]) -> None:
        if not chunk_ids:
            return
        client = self._get_client()
        quoted = ", ".join(f'"{chunk_id}"' for chunk_id in chunk_ids)
        client.delete(collection_name=collection_name, filter=f"chunk_id in [{quoted}]")

    def drop_collection(self, collection_name: str) -> None:
        client = self._get_client()
        if self._has_collection(collection_name):
            client.drop_collection(collection_name=collection_name)

    def _normalize_hits(self, results: Any) -> List[Dict[str, Any]]:
        if not results:
            return []

        first = results[0] if isinstance(results, list) else results
        if isinstance(first, list):
            items = first
        elif isinstance(first, dict):
            items = results if isinstance(results, list) else [results]
        else:
            try:
                items = list(first)
            except TypeError:
                items = [first]

        hits: List[Dict[str, Any]] = []
        for item in items:
            entity = item.get("entity") if isinstance(item, dict) else None
            entity = entity or item or {}
            hits.append(
                {
                    "chunk_id": entity.get("chunk_id") or entity.get("id") or item.get("id"),
                    "document_id": entity.get("document_id"),
                    "knowledgebase_id": entity.get("knowledgebase_id"),
                    "chunk_index": entity.get("chunk_index"),
                    "score": float(item.get("distance") or item.get("score") or 0.0),
                }
            )
        return hits
