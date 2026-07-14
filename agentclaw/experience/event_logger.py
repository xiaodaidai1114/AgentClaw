"""
EventLogger - 事件记录器

构造事件 → 应用隐私脱敏（默认开启）→ 写入 TrajectoryStore。
提供 task_started / tool_called / agent_responded / task_failed 四类便捷方法。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .event_schema import (
    AgentRespondedEvent,
    BaseEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    ToolCalledEvent,
    Trajectory,
)
from .privacy_filter import sanitize_dict, sanitize_text
from .trajectory_store import TrajectoryStore


class EventLogger:
    """事件记录器：构造事件 → 脱敏 → 写入存储"""

    def __init__(
        self,
        store: Optional[TrajectoryStore] = None,
        *,
        privacy_enabled: bool = True,
    ) -> None:
        self.store = store or TrajectoryStore()
        self.privacy_enabled = privacy_enabled

    # ------------------------------------------------------------------
    # 脱敏辅助
    # ------------------------------------------------------------------
    def _text(self, value: str) -> str:
        return sanitize_text(value) if self.privacy_enabled else value

    def _dict(self, value: Dict[str, Any]) -> Dict[str, Any]:
        return sanitize_dict(value) if self.privacy_enabled else value

    # ------------------------------------------------------------------
    # 便捷记录方法
    # ------------------------------------------------------------------
    def log_task_started(
        self,
        agent_id: str,
        task_id: str,
        *,
        user_request: str = "",
        agent_version: str = "",
    ) -> TaskStartedEvent:
        ev = TaskStartedEvent(
            agent_id=agent_id,
            task_id=task_id,
            agent_version=agent_version,
            user_request=self._text(user_request),
        )
        self.store.record_event(ev)
        return ev

    def log_tool_called(
        self,
        agent_id: str,
        task_id: str,
        tool_name: str,
        *,
        tool_input: Optional[Dict[str, Any]] = None,
        tool_output: str = "",
        success: bool = True,
        latency_ms: float = 0.0,
    ) -> ToolCalledEvent:
        ev = ToolCalledEvent(
            agent_id=agent_id,
            task_id=task_id,
            tool_name=tool_name,
            tool_input=self._dict(tool_input or {}),
            tool_output=self._text(tool_output),
            success=success,
            latency_ms=latency_ms,
        )
        self.store.record_event(ev)
        return ev

    def log_agent_responded(
        self,
        agent_id: str,
        task_id: str,
        *,
        response: str = "",
        confidence: float = 0.0,
    ) -> AgentRespondedEvent:
        ev = AgentRespondedEvent(
            agent_id=agent_id,
            task_id=task_id,
            response=self._text(response),
            confidence=confidence,
        )
        self.store.record_event(ev)
        return ev

    def log_task_failed(
        self,
        agent_id: str,
        task_id: str,
        *,
        error_type: str = "",
        error_message: str = "",
        failed_step: str = "",
    ) -> TaskFailedEvent:
        ev = TaskFailedEvent(
            agent_id=agent_id,
            task_id=task_id,
            error_type=error_type,
            error_message=self._text(error_message),
            failed_step=failed_step,
        )
        self.store.record_event(ev)
        return ev

    def log_event(self, event: BaseEvent) -> BaseEvent:
        """通用：记录已构造的事件（调用方自行负责脱敏）"""
        self.store.record_event(event)
        return event

    # ------------------------------------------------------------------
    # Trajectory 聚合
    # ------------------------------------------------------------------
    def finalize(
        self,
        task_id: str,
        agent_id: str,
        **kwargs: Any,
    ) -> Trajectory:
        """聚合同 task_id 的事件为 Trajectory 并写入存储"""
        return self.store.finalize_trajectory(task_id, agent_id, **kwargs)
