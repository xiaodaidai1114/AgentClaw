"""
任务管理 API - 用于中止运行中的工作流任务
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CancelTaskRequest(BaseModel):
    reason: Optional[str] = "用户中止"


@router.post("/{task_id}/cancel", summary="Cancel task")
async def cancel_task(task_id: str, req: Optional[CancelTaskRequest] = None) -> dict:
    """Cancel a running workflow task."""
    from agentclaw.api.server import TaskManager
    
    reason = req.reason if req else "用户中止"
    task_manager = TaskManager.get_instance()
    
    success = await task_manager.cancel(task_id, reason)
    
    if success:
        logger.info(f"任务已中止: {task_id}, 原因: {reason}")
        return {"success": True, "message": f"任务已中止: {reason}"}
    else:
        return {"success": False, "message": "任务不存在或已完成"}


@router.get("", summary="List running tasks")
async def list_running_tasks(workflow_id: Optional[str] = None) -> dict:
    """List currently running workflow tasks."""
    from agentclaw.api.server import TaskManager
    
    task_manager = TaskManager.get_instance()
    tasks = await task_manager.get_running_tasks(workflow_id)
    
    return {"tasks": tasks}


@router.delete("/cleanup", summary="Cleanup done tasks")
async def cleanup_done_tasks() -> dict:
    """Clean up completed tasks from the task manager."""
    from agentclaw.api.server import TaskManager
    
    task_manager = TaskManager.get_instance()
    count = await task_manager.cleanup_done_tasks()
    
    return {"cleaned": count}
