"""
Dashboard 服务 - 封装仪表盘统计业务逻辑
"""

from datetime import datetime, timedelta

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class DashboardService:
    """Dashboard 服务"""
    
    def __init__(self, registry=None, tracer=None):
        self._registry = registry
        self._tracer = tracer

    @staticmethod
    def _empty_trace_summary() -> dict:
        """统一的追踪摘要零值结构。"""
        return {
            "total": 0,
            "success": 0,
            "error": 0,
            "running": 0,
            "avg_duration_ms": None,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    
    async def get_dashboard_stats(self) -> dict:
        """获取仪表盘全局统计（只统计已注册工作流）"""
        workflow_ids = None
        workflow_count = 0
        if self._registry:
            workflows = self._registry.list_all()
            workflow_count = len(workflows)
            workflow_ids = [wf.id for wf in workflows]
        
        execution_count_24h = 0
        success_rate = 0.0
        avg_duration_ms = None
        running_count = 0
        
        if workflow_ids:
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=24)

            summary = await self.get_traces_summary(
                start_time=start_date,
                end_time=end_date,
                include_internal=False,
            )
            success = summary.get("success", 0)
            error = summary.get("error", 0)
            completed = success + error

            execution_count_24h = summary.get("total", 0)
            success_rate = (success / completed * 100) if completed > 0 else 0.0
            avg_duration_ms = summary.get("avg_duration_ms")
            running_count = summary.get("running", 0)
        
        return {
            "workflow_count": workflow_count,
            "execution_count_24h": execution_count_24h,
            "success_rate": success_rate,
            "avg_duration_ms": avg_duration_ms,
            "running_count": running_count,
        }
    
    async def get_traces_summary(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        include_internal: bool = True,
    ) -> dict:
        """获取追踪统计摘要。默认包含内部/子智能体执行日志。"""
        zero_summary = self._empty_trace_summary()
        if not self._tracer:
            return zero_summary
        
        workflow_ids = None
        if self._registry and not include_internal:
            workflows = self._registry.list_all()
            workflow_ids = [wf.id for wf in workflows]
            if workflow_id and workflow_id not in workflow_ids:
                return zero_summary
        
        summary = await self._tracer.get_traces_summary(
            workflow_id=workflow_id,
            workflow_ids=workflow_ids if not workflow_id else None,
            status=status,
            start_time=start_time,
            end_time=end_time,
        )
        
        return {
            "total": summary.get("total", 0),
            "success": summary.get("success", 0),
            "error": summary.get("error", 0),
            "running": summary.get("running", 0),
            "avg_duration_ms": summary.get("avg_duration_ms"),
            "total_tokens": summary.get("total_tokens", 0),
            "prompt_tokens": summary.get("prompt_tokens", 0),
            "completion_tokens": summary.get("completion_tokens", 0),
        }
    
    async def get_dashboard_trends(
        self,
        time_range: str = "24h",
    ) -> dict:
        """获取仪表盘趋势数据"""
        if not self._tracer:
            return {
                "time_range": time_range,
                "data_points": [],
                "duration_points": [],
            }
        
        end_date = datetime.now()
        if time_range == "7d":
            start_date = end_date - timedelta(days=7)
            interval = "day"
        elif time_range == "30d":
            start_date = end_date - timedelta(days=30)
            interval = "day"
        else:  # 24h
            start_date = end_date - timedelta(hours=24)
            interval = "hour"
        
        trends = await self._tracer.get_execution_trends(
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )
        
        return {
            "time_range": time_range,
            "data_points": trends.get("data_points", []),
            "duration_points": trends.get("duration_points", []),
        }


def get_dashboard_service() -> DashboardService:
    """获取 Dashboard 服务实例"""
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.runtime.tracing import get_db_tracer
    
    return DashboardService(
        registry=WorkflowRegistry,
        tracer=get_db_tracer(),
    )
