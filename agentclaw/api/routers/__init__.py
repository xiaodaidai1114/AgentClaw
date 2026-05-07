"""
API 路由模块

包含：
- Admin API 路由（/admin/*）
- 工作流 API 路由（/api/*）
"""

from agentclaw.api.routers.admin import router as admin_router

__all__ = [
    "admin_router",
]
