"""
State Serializer - 状态序列化工具

提供自动降级的 JSON 序列化功能：
- 支持基础类型直接序列化
- 不可序列化对象自动降级为字符串表示
- 记录警告日志提醒用户
"""

from __future__ import annotations
import json
from datetime import datetime, date
from typing import Any, Dict, Set
from uuid import UUID

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

# 已警告过的类型（避免重复警告）
_warned_types: Set[str] = set()


def make_serializable(obj: Any, path: str = "root", warn: bool = True) -> Any:
    """
    递归将对象转换为 JSON 可序列化格式
    
    Args:
        obj: 要序列化的对象
        path: 当前路径（用于日志）
        warn: 是否输出警告
    
    Returns:
        JSON 可序列化的对象
    
    Example:
        state = {"user": CustomUser("张三"), "count": 10}
        safe_state = make_serializable(state)
        # {"user": "<CustomUser: 张三>", "count": 10}
    """
    # None
    if obj is None:
        return None
    
    # 基础类型
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # 日期时间
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    
    # UUID
    if isinstance(obj, UUID):
        return str(obj)
    
    # bytes
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return f"<bytes: {len(obj)} bytes>"
    
    # 字典
    if isinstance(obj, dict):
        return {
            str(k): make_serializable(v, f"{path}.{k}", warn)
            for k, v in obj.items()
        }
    
    # 列表/元组
    if isinstance(obj, (list, tuple)):
        return [
            make_serializable(item, f"{path}[{i}]", warn)
            for i, item in enumerate(obj)
        ]
    
    # set
    if isinstance(obj, set):
        return [make_serializable(item, f"{path}[set]", warn) for item in obj]
    
    # Pydantic BaseModel
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    
    # dataclass
    if hasattr(obj, "__dataclass_fields__"):
        try:
            import dataclasses
            return make_serializable(dataclasses.asdict(obj), path, warn)
        except Exception:
            pass
    
    # 有 to_dict 方法的对象
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return make_serializable(obj.to_dict(), path, warn)
        except Exception:
            pass
    
    # 有 __dict__ 的普通对象
    if hasattr(obj, "__dict__"):
        try:
            return make_serializable(obj.__dict__, path, warn)
        except Exception:
            pass
    
    # 无法序列化，降级为字符串
    type_name = type(obj).__name__
    
    # 只警告一次
    if warn and type_name not in _warned_types:
        _warned_types.add(type_name)
        logger.warning(
            f"State 中包含不可序列化类型 '{type_name}'，已自动转为字符串。"
            f"路径: {path}"
        )
    
    # 尝试获取有意义的字符串表示
    try:
        return f"<{type_name}: {str(obj)[:100]}>"
    except Exception:
        return f"<{type_name}>"


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """
    安全的 JSON 序列化
    
    自动处理不可序列化对象，不会抛出异常
    
    Args:
        obj: 要序列化的对象
        **kwargs: 传递给 json.dumps 的参数
    
    Returns:
        JSON 字符串
    """
    safe_obj = make_serializable(obj)
    
    # 设置默认参数
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", str)  # 最后的保底
    
    return json.dumps(safe_obj, **kwargs)


def safe_json_loads(s: str, **kwargs) -> Any:
    """
    安全的 JSON 反序列化
    
    Args:
        s: JSON 字符串
        **kwargs: 传递给 json.loads 的参数
    
    Returns:
        解析后的对象，失败返回 None
    """
    try:
        return json.loads(s, **kwargs)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"JSON 解析失败: {e}")
        return None


class SafeJSONEncoder(json.JSONEncoder):
    """
    安全的 JSON 编码器
    
    用于 FastAPI 响应等场景
    
    Example:
        json.dumps(data, cls=SafeJSONEncoder)
    """
    
    def default(self, obj: Any) -> Any:
        # 日期时间
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        
        # UUID
        if isinstance(obj, UUID):
            return str(obj)
        
        # bytes
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                return f"<bytes: {len(obj)} bytes>"
        
        # set
        if isinstance(obj, set):
            return list(obj)
        
        # Pydantic
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        
        # dataclass
        if hasattr(obj, "__dataclass_fields__"):
            import dataclasses
            return dataclasses.asdict(obj)
        
        # to_dict
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return obj.to_dict()
        
        # __dict__
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        
        # 降级为字符串
        type_name = type(obj).__name__
        try:
            return f"<{type_name}: {str(obj)[:100]}>"
        except Exception:
            return f"<{type_name}>"
