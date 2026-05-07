"""
Model - LLM 模型管理模块

提供 LLM 调用、多模型配置、降级策略、视觉处理
"""

from agentclaw.model.manager import (
    LLMManager,
    LLMConfig,
    FallbackState,
    UsageStats,
)
from agentclaw.model.vision import (
    ImageInput,
    build_vision_messages,
    encode_image,
    image_from_url,
    image_from_file,
)

__all__ = [
    # Manager
    "LLMManager",
    "LLMConfig",
    "FallbackState",
    "UsageStats",
    # Vision
    "ImageInput",
    "build_vision_messages",
    "encode_image",
    "image_from_url",
    "image_from_file",
]
