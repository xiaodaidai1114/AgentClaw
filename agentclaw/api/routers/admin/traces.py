"""
追踪 API 路由
"""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Query, Depends

from agentclaw.api.schemas import (
    TraceListResponse,
    TraceDetail,
    TraceRecord,
    NodeLog,
    LLMLog,
    TraceTimelineResponse,
    TraceTimelineEvent,
)
from agentclaw.api.schemas.common import ErrorCode, APIError
from agentclaw.api.schemas.dashboard import TracesSummary
from agentclaw.api.services import get_trace_service, TraceService
from agentclaw.api.services.dashboard_service import (
    DashboardService,
    get_dashboard_service,
)

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("/summary", response_model=TracesSummary, summary="Get traces summary")
async def get_traces_summary(
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    status: Optional[str] = Query(None, description="Filter by status: running, success, error, timeout"),
    start_time: Optional[datetime] = Query(None, description="Start time filter"),
    end_time: Optional[datetime] = Query(None, description="End time filter"),
    include_internal: bool = Query(True, description="Include internal/sub-agent traces"),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Get overall trace statistics: total, success, error, running counts and avg duration."""
    summary = await service.get_traces_summary(
        workflow_id=workflow_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        include_internal=include_internal,
    )
    return TracesSummary(**summary)


@router.get("", response_model=TraceListResponse, summary="List traces")
async def list_traces(
    workflow_id: Optional[str] = Query(None, description="Filter by workflow ID"),
    status: Optional[str] = Query(None, description="Filter by status: running, success, error, timeout"),
    start_time: Optional[datetime] = Query(None, description="Start time filter"),
    end_time: Optional[datetime] = Query(None, description="End time filter"),
    include_internal: bool = Query(True, description="Include internal/sub-agent traces"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    service: TraceService = Depends(get_trace_service),
):
    """List traces with pagination and filtering."""
    result = await service.list_traces(
        workflow_id=workflow_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        limit=limit,
        include_internal=include_internal,
    )
    
    traces = [TraceRecord(**t) for t in result["traces"]]
    
    return TraceListResponse(
        traces=traces,
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
    )


@router.get("/{trace_id}", response_model=TraceDetail, summary="Get trace detail")
async def get_trace(
    trace_id: str,
    service: TraceService = Depends(get_trace_service),
):
    """Get full trace detail including node logs and LLM call logs."""
    trace = await service.get_trace(trace_id)
    if not trace:
        raise APIError(
            error=f"追踪 '{trace_id}' 不存在",
            code=ErrorCode.TRACE_NOT_FOUND,
            status_code=404,
        )
    
    # 转换节点日志
    node_logs = [NodeLog(**n) for n in trace.get("node_logs", [])]
    
    # 转换 LLM 日志
    llm_logs = [LLMLog(**l) for l in trace.get("llm_logs", [])]
    
    return TraceDetail(
        id=trace["id"],
        workflow_id=trace.get("workflow_id"),
        thread_id=trace.get("thread_id"),
        user_id=trace.get("user_id"),
        name=trace.get("name", ""),
        status=trace.get("status", "unknown"),
        duration_ms=trace.get("duration_ms"),
        start_time=trace.get("start_time"),
        end_time=trace.get("end_time"),
        error=trace.get("error"),
        input_data=trace.get("input_data"),
        output_data=trace.get("output_data"),
        node_logs=node_logs,
        llm_logs=llm_logs,
        internal_traces=trace.get("internal_traces", []),
    )


@router.get("/{trace_id}/timeline", response_model=TraceTimelineResponse, summary="Get trace timeline")
async def get_trace_timeline(
    trace_id: str,
    service: TraceService = Depends(get_trace_service),
):
    """Get chronologically ordered execution events for a trace."""
    events = await service.get_trace_timeline(trace_id)
    
    return TraceTimelineResponse(
        trace_id=trace_id,
        events=[TraceTimelineEvent(**e) for e in events],
    )
