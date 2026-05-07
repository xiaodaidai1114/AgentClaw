"""
File upload API router

Handles file uploads for chat attachments. Requires database availability.
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request

from agentclaw.api.auth.dependencies import (
    require_admin_auth,
    require_workflow_or_admin_auth,
)
from agentclaw.api.upload_limits import (
    UploadTooLarge,
    enforce_upload_content_length,
    read_upload_file_limited,
)
from agentclaw.api.schemas.upload import UploadStatusResponse, UploadFileResponse
from agentclaw.logger.config import get_logger
from agentclaw.config import get_config

logger = get_logger(__name__)

router = APIRouter(tags=["upload"])


@router.get(
    "/upload/status",
    response_model=UploadStatusResponse,
    summary="Check upload availability",
    description="Check if file upload is available (requires database)",
    dependencies=[Depends(require_workflow_or_admin_auth)],
)
async def upload_status():
    """Check file upload availability"""
    from agentclaw.database import get_file_storage

    storage = get_file_storage()
    available = storage is not None and storage.db is not None and storage.db.pg_pool is not None

    config = get_config()
    max_size = config.upload.max_size_bytes

    return UploadStatusResponse(available=available, max_size=max_size)


@router.post(
    "/upload",
    response_model=UploadFileResponse,
    summary="Upload file attachment",
    description="Upload a file attachment for chat conversations. Requires authentication and database.",
    responses={
        401: {"description": "Unauthorized - invalid or missing API key"},
        413: {"description": "File too large"},
        503: {"description": "Database not available"},
    },
)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    _principal=Depends(require_workflow_or_admin_auth),
):
    """
    Upload file attachment.

    Requires database availability. Files are deduplicated by hash.
    Original filename is preserved in database.
    """
    # Check DB
    from agentclaw.database import get_file_storage

    storage = get_file_storage()
    if not storage or not storage.db or not storage.db.pg_pool:
        raise HTTPException(
            status_code=503,
            detail="File upload requires database support. Database not configured.",
        )

    config = get_config()
    max_size = config.upload.max_size_bytes
    enforce_upload_content_length(request, max_size)

    try:
        data = await read_upload_file_limited(file, max_size)
    except UploadTooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds limit ({config.upload.max_size_mb}MB)",
        )

    # Save
    original_name = file.filename or "unnamed"
    stored = await storage.save(data, original_name, file.content_type)

    logger.info(f"File uploaded: {original_name} -> {stored.file_path} ({stored.size} bytes)")

    return UploadFileResponse(
        id=stored.id,
        original_name=stored.original_name,
        file_path=stored.file_path,
        mime_type=stored.mime_type,
        size=stored.size,
    )


@router.get(
    "/upload/list",
    summary="List uploaded files",
    description="List all uploaded files with original names. Used by skill-tools to show upload directory contents.",
    dependencies=[Depends(require_admin_auth)],
)
async def list_uploaded_files():
    """List all uploaded files from database"""
    from agentclaw.database import get_file_storage

    storage = get_file_storage()
    if not storage or not storage.db or not storage.db.pg_pool:
        return {"files": []}

    try:
        rows = await storage.db.pg_fetch(
            "SELECT id, original_name, file_path, mime_type, size FROM files WHERE file_path LIKE 'uploads/%' ORDER BY id"
        )
        files = [
            {
                "id": str(row["id"]),
                "original_name": row["original_name"],
                "file_path": row["file_path"],
                "mime_type": row["mime_type"],
                "size": row["size"],
            }
            for row in rows
        ]
        return {"files": files}
    except Exception as e:
        logger.warning(f"列出上传文件失败: {e}")
        return {"files": []}
