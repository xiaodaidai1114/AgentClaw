"""
Admin API 路由模块

每个资源独立路由文件
"""

from agentclaw.api.routers.admin.auth import router as auth_router
from agentclaw.api.routers.admin.workflows import router as workflows_router
from agentclaw.api.routers.admin.traces import router as traces_router
from agentclaw.api.routers.admin.prompts import router as prompts_router
from agentclaw.api.routers.admin.models import router as models_router
from agentclaw.api.routers.admin.dashboard import router as dashboard_router
from agentclaw.api.routers.admin.conversations import router as conversations_router
from agentclaw.api.routers.admin.knowledgebases import router as knowledgebases_router
from agentclaw.api.routers.admin.router import router

__all__ = [
    "router",
    "auth_router",
    "workflows_router",
    "traces_router",
    "prompts_router",
    "models_router",
    "dashboard_router",
    "conversations_router",
    "knowledgebases_router",
]
