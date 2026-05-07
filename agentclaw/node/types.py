"""
Node Types - 节点类型定义
"""

from enum import Enum


class ErrorStrategy(Enum):
    """错误处理策略"""
    ABORT = "abort"      # 终止工作流
    RETRY = "retry"      # 重试
    SKIP = "skip"        # 跳过该节点
    FALLBACK = "fallback"  # 使用降级值
