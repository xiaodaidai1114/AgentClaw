"""
统一文件下载 API

通过文件 ID 下载任何已存储的文件（通用上传 + 知识库文档）。
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from agentclaw.api.auth.dependencies import authenticate_bearer
from agentclaw.api.files.response import file_response_headers
from agentclaw.api.files.signing import verify_file_access_token
from agentclaw.database.file_storage import get_file_storage

router = APIRouter(tags=["files"])


async def _authorize_file_access(request: Request, file_id: str) -> None:
    signed_token = request.query_params.get("token")
    if verify_file_access_token(file_id, signed_token):
        return

    try:
        principal = await authenticate_bearer(request)
    except HTTPException as exc:
        if signed_token:
            raise HTTPException(status_code=403, detail="Invalid file access token")
        raise exc

    if principal.auth_type != "admin":
        raise HTTPException(status_code=403, detail="Admin token required")


@router.get("/files/{file_id}")
async def get_file(
    request: Request,
    file_id: str,
    download: bool = Query(False),
):
    """
    通过文件 ID 下载文件。

    - 图片/PDF 默认 inline 展示
    - 其他类型默认 attachment 下载
    - ?download=true 强制下载
    - 浏览器嵌入场景可使用短期签名 token，无需 Bearer header
    """
    await _authorize_file_access(request, file_id)

    storage = get_file_storage()
    if not storage:
        raise HTTPException(status_code=503, detail="File storage not available")

    stored = await storage.find_by_id(file_id)
    if not stored:
        raise HTTPException(status_code=404, detail="File not found")

    data = await storage.get_file_bytes(file_id)
    if data is None:
        raise HTTPException(status_code=404, detail="File content not found")

    content_type = stored.mime_type or "application/octet-stream"
    filename = stored.original_name or "file"

    return Response(
        content=data,
        media_type=content_type,
        headers=file_response_headers(filename, content_type, download=download),
    )
