"""
追踪服务 - 封装追踪查询业务逻辑
"""

import json
from typing import Optional, List
from datetime import datetime

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class TraceService:
    """
    追踪服务
    
    封装追踪记录查询等业务逻辑
    """
    
    def __init__(self, tracer=None, registry=None):
        self._tracer = tracer
        self._registry = registry
    
    def _get_registered_workflow_ids(self) -> Optional[List[str]]:
        """获取已注册的工作流 ID 列表"""
        if not self._registry:
            return None
        workflows = self._registry.list_all()
        return [wf.id for wf in workflows]

    @staticmethod
    def _extract_internal_trace_ids(node_logs: List[dict], parent_trace_id: str) -> List[str]:
        """从节点 output_data 中提取内部子工作流 trace_id 引用。"""
        collected: List[str] = []
        seen = set()
        for log in node_logs:
            output_data = log.get("output_data")
            if not isinstance(output_data, dict):
                continue
            for key, value in output_data.items():
                if not isinstance(value, dict):
                    continue
                if not (str(key).startswith("__") and str(key).endswith("_metadata__")):
                    continue
                candidate = value.get("sub_trace_id")
                if not candidate:
                    continue
                trace_id = str(candidate)
                if trace_id == parent_trace_id:
                    continue
                if trace_id in seen:
                    continue
                seen.add(trace_id)
                collected.append(trace_id)
        return collected
    
    async def list_traces(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        limit: int = 20,
        include_internal: bool = True,
    ) -> dict:
        """获取追踪列表。默认包含内部/子智能体执行日志。"""
        if not self._tracer:
            return {"traces": [], "total": 0, "page": page, "limit": limit}
        
        registered_ids = self._get_registered_workflow_ids() if not include_internal else None
        
        if workflow_id:
            if registered_ids and workflow_id not in registered_ids:
                return {"traces": [], "total": 0, "page": page, "limit": limit}
        
        offset = (page - 1) * limit
        
        traces = await self._tracer.list_workflow_logs(
            workflow_id=workflow_id,
            workflow_ids=registered_ids if not workflow_id else None,
            status=status,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        
        for trace in traces:
            for key in ["id", "workflow_id", "thread_id", "user_id"]:
                if key in trace and trace[key] is not None:
                    trace[key] = str(trace[key])
        
        # 批量获取每个 trace 的 token 统计
        trace_ids = [t["id"] for t in traces if t.get("id")]
        token_stats = await self._get_token_stats_batch(trace_ids) if trace_ids else {}
        for trace in traces:
            stats = token_stats.get(trace["id"], {})
            trace["total_tokens"] = stats.get("total_tokens", 0)
            trace["prompt_tokens"] = stats.get("prompt_tokens", 0)
            trace["completion_tokens"] = stats.get("completion_tokens", 0)
            trace["llm_calls"] = stats.get("llm_calls", 0)
        
        total = await self._tracer.count_workflow_logs(
            workflow_id=workflow_id,
            workflow_ids=registered_ids if not workflow_id else None,
            status=status,
            start_time=start_time,
            end_time=end_time,
        )
        
        return {
            "traces": traces,
            "total": total,
            "page": page,
            "limit": limit,
        }
    
    async def _get_token_stats_batch(self, trace_ids: List[str]) -> dict:
        """批量获取 trace 的 token 统计"""
        if not self._tracer or not hasattr(self._tracer, "get_trace_token_stats_batch"):
            return {}

        try:
            return await self._tracer.get_trace_token_stats_batch(trace_ids)
        except Exception as e:
            logger.warning(f"批量获取 token 统计失败: {e}")
            return {}
    
    async def get_trace(self, trace_id: str) -> Optional[dict]:
        """获取追踪详情"""
        if not self._tracer:
            return None
        
        # 验证 UUID 格式
        import uuid
        try:
            uuid.UUID(trace_id)
        except ValueError:
            return None
        
        trace = await self._tracer.get_workflow_log(trace_id)
        if not trace:
            return None
        
        for key in ["id", "workflow_id", "thread_id", "user_id"]:
            if key in trace and trace[key] is not None:
                trace[key] = str(trace[key])
        
        for key in ["input_data", "output_data", "metadata", "node_log_ids"]:
            if key in trace and isinstance(trace[key], str):
                try:
                    trace[key] = json.loads(trace[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        
        node_logs = await self._tracer.get_node_logs(trace_id)
        llm_logs = await self._tracer.get_llm_logs(trace_id)
        
        for log in node_logs:
            for key in ["id", "workflow_log_id", "parent_node_log_id"]:
                if key in log and log[key] is not None:
                    log[key] = str(log[key])
            for key in ["input_data", "output_data", "metadata"]:
                if key in log and isinstance(log[key], str):
                    try:
                        log[key] = json.loads(log[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        
        for log in llm_logs:
            for key in ["id", "workflow_log_id", "node_log_id"]:
                if key in log and log[key] is not None:
                    log[key] = str(log[key])
            for key in ["metadata"]:
                if key in log and isinstance(log[key], str):
                    try:
                        log[key] = json.loads(log[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        
        trace["node_logs"] = node_logs
        trace["llm_logs"] = llm_logs

        # 聚合内部子智能体 trace 引用，便于前端/调用方直接追踪内部执行链
        internal_trace_ids = self._extract_internal_trace_ids(node_logs, trace_id)
        internal_traces: List[dict] = []
        for sub_trace_id in internal_trace_ids:
            sub_trace = await self._tracer.get_workflow_log(sub_trace_id)
            if not sub_trace:
                continue
            for key in ["id", "workflow_id", "thread_id", "user_id"]:
                if key in sub_trace and sub_trace[key] is not None:
                    sub_trace[key] = str(sub_trace[key])
            internal_traces.append(
                {
                    "trace_id": sub_trace.get("id"),
                    "workflow_id": sub_trace.get("workflow_id"),
                    "thread_id": sub_trace.get("thread_id"),
                    "status": sub_trace.get("status"),
                    "duration_ms": sub_trace.get("duration_ms"),
                    "start_time": sub_trace.get("start_time"),
                    "end_time": sub_trace.get("end_time"),
                    "error": sub_trace.get("error"),
                }
            )
        trace["internal_traces"] = internal_traces
        
        return trace
    
    async def get_trace_timeline(self, trace_id: str) -> List[dict]:
        """获取追踪时间线"""
        if not self._tracer:
            return []
        
        # 验证 UUID 格式
        import uuid
        try:
            uuid.UUID(trace_id)
        except ValueError:
            return []
        
        events = []
        
        node_logs = await self._tracer.get_node_logs(trace_id)
        for log in node_logs:
            events.append({
                "timestamp": log.get("start_time"),
                "event_type": "node_start",
                "name": log.get("name"),
                "status": None,
                "metadata": {"node_type": log.get("node_type")},
            })
            if log.get("end_time"):
                events.append({
                    "timestamp": log.get("end_time"),
                    "event_type": "node_end",
                    "name": log.get("name"),
                    "status": log.get("status"),
                    "duration_ms": log.get("duration_ms"),
                    "metadata": {"node_type": log.get("node_type")},
                })
        
        llm_logs = await self._tracer.get_llm_logs(trace_id)
        for log in llm_logs:
            events.append({
                "timestamp": log.get("created_at"),
                "event_type": "llm_call",
                "name": log.get("model_name"),
                "status": log.get("status"),
                "duration_ms": log.get("latency_ms"),
                "metadata": {
                    "model_id": log.get("model_id"),
                    "total_tokens": log.get("total_tokens"),
                },
            })
        
        events.sort(key=lambda x: x["timestamp"] if x["timestamp"] else datetime.min)
        
        return events


def get_trace_service() -> TraceService:
    """获取追踪服务实例"""
    from agentclaw.runtime.tracing import get_db_tracer
    from agentclaw.api.registry import WorkflowRegistry
    
    return TraceService(tracer=get_db_tracer(), registry=WorkflowRegistry)
