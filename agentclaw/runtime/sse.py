"""
SSE (Server-Sent Events) 格式化
"""

from typing import Union, Any

from agentclaw.state.serializer import safe_json_dumps


def sse_format(event: Union[dict, "OutputEvent"]) -> str:
    """
    将事件格式化为 SSE
    
    Args:
        event: 事件字典或 OutputEvent
    
    Returns:
        SSE 格式字符串: data: {...}\n\n
    """
    if hasattr(event, 'to_dict'):
        data = event.to_dict()
    else:
        data = event
    
    # 使用安全序列化（自动处理不可序列化对象）
    return f"data: {safe_json_dumps(data)}\n\n"
