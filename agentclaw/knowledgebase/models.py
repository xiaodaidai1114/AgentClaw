"""
知识库领域模型
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class KnowledgeBaseRecord:
    id: str
    name: str
    description: str = ""
    embedding_model_id: str = ""
    rerank_model_id: str = ""
    llm_model_id: str = ""
    chunk_size: int = 1200
    chunk_overlap: int = 200
    is_default: bool = False
    vector_collection: str = ""
    embedding_dim: Optional[int] = None
    retrieval_config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class KnowledgeDocumentRecord:
    id: str
    knowledgebase_id: str
    original_name: str
    stored_path: str
    parsed_path: str = ""
    parsed_text: str = ""
    mime_type: str = "application/octet-stream"
    size: int = 0
    file_hash: str = ""
    status: str = "pending"
    chunk_count: int = 0
    parser_name: str = "markitdown"
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None


@dataclass
class KnowledgeChunkRecord:
    id: str
    knowledgebase_id: str
    document_id: str
    chunk_index: int
    content: str
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None


@dataclass
class ParsedDocument:
    text: str
    markdown: str
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    parser_name: str = "markitdown"


@dataclass
class ChunkPayload:
    chunk_index: int
    content: str
    token_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchHit:
    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    content: str
    score: float
    dense_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: Optional[float] = None
    source_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchCandidate:
    chunk_id: str
    score: float
    dense_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: Optional[float] = None


@dataclass
class SearchExecution:
    strategy: str
    candidates: List[SearchCandidate]


@dataclass
class SearchResult:
    query: str
    knowledgebase_id: str
    hits: List[SearchHit]
    total: int
    strategy: str = "hybrid"
    rerank_applied: bool = False


@dataclass
class SearchLogRecord:
    id: str
    knowledgebase_id: str
    query: str
    mode: str = ""
    strategy: str = ""
    top_k: int = 8
    hit_count: int = 0
    latency_ms: int = 0
    hits: List[Dict[str, Any]] = field(default_factory=list)
    created_at: Optional[datetime] = None
