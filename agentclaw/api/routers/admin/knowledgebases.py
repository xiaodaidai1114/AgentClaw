"""
知识库管理 Admin API
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from agentclaw.api.upload_limits import (
    UploadTooLarge,
    enforce_upload_content_length,
    read_upload_file_limited,
)
from agentclaw.api.schemas.common import ErrorCode
from agentclaw.api.schemas.knowledgebase import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseImportPathRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseSearchResponse,
    KnowledgeChunkCreateRequest,
    KnowledgeChunkResponse,
    KnowledgeChunkUpdateRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentResponse,
    SearchLogCreateRequest,
    SearchLogResponse,
)
from agentclaw.knowledgebase import get_knowledgebase_service

router = APIRouter(prefix="/knowledgebases", tags=["knowledgebases"])


def _get_service():
    service = get_knowledgebase_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "KnowledgeBase service not initialized",
                "code": ErrorCode.SERVICE_UNAVAILABLE,
            },
        )
    return service


async def _kb_to_response(service, record) -> dict:
    stats = await service.store.get_knowledgebase_stats(record.id)
    return KnowledgeBaseResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        embedding_model_id=record.embedding_model_id,
        rerank_model_id=record.rerank_model_id,
        llm_model_id=record.llm_model_id,
        chunk_size=record.chunk_size,
        chunk_overlap=record.chunk_overlap,
        is_default=record.is_default,
        vector_collection=record.vector_collection,
        embedding_dim=record.embedding_dim,
        retrieval_config=record.retrieval_config,
        metadata=record.metadata,
        document_count=stats["document_count"],
        chunk_count=stats["chunk_count"],
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


def _document_to_response(record) -> dict:
    return KnowledgeDocumentResponse(
        id=record.id,
        knowledgebase_id=record.knowledgebase_id,
        original_name=record.original_name,
        stored_path=record.stored_path,
        parsed_path=record.parsed_path,
        mime_type=record.mime_type,
        size=record.size,
        file_hash=record.file_hash,
        status=record.status,
        chunk_count=record.chunk_count,
        parser_name=record.parser_name,
        error=record.error,
        metadata=record.metadata,
        created_at=record.created_at,
        updated_at=record.updated_at,
        indexed_at=record.indexed_at,
    ).model_dump(mode="json")


def _chunk_to_response(record) -> dict:
    return KnowledgeChunkResponse(
        id=record.id,
        knowledgebase_id=record.knowledgebase_id,
        document_id=record.document_id,
        chunk_index=record.chunk_index,
        content=record.content,
        token_count=record.token_count,
        metadata=record.metadata,
        created_at=record.created_at,
    ).model_dump(mode="json")


def _search_hit_to_response(hit) -> dict:
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "document_name": hit.document_name,
        "chunk_index": hit.chunk_index,
        "content": hit.content,
        "score": hit.score,
        "dense_score": hit.dense_score,
        "keyword_score": hit.keyword_score,
        "source_path": hit.source_path,
        "metadata": hit.metadata,
    }


@router.get("")
async def list_knowledgebases():
    service = _get_service()
    knowledgebases = await service.list_knowledgebases()
    return {"knowledgebases": [await _kb_to_response(service, item) for item in knowledgebases]}


@router.post("")
async def create_knowledgebase(body: KnowledgeBaseCreateRequest):
    service = _get_service()
    record = await service.create_knowledgebase(**body.model_dump())
    return await _kb_to_response(service, record)


@router.get("/{knowledgebase_id}")
async def get_knowledgebase(knowledgebase_id: str):
    service = _get_service()
    record = await service.get_knowledgebase(knowledgebase_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"error": "KnowledgeBase not found", "code": ErrorCode.NOT_FOUND})
    return await _kb_to_response(service, record)


@router.put("/{knowledgebase_id}")
async def update_knowledgebase(knowledgebase_id: str, body: KnowledgeBaseUpdateRequest):
    service = _get_service()
    record = await service.update_knowledgebase(
        knowledgebase_id,
        {key: value for key, value in body.model_dump().items() if value is not None},
    )
    if record is None:
        raise HTTPException(status_code=404, detail={"error": "KnowledgeBase not found", "code": ErrorCode.NOT_FOUND})
    return await _kb_to_response(service, record)


@router.delete("/{knowledgebase_id}")
async def delete_knowledgebase(knowledgebase_id: str):
    service = _get_service()
    ok = await service.delete_knowledgebase(knowledgebase_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "KnowledgeBase not found", "code": ErrorCode.NOT_FOUND})
    return {"ok": True}


@router.get("/{knowledgebase_id}/documents")
async def list_documents(knowledgebase_id: str):
    service = _get_service()
    documents = await service.list_documents(knowledgebase_id)
    return {"documents": [_document_to_response(item) for item in documents]}


@router.get("/{knowledgebase_id}/documents/{document_id}")
async def get_document(knowledgebase_id: str, document_id: str):
    service = _get_service()
    document = await service.get_document(knowledgebase_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    return _document_to_response(document)


@router.get("/{knowledgebase_id}/documents/{document_id}/download")
async def download_document(knowledgebase_id: str, document_id: str):
    service = _get_service()
    document = await service.get_document(knowledgebase_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})

    from agentclaw.database.file_storage import get_file_storage
    from agentclaw.api.files.response import file_response_headers
    from fastapi.responses import Response
    file_storage = get_file_storage()
    if file_storage:
        data = await file_storage._read_file(document.stored_path)
        if data:
            return Response(
                content=data,
                media_type=document.mime_type or "application/octet-stream",
                headers=file_response_headers(
                    document.original_name,
                    document.mime_type or "application/octet-stream",
                    download=True,
                ),
            )

    # Fallback: 旧数据直接从磁盘读取
    from agentclaw.database.file_storage import resolve_allowed_legacy_file_path

    file_path = resolve_allowed_legacy_file_path(document.stored_path)
    if not file_path:
        raise HTTPException(status_code=404, detail={"error": "File not found on disk", "code": ErrorCode.NOT_FOUND})
    if not file_path.exists():
        raise HTTPException(status_code=404, detail={"error": "File not found on disk", "code": ErrorCode.NOT_FOUND})
    return FileResponse(
        path=str(file_path),
        media_type=document.mime_type or "application/octet-stream",
        headers=file_response_headers(
            document.original_name,
            document.mime_type or "application/octet-stream",
            download=True,
        ),
    )


@router.post("/{knowledgebase_id}/documents/upload")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    knowledgebase_id: str,
    file: UploadFile = File(...),
):
    service = _get_service()
    from agentclaw.config import get_config

    config = get_config()
    enforce_upload_content_length(request, config.upload.max_size_bytes)
    try:
        data = await read_upload_file_limited(file, config.upload.max_size_bytes)
    except UploadTooLarge:
        raise HTTPException(
            status_code=413,
            detail={"error": "File size exceeds limit", "code": ErrorCode.INVALID_REQUEST},
        )
    record = await service.upload_document(
        knowledgebase_id=knowledgebase_id,
        data=data,
        filename=file.filename or "unnamed",
        mime_type=file.content_type,
        index_now=False,
    )
    background_tasks.add_task(service.process_document, record.id)
    return _document_to_response(record)


@router.post("/{knowledgebase_id}/documents/import")
async def import_local_document(knowledgebase_id: str, body: KnowledgeBaseImportPathRequest):
    service = _get_service()
    record = await service.import_local_document(
        knowledgebase_id=knowledgebase_id,
        file_path=body.file_path,
        metadata=body.metadata,
    )
    return _document_to_response(record)


@router.post("/{knowledgebase_id}/documents/{document_id}/reindex")
async def reindex_document(knowledgebase_id: str, document_id: str):
    service = _get_service()
    record = await service.reindex_document(document_id)
    if record.knowledgebase_id != knowledgebase_id:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    return _document_to_response(record)


@router.post("/{knowledgebase_id}/documents/{document_id}/replace")
async def replace_document(
    request: Request,
    knowledgebase_id: str,
    document_id: str,
    file: UploadFile = File(...),
):
    service = _get_service()
    from agentclaw.config import get_config

    config = get_config()
    enforce_upload_content_length(request, config.upload.max_size_bytes)
    try:
        data = await read_upload_file_limited(file, config.upload.max_size_bytes)
    except UploadTooLarge:
        raise HTTPException(
            status_code=413,
            detail={"error": "File size exceeds limit", "code": ErrorCode.INVALID_REQUEST},
        )
    record = await service.replace_document(
        knowledgebase_id=knowledgebase_id,
        document_id=document_id,
        data=data,
        filename=file.filename or "unnamed",
        mime_type=file.content_type,
    )
    return _document_to_response(record)


@router.delete("/{knowledgebase_id}/documents/{document_id}")
async def delete_document(knowledgebase_id: str, document_id: str):
    service = _get_service()
    ok = await service.delete_document(knowledgebase_id, document_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    return {"ok": True}


@router.get("/{knowledgebase_id}/documents/{document_id}/chunks")
async def list_document_chunks(knowledgebase_id: str, document_id: str):
    service = _get_service()
    try:
        chunks = await service.list_chunks(knowledgebase_id, document_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    return {"chunks": [_chunk_to_response(item) for item in chunks]}


@router.post("/{knowledgebase_id}/documents/{document_id}/chunks")
async def create_document_chunk(knowledgebase_id: str, document_id: str, body: KnowledgeChunkCreateRequest):
    service = _get_service()
    try:
        chunk = await service.create_chunk(
            knowledgebase_id=knowledgebase_id,
            document_id=document_id,
            content=body.content,
            chunk_index=body.chunk_index,
            metadata=body.metadata,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    return _chunk_to_response(chunk)


@router.put("/{knowledgebase_id}/documents/{document_id}/chunks/{chunk_id}")
async def update_document_chunk(
    knowledgebase_id: str,
    document_id: str,
    chunk_id: str,
    body: KnowledgeChunkUpdateRequest,
):
    service = _get_service()
    try:
        chunk = await service.update_chunk(
            knowledgebase_id=knowledgebase_id,
            document_id=document_id,
            chunk_id=chunk_id,
            updates={key: value for key, value in body.model_dump().items() if value is not None},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    if chunk is None:
        raise HTTPException(status_code=404, detail={"error": "Chunk not found", "code": ErrorCode.NOT_FOUND})
    return _chunk_to_response(chunk)


@router.delete("/{knowledgebase_id}/documents/{document_id}/chunks/{chunk_id}")
async def delete_document_chunk(knowledgebase_id: str, document_id: str, chunk_id: str):
    service = _get_service()
    try:
        ok = await service.delete_chunk(
            knowledgebase_id=knowledgebase_id,
            document_id=document_id,
            chunk_id=chunk_id,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Document not found", "code": ErrorCode.NOT_FOUND})
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "Chunk not found", "code": ErrorCode.NOT_FOUND})
    return {"ok": True}


@router.post("/{knowledgebase_id}/search")
async def search_knowledgebase(knowledgebase_id: str, body: KnowledgeBaseSearchRequest):
    service = _get_service()
    result = await service.search(
        query=body.query,
        knowledgebase_id=knowledgebase_id,
        top_k=body.top_k,
        mode=body.mode,
        score_threshold=body.score_threshold,
        rerank_model_id=body.rerank_model_id,
        prefer_builtin_hybrid=body.prefer_builtin_hybrid,
    )
    return KnowledgeBaseSearchResponse(
        query=result.query,
        knowledgebase_id=result.knowledgebase_id,
        strategy=result.strategy,
        rerank_applied=result.rerank_applied,
        total=result.total,
        hits=[_search_hit_to_response(hit) for hit in result.hits],
    ).model_dump(mode="json")


# ---- Search Logs ----

@router.get("/{knowledgebase_id}/search-logs")
async def list_search_logs(knowledgebase_id: str, limit: int = 50):
    service = _get_service()
    logs = await service.store.list_search_logs(knowledgebase_id, limit=min(limit, 200))
    return {
        "logs": [
            SearchLogResponse(
                id=log.id,
                knowledgebase_id=log.knowledgebase_id,
                query=log.query,
                mode=log.mode,
                strategy=log.strategy,
                top_k=log.top_k,
                hit_count=log.hit_count,
                latency_ms=log.latency_ms,
                hits=log.hits,
                created_at=log.created_at,
            ).model_dump(mode="json")
            for log in logs
        ],
        "total": len(logs),
    }


@router.post("/{knowledgebase_id}/search-logs")
async def create_search_log(knowledgebase_id: str, body: SearchLogCreateRequest):
    import uuid
    from agentclaw.knowledgebase.models import SearchLogRecord
    from datetime import datetime

    record = SearchLogRecord(
        id=uuid.uuid4().hex,
        knowledgebase_id=knowledgebase_id,
        query=body.query,
        mode=body.mode,
        strategy=body.strategy,
        top_k=body.top_k,
        hit_count=body.hit_count,
        latency_ms=body.latency_ms,
        hits=body.hits,
        created_at=datetime.utcnow(),
    )
    service = _get_service()
    await service.store.create_search_log(record)
    return {"ok": True, "id": record.id}


@router.delete("/{knowledgebase_id}/search-logs")
async def clear_search_logs(knowledgebase_id: str):
    service = _get_service()
    deleted = await service.store.clear_search_logs(knowledgebase_id)
    return {"ok": True, "deleted": deleted}
