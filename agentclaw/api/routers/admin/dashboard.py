"""
Dashboard API 路由
"""

from fastapi import APIRouter, Query, Depends

from agentclaw.api.schemas.dashboard import (
    DashboardStats,
    TracesSummary,
    TrendData,
)
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
