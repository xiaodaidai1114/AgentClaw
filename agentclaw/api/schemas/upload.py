"""
File upload request/response schemas
"""

from pydantic import BaseModel, Field


class UploadStatusResponse(BaseModel):
    """Upload availability status"""
    available: bool = Field(..., description="Whether file upload is available")
    max_size: int = Field(..., description="Maximum file size in bytes")


class UploadFileResponse(BaseModel):
    """File upload response"""
    id: str = Field(..., description="File ID")
    original_name: str = Field(..., description="Original filename")
    file_path: str = Field(..., description="Stored file path")
    mime_type: str = Field(..., description="MIME type")
    size: int = Field(..., description="File size in bytes")
