"""
定时任务模块 - API 路由

提供定时任务的 CRUD REST API。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from agentclaw.api.auth.dependencies import require_admin_auth
from agentclaw.logger.config import get_logger
from agentclaw.utils.security import safe_compare_digest
from agentclaw.scheduler.models import (
    CreateJobRequest,
    JobExecutionListResponse,
    JobExecutionResponse,
    JobListResponse,
    JobResponse,
    JobStatus,
    TriggerJobResponse,
    UpdateJobRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


def _get_scheduler():
    """获取调度器实例"""
    from agentclaw.scheduler.scheduler import WorkflowScheduler

    instance = WorkflowScheduler.get_instance()
    if not instance:
        return None
    return instance


def _job_to_response(job) -> dict:
    """ScheduledJob → JobResponse dict"""
    return JobResponse(
        id=job.id,
        name=job.name,
        description=job.description,
        workflow_id=job.workflow_id,
        trigger=job.trigger,
        inputs=job.inputs,
        status=job.status,
        config=job.config,
        webhook=job.webhook,
        created_at=job.created_at,
        updated_at=job.updated_at,
        last_run_at=job.last_run_at,
        next_run_at=job.next_run_at,
        run_count=job.run_count,
        fail_count=job.fail_count,
    ).model_dump(mode="json")


# ── Jobs CRUD ─────────────────────────────────────────


@router.post("/jobs", dependencies=[Depends(require_admin_auth)])
async def create_job(request: CreateJobRequest):
    """创建定时任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    try:
        job = await scheduler.add_job(request)
        return JSONResponse(status_code=201, content=_job_to_response(job))
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e), "code": "VALIDATION_ERROR"},
        )
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "code": "OPERATION_FAILED"},
        )


@router.get("/jobs", dependencies=[Depends(require_admin_auth)])
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_id: Optional[str] = Query(None, description="Filter by workflow"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """列取定时任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid status: {status}", "code": "VALIDATION_ERROR"},
            )

    jobs, total = await scheduler.list_jobs(job_status, workflow_id, page, limit)
    return JSONResponse(
        content=JobListResponse(
            jobs=[JobResponse.model_validate(_job_to_response(j)) for j in jobs],
            total=total,
        ).model_dump(mode="json")
    )


@router.get("/jobs/{job_id}", dependencies=[Depends(require_admin_auth)])
async def get_job(job_id: str):
    """获取任务详情"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job = await scheduler.get_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(content=_job_to_response(job))


@router.put("/jobs/{job_id}", dependencies=[Depends(require_admin_auth)])
async def update_job(job_id: str, request: UpdateJobRequest):
    """更新任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job = await scheduler.update_job(job_id, request)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(content=_job_to_response(job))


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_admin_auth)])
async def delete_job(job_id: str):
    """删除任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    deleted = await scheduler.remove_job(job_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(content={"success": True})


@router.post("/jobs/{job_id}/pause", dependencies=[Depends(require_admin_auth)])
async def pause_job(job_id: str):
    """暂停任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job = await scheduler.pause_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(content=_job_to_response(job))


@router.post("/jobs/{job_id}/resume", dependencies=[Depends(require_admin_auth)])
async def resume_job(job_id: str):
    """恢复任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job = await scheduler.resume_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(content=_job_to_response(job))


@router.post("/jobs/{job_id}/trigger", dependencies=[Depends(require_admin_auth)])
async def trigger_job(job_id: str):
    """立即触发任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    try:
        execution_id = await scheduler.trigger_job(job_id, trigger_source="manual")
        return JSONResponse(
            content=TriggerJobResponse(
                execution_id=execution_id,
                message="Job triggered successfully",
            ).model_dump()
        )
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e), "code": "NOT_FOUND"},
        )


# ── Webhook ───────────────────────────────────────────


@router.post("/jobs/{job_id}/webhook")
async def webhook_trigger(job_id: str, request: Request):
    """Webhook 触发任务"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    job = await scheduler.get_job(job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"error": f"Job '{job_id}' not found", "code": "NOT_FOUND"},
        )

    # 检查 webhook 是否启用
    if not job.webhook.enabled:
        return JSONResponse(
            status_code=400,
            content={"error": "Webhook is not enabled for this job", "code": "WEBHOOK_DISABLED"},
        )

    # 验证 secret. Public webhook endpoints must always be protected by a
    # job-level secret; otherwise a guessed job_id could trigger the workflow.
    if not job.webhook.secret:
        return JSONResponse(
            status_code=403,
            content={
                "error": "Webhook secret is required for public triggers",
                "code": "WEBHOOK_SECRET_REQUIRED",
            },
        )

    provided_secret = request.headers.get("X-Webhook-Secret", "")
    if not safe_compare_digest(provided_secret, job.webhook.secret):
        return JSONResponse(
            status_code=403,
            content={"error": "Invalid webhook secret", "code": "FORBIDDEN"},
        )

    # 解析 inputs
    override_inputs = None
    if job.webhook.allow_input_override:
        try:
            body = await request.json()
            if isinstance(body, dict):
                override_inputs = body
        except Exception:
            pass  # 空 body 或非 JSON，使用默认 inputs

    try:
        execution_id = await scheduler.trigger_job(
            job_id,
            trigger_source="webhook",
            override_inputs=override_inputs,
        )
        return JSONResponse(
            content=TriggerJobResponse(
                execution_id=execution_id,
                message="Job triggered via webhook",
            ).model_dump()
        )
    except ValueError as e:
        return JSONResponse(
            status_code=404,
            content={"error": str(e), "code": "NOT_FOUND"},
        )


# ── Executions ────────────────────────────────────────


def _execution_to_response(e) -> JobExecutionResponse:
    """JobExecution → JobExecutionResponse"""
    return JobExecutionResponse(
        id=e.id,
        job_id=e.job_id,
        status=e.status,
        trigger_source=e.trigger_source,
        started_at=e.started_at,
        ended_at=e.ended_at,
        duration_ms=e.duration_ms,
        inputs=e.inputs,
        outputs=e.outputs,
        error=e.error,
        retry_count=e.retry_count,
    )


@router.get("/jobs/{job_id}/executions", dependencies=[Depends(require_admin_auth)])
async def list_executions(
    job_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """获取执行历史"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    executions, total = await scheduler.list_executions(job_id, page, limit)
    return JSONResponse(
        content=JobExecutionListResponse(
            executions=[_execution_to_response(e) for e in executions],
            total=total,
            page=page,
            limit=limit,
        ).model_dump(mode="json")
    )


@router.get(
    "/jobs/{job_id}/executions/{execution_id}",
    dependencies=[Depends(require_admin_auth)],
)
async def get_execution(job_id: str, execution_id: str):
    """获取执行详情"""
    scheduler = _get_scheduler()
    if not scheduler:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not available", "code": "SCHEDULER_NOT_AVAILABLE"},
        )

    execution = await scheduler.get_execution(execution_id)
    if not execution or execution.job_id != job_id:
        return JSONResponse(
            status_code=404,
            content={"error": "Execution not found", "code": "NOT_FOUND"},
        )

    return JSONResponse(
        content=_execution_to_response(execution).model_dump(mode="json")
    )
