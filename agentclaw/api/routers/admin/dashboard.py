"""
Dashboard API 路由
"""

from fastapi import APIRouter, Body, Query, Depends

from agentclaw.api.schemas.dashboard import (
    AgentSquareApp,
    AgentSquareAppsResponse,
    DashboardStats,
    TemplateLibraryApp,
    TemplateLibraryAppsResponse,
    TemplateLibraryImportRequest,
    TemplateLibraryImportResponse,
    TracesSummary,
    TrendData,
)
from agentclaw.api.schemas.common import APIError, ErrorCode
from agentclaw.api.services.dashboard_service import (
    DashboardService,
    get_dashboard_service,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats, summary="Get dashboard stats")
async def get_dashboard_stats(
    service: DashboardService = Depends(get_dashboard_service),
):
    """Get global dashboard statistics: workflow count, 24h executions, success rate, avg duration."""
    stats = await service.get_dashboard_stats()
    return DashboardStats(**stats)


@router.get("/trends", response_model=TrendData, summary="Get dashboard trends")
async def get_dashboard_trends(
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Get execution trends aggregated by time range."""
    trends = await service.get_dashboard_trends(time_range)
    return TrendData(**trends)


@router.get("/agent-square/apps", response_model=AgentSquareAppsResponse, summary="List Template Library apps (compatibility alias)")
async def list_agent_square_apps(
    service: DashboardService = Depends(get_dashboard_service),
):
    """Compatibility alias: list packaged templates shipped with AgentClaw."""
    apps = [AgentSquareApp(**app) for app in service.list_agent_square_apps()]
    return AgentSquareAppsResponse(apps=apps)


@router.get(
    "/template-library/apps",
    response_model=TemplateLibraryAppsResponse,
    summary="List Template Library apps",
)
async def list_template_library_apps(
    service: DashboardService = Depends(get_dashboard_service),
):
    """List packaged Template Library apps without importing their workflow code."""
    apps = [TemplateLibraryApp(**app) for app in service.list_template_library_apps()]
    return TemplateLibraryAppsResponse(apps=apps)


@router.post(
    "/template-library/apps/{app_id}/import",
    response_model=TemplateLibraryImportResponse,
    summary="Import a Template Library app into the current project",
)
async def import_template_library_app(
    app_id: str,
    request: TemplateLibraryImportRequest = Body(default=TemplateLibraryImportRequest()),
    service: DashboardService = Depends(get_dashboard_service),
):
    """Copy a packaged template into the project and hot-register it as a normal workflow."""
    try:
        result = await service.import_template_library_app(app_id, overwrite=request.overwrite)
    except FileNotFoundError as exc:
        raise APIError(
            error=str(exc),
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )
    except FileExistsError as exc:
        raise APIError(
            error=str(exc),
            code=ErrorCode.INVALID_REQUEST,
            status_code=409,
        )
    except (PermissionError, ValueError) as exc:
        raise APIError(
            error=str(exc),
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )
    except Exception as exc:
        raise APIError(
            error=f"导入模板失败: {exc}",
            code=ErrorCode.OPERATION_FAILED,
            status_code=500,
        )
    return TemplateLibraryImportResponse(**result)
