"""
Public API router

Aggregates all public-facing API routes under /api prefix.
"""

from fastapi import APIRouter

from agentclaw.api.routers.public.execution import router as execution_router
from agentclaw.api.routers.public.upload import router as upload_router
from agentclaw.api.routers.public.files import router as files_router
from agentclaw.api.routers.public.conversations import router as conversations_router

router = APIRouter(prefix="/api")

router.include_router(execution_router)
router.include_router(upload_router)
router.include_router(files_router)
router.include_router(conversations_router)
