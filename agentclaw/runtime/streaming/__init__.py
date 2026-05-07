"""
流式输出模块

提供：
- OutputChannel: 输出通道管理
- output(): 统一输出函数
- sse_format(): SSE 格式化（使用安全序列化）
"""

from agentclaw.runtime.streaming.context import (
    OutputChannel,
    output,
    get_output_channel,
)

# sse_format 统一使用 runtime/sse.py 的实现（支持安全序列化）
from agentclaw.runtime.sse import sse_format

__all__ = [
    "OutputChannel",
    "output",
    "get_output_channel",
    "sse_format",
]
