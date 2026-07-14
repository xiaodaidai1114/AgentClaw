"""
Experience 事件 Schema（Pydantic）

记录企业 Agent 运行过程的 5 类事件 + Trajectory 聚合，为 Skill Evolution Engine
提供原始数据。事件可序列化为 JSON，写入 JSONL 或未来替换为 PostgreSQL。

事件类型：
- TaskStartedEvent      任务开始
- ToolCalledEvent       工具调用
- AgentRespondedEvent   Agent 给出回复
- HumanFeedbackEvent    人工反馈（评分/反馈/人工修正）
- TaskFailedEvent       任务失败

Trajectory 把一次完整任务的事件聚合为一条可分析的轨迹。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# 事件类型常量
# ------------------------------------------------------------------

EVENT_TYPE_TASK_STARTED = "task_started"
EVENT_TYPE_TOOL_CALLED = "tool_called"
EVENT_TYPE_AGENT_RESPONDED = "agent_responded"
EVENT_TYPE_HUMAN_FEEDBACK = "human_feedback_received"
EVENT_TYPE_TASK_FAILED = "task_failed"

ALL_EVENT_TYPES = frozenset({
    EVENT_TYPE_TASK_STARTED,
    EVENT_TYPE_TOOL_CALLED,
    EVENT_TYPE_AGENT_RESPONDED,
    EVENT_TYPE_HUMAN_FEEDBACK,
    EVENT_TYPE_TASK_FAILED,
})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------
# 事件
# ------------------------------------------------------------------

class BaseEvent(BaseModel):
    """事件基类"""
    event_type: str
    agent_id: str
    task_id: str
    timestamp: datetime = Field(default_factory=_now_utc)

    def to_jsonl(self) -> str:
        """序列化为 JSONL 一行（含换行）"""
        import json
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)


class TaskStartedEvent(BaseEvent):
    """任务开始"""
    event_type: str = EVENT_TYPE_TASK_STARTED
    agent_version: str = ""
    user_request: str = ""


class ToolCalledEvent(BaseEvent):
    """工具调用"""
    event_type: str = EVENT_TYPE_TOOL_CALLED
    tool_name: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    tool_output: str = ""
    success: bool = True
    latency_ms: float = 0.0


class AgentRespondedEvent(BaseEvent):
    """Agent 给出回复"""
    event_type: str = EVENT_TYPE_AGENT_RESPONDED
    response: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class HumanFeedbackEvent(BaseEvent):
    """人工反馈"""
    event_type: str = EVENT_TYPE_HUMAN_FEEDBACK
    rating: int = 0  # 1-5，0 表示未评分
    feedback: str = ""
    human_correction: str = ""


class TaskFailedEvent(BaseEvent):
    """任务失败"""
    event_type: str = EVENT_TYPE_TASK_FAILED
    error_type: str = ""
    error_message: str = ""
    failed_step: str = ""


# ------------------------------------------------------------------
# Trajectory（任务聚合）
# ------------------------------------------------------------------

class Trajectory(BaseModel):
    """一次完整任务的事件聚合，供 Skill Evolution 分析"""
    trajectory_id: str
    agent_id: str
    agent_version: str = ""
    task: str = ""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[ToolCalledEvent] = Field(default_factory=list)
    final_answer: str = ""
    human_feedback: str = ""
    human_correction: str = ""
    rating: int = 0
    success: bool = True
    created_at: datetime = Field(default_factory=_now_utc)


# 事件类 → 类型常量，便于反序列化
EVENT_CLASS_BY_TYPE = {
    EVENT_TYPE_TASK_STARTED: TaskStartedEvent,
    EVENT_TYPE_TOOL_CALLED: ToolCalledEvent,
    EVENT_TYPE_AGENT_RESPONDED: AgentRespondedEvent,
    EVENT_TYPE_HUMAN_FEEDBACK: HumanFeedbackEvent,
    EVENT_TYPE_TASK_FAILED: TaskFailedEvent,
}


def event_from_dict(data: Dict[str, Any]) -> BaseEvent:
    """根据 event_type 反序列化为对应事件类"""
    event_type = str(data.get("event_type") or "")
    cls = EVENT_CLASS_BY_TYPE.get(event_type)
    if cls is None:
        # 未知事件类型回退为基类（保留字段）
        return BaseEvent.model_validate(data)
    return cls.model_validate(data)
