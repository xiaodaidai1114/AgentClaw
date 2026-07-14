"""
FeedbackCollector - 人工反馈采集

收集用户对 Agent 回复的评分/反馈/人工修正，记录为 HumanFeedbackEvent。
反馈是 Skill Evolution 最有价值的信号（重复的人工修正 → 候选 Skill）。
"""

from __future__ import annotations

from typing import Optional

from .event_logger import EventLogger
from .event_schema import HumanFeedbackEvent
from .privacy_filter import sanitize_text


# 评分范围
RATING_MIN = 1
RATING_MAX = 5


class FeedbackCollector:
    """人工反馈采集器"""

    def __init__(self, logger: Optional[EventLogger] = None) -> None:
        self.logger = logger or EventLogger()

    def submit(
        self,
        agent_id: str,
        task_id: str,
        *,
        rating: int = 0,
        feedback: str = "",
        human_correction: str = "",
    ) -> HumanFeedbackEvent:
        """
        提交人工反馈。

        Args:
            rating: 1-5 分，0 表示未评分
            feedback: 自由文本反馈
            human_correction: 用户给出的修正内容（Skill Evolution 的核心信号）
        """
        if rating != 0 and not (RATING_MIN <= rating <= RATING_MAX):
            raise ValueError(f"rating 必须在 {RATING_MIN}-{RATING_MAX} 之间或为 0，当前: {rating}")

        privacy = self.logger.privacy_enabled
        ev = HumanFeedbackEvent(
            agent_id=agent_id,
            task_id=task_id,
            rating=rating,
            feedback=sanitize_text(feedback) if privacy else feedback,
            human_correction=sanitize_text(human_correction) if privacy else human_correction,
        )
        self.logger.store.record_event(ev)
        return ev
