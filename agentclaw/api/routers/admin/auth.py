"""
认证 API 路由
"""

from fastapi import APIRouter
from pydantic import BaseModel

from agentclaw.api.auth import AdminTokenManager

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenVerifyRequest(BaseModel):
    """Token 验证请求"""
    token: str


class TokenVerifyResponse(BaseModel):
    """Token 验证响应"""
    valid: bool


@router.post("/verify", response_model=TokenVerifyResponse, summary="Verify admin token")
async def verify_token(request: TokenVerifyRequest):
    """Verify an admin token's validity."""
    manager = AdminTokenManager.get_instance()
    valid = manager.verify(request.token)
    return TokenVerifyResponse(valid=valid)
