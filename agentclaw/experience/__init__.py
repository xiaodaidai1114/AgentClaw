"""
Experience Collector - 企业 Agent 使用经验采集

为 Skill Evolution Engine 提供原始数据：
- 5 类事件（task_started / tool_called / agent_responded / human_feedback / task_failed）
- Trajectory 聚合（一次任务的完整轨迹）
- 隐私脱敏默认开启（email/手机号/身份证/银行卡/api_key/token/password/address）
- JSONL 存储，StorageBackend 抽象可替换为 PostgreSQL

Phase 4 为纯新增模块，不依赖运行时；后续通过 BaseTracer 子类零侵入挂载到
现有三层 trace 表。开关 AGENTCLAW_EXPERIENCE_ENABLED（默认 off）控制自动采集。

典型用法：
    from agentclaw.experience import EventLogger, FeedbackCollector, JSONLStorage
    from pathlib import Path

    logger = EventLogger(store=TrajectoryStore(JSONLStorage(Path("data/experience"))))
    logger.log_task_started("sales_agent", "task-1", user_request="...", agent_version="v0.1")
    logger.log_tool_called("sales_agent", "task-1", "crm_query", tool_input={"id": 1})
    logger.log_agent_responded("sales_agent", "task-1", response="...", confidence=0.8)
    traj = logger.finalize("task-1", "sales_agent")

    fc = FeedbackCollector(logger)
    fc.submit("sales_agent", "task-1", rating=4, human_correction="预算>50万应标记高价值")
"""

from .event_schema import (
    AgentRespondedEvent,
    ALL_EVENT_TYPES,
    BaseEvent,
    EVENT_TYPE_AGENT_RESPONDED,
    EVENT_TYPE_HUMAN_FEEDBACK,
    EVENT_TYPE_TASK_FAILED,
    EVENT_TYPE_TASK_STARTED,
    EVENT_TYPE_TOOL_CALLED,
    HumanFeedbackEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    ToolCalledEvent,
    Trajectory,
    event_from_dict,
)
from .event_logger import EventLogger
from .feedback_collector import FeedbackCollector, RATING_MAX, RATING_MIN
from .privacy_filter import (
    SENSITIVE_KEYS,
    has_sensitive_info,
    mask_value,
    sanitize_dict,
    sanitize_text,
    sanitize_value,
)
from .trajectory_store import (
    JSONLStorage,
    StorageBackend,
    TrajectoryStore,
)

__all__ = [
    # 事件
    "BaseEvent",
    "TaskStartedEvent",
    "ToolCalledEvent",
    "AgentRespondedEvent",
    "HumanFeedbackEvent",
    "TaskFailedEvent",
    "Trajectory",
    "event_from_dict",
    "EVENT_TYPE_TASK_STARTED",
    "EVENT_TYPE_TOOL_CALLED",
    "EVENT_TYPE_AGENT_RESPONDED",
    "EVENT_TYPE_HUMAN_FEEDBACK",
    "EVENT_TYPE_TASK_FAILED",
    "ALL_EVENT_TYPES",
    # 隐私
    "mask_value",
    "sanitize_text",
    "sanitize_dict",
    "sanitize_value",
    "has_sensitive_info",
    "SENSITIVE_KEYS",
    # 存储
    "StorageBackend",
    "JSONLStorage",
    "TrajectoryStore",
    # 记录
    "EventLogger",
    "FeedbackCollector",
    "RATING_MIN",
    "RATING_MAX",
]
