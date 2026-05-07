"""
工作流服务 - 封装工作流相关业务逻辑
"""

from typing import Optional, List, Dict
from datetime import datetime, timedelta

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class WorkflowService:
    """
    工作流服务
    
    封装工作流查询、统计等业务逻辑
    """
    
    def __init__(self, registry=None, tracer=None, conversation_service=None):
        self._registry = registry
        self._tracer = tracer
        self._conversation_service = conversation_service

    @staticmethod
    def _empty_trace_summary() -> dict:
        """统一的工作流追踪摘要零值结构。"""
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

    @staticmethod
    def _empty_feedback_summary() -> dict:
        return {
            "like_count": 0,
            "dislike_count": 0,
        }
    
    def list_workflows(self, include_builtin: bool = False) -> List[dict]:
        """获取所有工作流列表"""
        if not self._registry:
            return []
        
        workflows = self._registry.list_all()
        if not include_builtin:
            workflows = [wf for wf in workflows if wf.id != "__builtin__"]
        return [self._to_info(wf) for wf in workflows]
    
    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        """获取工作流详情"""
        if not self._registry:
            return None
        
        wf = self._registry.get(workflow_id)
        if not wf:
            return None
        
        return self._to_info(wf)
    
    def get_workflow_structure(self, workflow_id: str) -> Optional[dict]:
        """获取工作流结构（用于可视化）"""
        if not self._registry:
            return None
        
        wf = self._registry.get(workflow_id)
        if not wf:
            return None
        
        return wf.get_structure()
    
    async def get_workflow_stats(
        self,
        workflow_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """获取工作流统计数据"""
        if not self._tracer:
            return {}
        
        return await self._tracer.get_workflow_stats(workflow_id, start_date, end_date)

    async def get_workflow_trace_summary(self, workflow_id: str) -> dict:
        """获取工作流在执行追踪口径下的汇总摘要。"""
        zero_summary = self._empty_trace_summary()
        if not self._tracer or not hasattr(self._tracer, "get_traces_summary"):
            return zero_summary

        try:
            return await self._tracer.get_traces_summary(workflow_id=workflow_id)
        except Exception:
            return zero_summary

    async def get_workflow_feedback_summary(self, workflow_id: str) -> dict:
        if not self._conversation_service:
            return self._empty_feedback_summary()
        try:
            return await self._conversation_service.get_feedback_summary(workflow_id)
        except Exception:
            return self._empty_feedback_summary()

    async def get_workflow_feedback_summary_map(
        self,
        workflow_ids: List[str],
    ) -> Dict[str, dict]:
        workflow_ids = [workflow_id for workflow_id in workflow_ids if workflow_id]
        if not workflow_ids:
            return {}
        empty_map = {
            workflow_id: self._empty_feedback_summary()
            for workflow_id in workflow_ids
        }
        if not self._conversation_service:
            return empty_map
        try:
            return await self._conversation_service.get_feedback_summary_map(workflow_ids)
        except Exception:
            return empty_map

    @staticmethod
    def build_workflow_list_stats(stats: dict) -> dict:
        """统一工作流列表页/卡片使用的统计结构。"""
        execution_count = stats.get("total_count", 0)
        return {
            "execution_count": execution_count,
            "success_rate": stats.get("success_rate") if execution_count > 0 else None,
            "avg_duration_ms": stats.get("avg_duration_ms"),
            "total_tokens": stats.get("total_tokens", 0),
            "running_count": stats.get("running_count", 0),
            "last_execution_time": stats.get("last_execution_time"),
        }

    async def list_workflows_with_stats(
        self,
        include_builtin: bool = False,
        time_range: str = "24h",
    ) -> List[dict]:
        """获取带列表摘要统计的工作流列表。"""
        workflows = self.list_workflows(include_builtin=include_builtin)
        feedback_map = await self.get_workflow_feedback_summary_map(
            [workflow["id"] for workflow in workflows]
        )
        result = []
        for workflow in workflows:
            stats = await self.get_workflow_stats_summary(workflow["id"], time_range=time_range)
            workflow["stats_24h"] = self.build_workflow_list_stats(stats)
            feedback = feedback_map.get(workflow["id"], self._empty_feedback_summary())
            workflow["like_count"] = feedback.get("like_count", 0)
            workflow["dislike_count"] = feedback.get("dislike_count", 0)
            result.append(workflow)
        return result

    @staticmethod
    def get_time_range_window(time_range: str) -> tuple[datetime, datetime]:
        """Return the start/end window for dashboard summary ranges."""
        end_date = datetime.now()
        if time_range == "7d":
            start_date = end_date - timedelta(days=7)
        elif time_range == "30d":
            start_date = end_date - timedelta(days=30)
        else:
            start_date = end_date - timedelta(hours=24)
        return start_date, end_date
    
    async def get_workflow_stats_summary(
        self,
        workflow_id: str,
        time_range: str = "24h",
    ) -> dict:
        """
        获取工作流统计摘要（默认近 24 小时）。

        用于工作流列表卡片/仪表盘展示，支持 24h、7d、30d。
        """
        start_date, end_date = self.get_time_range_window(time_range)

        stats = await self.get_workflow_stats(workflow_id, start_date, end_date)
        stats["time_range"] = time_range
        stats["last_execution_time"] = await self.get_last_execution_time(
            workflow_id,
            start_date=start_date,
            end_date=end_date,
        )
        
        return stats
    
    async def get_last_execution_time(
        self,
        workflow_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """获取工作流最后执行时间"""
        if not self._tracer:
            return None

        if not start_date and not end_date and hasattr(self._tracer, "get_last_workflow_execution_time"):
            return await self._tracer.get_last_workflow_execution_time(workflow_id)

        logs = await self._tracer.list_workflow_logs(
            workflow_id=workflow_id,
            start_time=start_date,
            end_time=end_date,
            limit=1,
            offset=0,
        )
        return logs[0].get("start_time") if logs else None
    
    async def get_workflow_trends(
        self,
        workflow_id: str,
        time_range: str = "24h",
    ) -> dict:
        """获取工作流执行趋势"""
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
        
        trends = await self._tracer.get_workflow_trends(
            workflow_id=workflow_id,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )
        
        return {
            "time_range": time_range,
            "data_points": trends.get("data_points", []),
            "duration_points": trends.get("duration_points", []),
        }
    
    def update_node_model(
        self,
        workflow_id: str,
        node_id: str,
        model_id: str,
    ) -> dict:
        """更新节点使用的模型"""
        if not self._registry:
            return {"success": False, "message": "工作流注册表不可用"}
        
        wf = self._registry.get(workflow_id)
        if not wf:
            return {"success": False, "message": f"工作流 '{workflow_id}' 不存在"}
        
        if not hasattr(wf, "_nodes") or node_id not in wf._nodes:
            return {"success": False, "message": f"节点 '{node_id}' 不存在"}
        
        node = wf._nodes[node_id]
        
        if not hasattr(node, "model_id"):
            return {"success": False, "message": f"节点 '{node_id}' 不是 LLM 节点"}
        
        try:
            node.model_id = model_id
            return {"success": True, "message": "模型切换成功"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def _to_info(self, workflow) -> dict:
        """转换为工作流信息"""
        is_builtin = workflow.id == "__builtin__" or bool(getattr(workflow, "is_builtin", False))
        return {
            "id": workflow.id,
            "name": workflow.name,
            "version": workflow.version,
            "description": getattr(workflow, "description", ""),
            "node_count": len(workflow._nodes) if hasattr(workflow, "_nodes") else 0,
            "is_builtin": is_builtin,
            "public_share_enabled": False if is_builtin else bool(getattr(workflow, "public_share_enabled", False)),
            "public_share_token": "" if is_builtin else (getattr(workflow, "public_share_token", "") or ""),
            "rate_limit": getattr(workflow, "rate_limit", "") or "",
            "public_conversation_limit": getattr(workflow, "public_conversation_limit", 20) or 20,
            "public_message_limit": getattr(workflow, "public_message_limit", 200) or 200,
            "inject_as_agentic_capability": bool(getattr(workflow, "inject_as_agentic_capability", True)),
            "workflow_api_key_set": bool(getattr(workflow, "workflow_api_key", None)),
            "like_count": 0,
            "dislike_count": 0,
        }


def get_workflow_service() -> WorkflowService:
    """获取工作流服务实例"""
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.api.services.conversation_service import get_conversation_service
    from agentclaw.runtime.tracing import get_db_tracer
    
    return WorkflowService(
        registry=WorkflowRegistry,
        tracer=get_db_tracer(),
        conversation_service=get_conversation_service(),
    )
