"""
知识库 API Schema
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreateRequest(BaseModel):
    name: str
    description: str = ""
    embedding_model_id: str = ""
    rerank_model_id: str = ""
    llm_model_id: str = ""
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    is_default: bool = False
    retrieval_config: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    embedding_model_id: Optional[str] = None
    rerank_model_id: Optional[str] = None
    llm_model_id: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    is_default: Optional[bool] = None
    retrieval_config: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding_dim: Optional[int] = None


class KnowledgeBaseResponse(BaseModel):
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
    retrieval_config: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    document_count: int = 0
    chunk_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class KnowledgeDocumentResponse(BaseModel):
    id: str
    knowledgebase_id: str
    original_name: str
    stored_path: str
    parsed_path: str = ""
    mime_type: str
    size: int
    file_hash: str = ""
    status: str = "pending"
    chunk_count: int = 0
    parser_name: str = "markitdown"
    error: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None


class KnowledgeChunkCreateRequest(BaseModel):
    content: str
    chunk_index: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunkUpdateRequest(BaseModel):
    content: Optional[str] = None
    chunk_index: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeChunkResponse(BaseModel):
    id: str
    knowledgebase_id: str
    document_id: str
    chunk_index: int
    content: str
    token_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class KnowledgeBaseSearchRequest(BaseModel):
    query: str
    top_k: int = 8
    mode: Optional[str] = None
    score_threshold: Optional[float] = None
    rerank_model_id: Optional[str] = None
    prefer_builtin_hybrid: Optional[bool] = None


class KnowledgeBaseSearchHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    content: str
    score: float
    dense_score: float = 0.0
    keyword_score: float = 0.0
    source_path: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseSearchResponse(BaseModel):
    query: str
    knowledgebase_id: str
    strategy: str = "hybrid"
    rerank_applied: bool = False
    total: int
    hits: List[KnowledgeBaseSearchHitResponse]


class KnowledgeBaseImportPathRequest(BaseModel):
    file_path: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchLogCreateRequest(BaseModel):
    query: str
    mode: str = ""
    strategy: str = ""
    top_k: int = 8
    hit_count: int = 0
    latency_ms: int = 0
    hits: List[Dict[str, Any]] = Field(default_factory=list)


class SearchLogResponse(BaseModel):
    id: str
    knowledgebase_id: str
    query: str
    mode: str = ""
    strategy: str = ""
    top_k: int = 8
    hit_count: int = 0
    latency_ms: int = 0
    hits: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None
