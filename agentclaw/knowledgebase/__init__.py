"""
知识库模块入口
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from agentclaw.config import get_config
from agentclaw.knowledgebase.backend import MilvusKnowledgeRetrievalBackend
from agentclaw.knowledgebase.model_gateway import KnowledgeBaseModelGateway
from agentclaw.knowledgebase.parser import MarkItDownParser
from agentclaw.knowledgebase.service import KnowledgeBaseService
from agentclaw.knowledgebase.storage import KnowledgeBaseStorage
from agentclaw.knowledgebase.store import KnowledgeBaseStore
from agentclaw.knowledgebase.vector_store import MilvusVectorStore
from agentclaw.logger.config import get_logger

if False:  # pragma: no cover
    from agentclaw.database.manager import DatabaseManager


_global_service: Optional[KnowledgeBaseService] = None
logger = get_logger(__name__)


def _resolve_milvus_uri(configured_uri: str, storage_root: Path, platform: str | None = None) -> str:
    """Resolve the Milvus URI, falling back to Milvus Lite where supported."""
    milvus_uri = (configured_uri or "").strip()
    if milvus_uri:
        return milvus_uri

    current_platform = platform or sys.platform
    if current_platform == "win32":
        raise RuntimeError(
            "MILVUS_URI 未配置；Milvus Lite 不支持 Windows。"
            "请使用 Docker/远程 Milvus，并配置 MILVUS_URI。"
        )

    return str(storage_root / "milvus.db")


def get_knowledgebase_service() -> Optional[KnowledgeBaseService]:
    return _global_service


async def init_knowledgebase_service(db: "DatabaseManager") -> KnowledgeBaseService:
    global _global_service

    config = get_config()
    kb_config = config.knowledgebase
    project_dir = config.project.project_dir
    storage_root = Path(kb_config.storage_dir)
    parsed_root = Path(kb_config.parser_cache_dir)
    if not storage_root.is_absolute():
        storage_root = project_dir / storage_root
    if not parsed_root.is_absolute():
        parsed_root = project_dir / parsed_root
    storage_root.mkdir(parents=True, exist_ok=True)
    parsed_root.mkdir(parents=True, exist_ok=True)

    milvus_uri = (kb_config.milvus_uri or "").strip()
    if kb_config.enabled and kb_config.backend == "milvus":
        milvus_uri_configured = bool(milvus_uri)
        milvus_uri = _resolve_milvus_uri(milvus_uri, storage_root)
        if not milvus_uri_configured:
            logger.info(f"知识库未配置 MILVUS_URI，自动使用本地 Milvus Lite: {milvus_uri}")

    vector_store = MilvusVectorStore(
        uri=milvus_uri,
        token=kb_config.milvus_token,
        metric_type=kb_config.milvus_metric_type,
        index_type=kb_config.milvus_index_type,
    )

    service = KnowledgeBaseService(
        store=KnowledgeBaseStore(db.pg_pool),
        storage=KnowledgeBaseStorage(storage_root, parsed_root),
        parser=MarkItDownParser(),
        model_gateway=KnowledgeBaseModelGateway(
            models_config_path=str(config.project.models_config) if config.project.models_config else None,
            default_embedding_model=kb_config.default_embedding_model,
            default_rerank_model=kb_config.default_rerank_model,
            default_llm_model=kb_config.default_llm_model,
        ),
        retrieval_backend=MilvusKnowledgeRetrievalBackend(
            vector_store=vector_store,
            config=kb_config,
        ),
        config=kb_config,
    )
    await service.init()
    _global_service = service
    return service


__all__ = [
    "KnowledgeBaseService",
    "KnowledgeBaseStore",
    "KnowledgeBaseStorage",
    "MilvusKnowledgeRetrievalBackend",
    "get_knowledgebase_service",
    "init_knowledgebase_service",
]
