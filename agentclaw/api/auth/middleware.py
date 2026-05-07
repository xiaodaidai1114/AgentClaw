"""
统一认证中间件

提供：
- Admin API Token 认证
- 工作流 API Key 认证
- 白名单路径配置
"""

from __future__ import annotations
from typing import Set, Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from agentclaw.api.auth.token import AdminTokenManager
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


async def verify_admin_token(request: Request) -> bool:
    """
    验证请求中的 Admin Token
    
    从 Authorization Header 中提取 Token 并验证
    
    Args:
        request: FastAPI 请求对象
        
    Returns:
        Token 是否有效
        
    Raises:
        HTTPException: Token 无效或缺失时抛出 401
    """
    token = None
    
    # 优先从 Authorization Header 获取
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # 去掉 "Bearer " 前缀
    
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header"
        )
    
    manager = AdminTokenManager.get_instance()
    
    if not manager.verify(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )
    
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """
    统一认证中间件
    
    支持：
    - Admin API Token 认证（/admin/* 路径）
    - 工作流 API Key 认证（可选）
    - 白名单路径配置
    
    Example:
        app = FastAPI()
        app.add_middleware(AuthMiddleware)
    """
    
    # Admin API 白名单路径（不需要认证）
    ADMIN_WHITELIST: Set[str] = {
        "/admin/auth/verify",
        "/admin/health",
    }
    
    # 全局白名单路径
    GLOBAL_WHITELIST: Set[str] = {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
    
    def __init__(
        self,
        app,
        api_key_manager=None,
        allow_internal_relay: bool = False,
    ):
        """
        初始化中间件
        
        Args:
            app: FastAPI 应用
            api_key_manager: 可选的 APIKeyManager 实例（用于工作流 API 认证）
            allow_internal_relay: 仅独立本机 relay 应用可启用；公网应用保持关闭
        """
        super().__init__(app)
        self.api_key_manager = api_key_manager
        self.allow_internal_relay = allow_internal_relay
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """处理请求"""
        path = request.url.path

        if path.startswith("/_internal/"):
            if not self.allow_internal_relay:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Not found"},
                )
            return await self._handle_internal_relay(request, call_next, path)

        # 全局白名单，直接放行
        if path in self.GLOBAL_WHITELIST:
            return await call_next(request)

        # Admin API 路径
        if path.startswith("/admin"):
            return await self._handle_admin_auth(request, call_next, path)

        # 其他路径（工作流 API 等），直接放行
        # 工作流 API 的认证在路由层处理（因为需要 workflow_id）
        return await call_next(request)
    
    async def _handle_internal_relay(
        self,
        request: Request,
        call_next,
        path: str,
    ) -> Response:
        """
        内部 API 中转入口

        - 只允许 127.0.0.1 / ::1 调用，隔绝所有外部访问
        - 自动注入 Admin Token auth header
        - 去掉 /_internal 前缀后转发到真实路由
        """
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1"):
            return JSONResponse(
                status_code=403,
                content={"error": "Internal relay: access denied"},
            )

        # 去掉 /_internal 前缀: /_internal/admin/workflows -> /admin/workflows
        real_path = path[len("/_internal"):]
        request.scope["path"] = real_path

        # 自动注入 auth header
        manager = AdminTokenManager.get_instance()
        headers = [
            (k, v)
            for k, v in request.scope["headers"]
            if k != b"authorization"
        ]
        headers.append((b"authorization", f"Bearer {manager.token}".encode()))
        request.scope["headers"] = headers

        return await call_next(request)

    async def _handle_admin_auth(
        self, 
        request: Request, 
        call_next, 
        path: str
    ) -> Response:
        """处理 Admin API 认证"""
        # 白名单路径，直接放行
        if path in self.ADMIN_WHITELIST:
            return await call_next(request)
        
        # 验证 Token
        try:
            await verify_admin_token(request)
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={"error": e.detail}
            )
        
        return await call_next(request)


# 便捷函数
def add_auth_middleware(app, api_key_manager=None):
    """
    添加认证中间件到 FastAPI 应用
    
    Example:
        app = FastAPI()
        add_auth_middleware(app)
    """
    app.add_middleware(AuthMiddleware, api_key_manager=api_key_manager)
    return app
