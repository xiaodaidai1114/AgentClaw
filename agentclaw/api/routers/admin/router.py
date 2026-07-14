"""
Admin API 主路由

聚合所有子路由，统一前缀 /admin
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException

from agentclaw.api.routers.admin.auth import router as auth_router
from agentclaw.api.routers.admin.workflows import router as workflows_router
from agentclaw.api.routers.admin.traces import router as traces_router
from agentclaw.api.routers.admin.prompts import router as prompts_router
from agentclaw.api.routers.admin.models import router as models_router
from agentclaw.api.routers.admin.audio import router as audio_router
from agentclaw.api.routers.admin.dashboard import router as dashboard_router
from agentclaw.api.routers.admin.debug import router as debug_router
from agentclaw.api.routers.admin.conversations import router as conversations_router
from agentclaw.api.routers.admin.tasks import router as tasks_router
from agentclaw.api.routers.admin.channels import router as channels_router
from agentclaw.api.routers.admin.knowledgebases import router as knowledgebases_router
from agentclaw.api.routers.admin.settings import router as settings_router
from agentclaw.api.routers.admin.public_rooms import router as public_rooms_router
from agentclaw.api.routers.admin.enterprise_tools import router as enterprise_tools_router

# 创建主路由
router = APIRouter(prefix="/admin")

# 注册子路由
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(workflows_router)
router.include_router(traces_router)
router.include_router(prompts_router)
router.include_router(models_router)
router.include_router(audio_router)
router.include_router(debug_router)
router.include_router(conversations_router)
router.include_router(tasks_router)
router.include_router(channels_router)
router.include_router(knowledgebases_router)
router.include_router(settings_router)
router.include_router(public_rooms_router)
router.include_router(enterprise_tools_router)


# 健康检查端点
@router.get("/health", tags=["health"], summary="Admin health check")
async def health_check():
    """Admin API health check endpoint."""
    return {"status": "ok", "service": "admin"}
