"""
Memory - 记忆组件（与 LangGraph State 集成）

核心概念：
- 对话消息（用户输入/模型输出）保存在 LangGraph State 的 `__messages__` 字段
- 通过 checkpointer 自动持久化
- 本模块提供辅助函数处理消息格式转换

系统保留字段（以 __ 开头和结尾）：
- __messages__: 对话历史
- __interrupted__: 中断标记
- __status__: 状态
- __interrupt_info__: 中断信息
- __interrupt_node__: 中断节点
- __debug_stopped__: 调试停止标记
- __error__: 错误信息

注意：用户定义的 State 字段不应以 __ 开头，否则可能覆盖系统变量。
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict, Annotated
from datetime import datetime

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


# 系统保留的 State 字段（以 __ 开头和结尾）
SYSTEM_STATE_FIELDS = {
    "__messages__",
    "__interrupted__",
    "__status__",
    "__interrupt_info__",
    "__interrupt_node__",
    "__debug_stopped__",
    "__error__",
}


def warn_if_system_field(field_name: str) -> None:
    """如果字段名以 __ 开头，发出警告"""
    if field_name.startswith("__"):
        if field_name in SYSTEM_STATE_FIELDS:
            logger.warning(
                f"State 字段 '{field_name}' 是系统保留字段，手动定义可能导致意外行为"
            )
        else:
            logger.warning(
                f"State 字段 '{field_name}' 以 __ 开头，可能与系统保留字段冲突"
            )


# ============================================================
# LangGraph 消息处理
# ============================================================

def create_user_message(content: str, **kwargs) -> dict:
    """创建用户消息（用于添加到 state.__messages__）"""
    try:
        from langchain_core.messages import HumanMessage
        return HumanMessage(content=content, **kwargs)
    except ImportError:
        return {"role": "user", "content": content, **kwargs}


def create_ai_message(content: str, **kwargs) -> dict:
    """创建 AI 消息（用于添加到 state.__messages__）"""
    try:
        from langchain_core.messages import AIMessage
        return AIMessage(content=content, **kwargs)
    except ImportError:
        return {"role": "assistant", "content": content, **kwargs}


def create_system_message(content: str) -> dict:
    """创建系统消息"""
    try:
        from langchain_core.messages import SystemMessage
        return SystemMessage(content=content)
    except ImportError:
        return {"role": "system", "content": content}


def get_messages_from_state(state: dict) -> List[dict]:
    """从 LangGraph state 中提取消息列表"""
    messages = state.get("__messages__") or []
    result = []
    
    for msg in messages:
        if hasattr(msg, "content"):
            result.append({
                "role": getattr(msg, "type", "unknown"),
                "content": msg.content,
            })
        elif isinstance(msg, dict):
            result.append(msg)
    
    return result


def format_messages_for_llm(state: dict, max_messages: int = 20) -> List[dict]:
    """从 state 格式化消息，用于 LLM 调用"""
    messages = state.get("__messages__") or []
    
    if len(messages) > max_messages:
        messages = messages[-max_messages:]
    
    result = []
    for msg in messages:
        if hasattr(msg, "content"):
            role_map = {"human": "user", "ai": "assistant", "system": "system"}
            role = role_map.get(getattr(msg, "type", ""), "user")
            result.append({"role": role, "content": msg.content})
        elif isinstance(msg, dict):
            result.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
    
    return result


def get_last_user_message(state: dict) -> Optional[str]:
    """获取最后一条用户消息"""
    messages = state.get("__messages__") or []
    
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            return msg.content
        elif isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content")
    
    return None


def get_last_ai_message(state: dict) -> Optional[str]:
    """获取最后一条 AI 消息"""
    messages = state.get("__messages__") or []
    
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai":
            return msg.content
        elif isinstance(msg, dict) and msg.get("role") == "assistant":
            return msg.get("content")
    
    return None


# ============================================================
# State 类型定义辅助
# ============================================================

# 哨兵值：表示未设置默认值
class _NotSet:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __repr__(self):
        return "NOT_SET"

_NOT_SET = _NotSet()


class FieldInfo:
    """字段信息，用于定义字段属性"""
    
    def __init__(self, default=_NOT_SET, required: bool = False, description: str = ""):
        self.default = default
        self.required = required
        self.description = description
        # 如果没有设置 default 且没有显式设置 required=False，则视为必填
        self._has_default = default is not _NOT_SET
    
    def __repr__(self):
        if self.required:
            return f"Field(default={self.default!r}, required=True)"
        if self._has_default:
            return f"Field(default={self.default!r})"
        return f"Field(description={self.description!r})"


def Field(default=_NOT_SET, required: bool = False, description: str = "") -> FieldInfo:
    """
    定义字段属性
    
    Args:
        default: 默认值
        required: 是否必填（默认 False）
        description: 字段描述
    
    Example:
        class MyState(State):
            # 可选，无默认值
            user_input: str
            
            # 可选，有默认值
            language: str = "zh"
            
            # 可选，有描述
            query: str = Field(description="搜索关键词")
            
            # 必填（显式标记）
            order_id: str = Field(required=True, description="订单ID")
            
            # 必填，有默认值（用户必须确认，但有推荐值）
            model_id: str = Field(default="gpt-4", required=True)
    """
    return FieldInfo(default=default, required=required, description=description)


class StateMeta(type):
    """State 元类，处理字段定义和默认值"""
    
    # 内部属性，不作为字段处理
    _INTERNAL_ATTRS = {"__state_fields__", "__state_defaults__", "__state_required__", "__state_descriptions__"}
    
    def __new__(mcs, name, bases, namespace):
        # 收集字段定义
        fields = {}
        defaults = {}
        required_fields = set()
        descriptions = {}
        annotations = namespace.get("__annotations__", {})
        
        # 从基类继承字段
        for base in bases:
            if hasattr(base, "__state_fields__"):
                fields.update(base.__state_fields__)
            if hasattr(base, "__state_defaults__"):
                defaults.update(base.__state_defaults__)
            if hasattr(base, "__state_required__"):
                required_fields.update(base.__state_required__)
            if hasattr(base, "__state_descriptions__"):
                descriptions.update(base.__state_descriptions__)
        
        # 处理当前类的字段
        for field_name, field_type in annotations.items():
            # 跳过内部属性
            if field_name in mcs._INTERNAL_ATTRS:
                continue
            
            # 跳过私有字段（单下划线）
            if field_name.startswith("_") and not field_name.startswith("__"):
                continue
            
            # 检查系统保留字段
            warn_if_system_field(field_name)
            
            fields[field_name] = field_type
            
            # 检查默认值
            if field_name in namespace:
                value = namespace[field_name]
                
                # 处理 FieldInfo
                if isinstance(value, FieldInfo):
                    if value._has_default:
                        defaults[field_name] = value.default
                    if value.required:
                        required_fields.add(field_name)
                    if value.description:
                        descriptions[field_name] = value.description
                else:
                    # 普通默认值
                    defaults[field_name] = value
            # 无默认值，不自动视为必填（只有显式 required=True 才必填）
        
        # 清理继承的内部属性（避免被当作字段）
        for attr in mcs._INTERNAL_ATTRS:
            fields.pop(attr, None)
            defaults.pop(attr, None)
            required_fields.discard(attr)
        
        # 设置元信息
        namespace["__state_fields__"] = fields
        namespace["__state_defaults__"] = defaults
        namespace["__state_required__"] = required_fields
        namespace["__state_descriptions__"] = descriptions
        
        return super().__new__(mcs, name, bases, namespace)


class State(metaclass=StateMeta):
    """
    State 基类 - 用于定义工作流状态结构
    
    支持：
    - 类型注解
    - 默认值
    - 必填字段校验
    
    示例：
    ```python
    from agentclaw.state import State, Field
    
    class MyState(State):
        # 必填字段（无默认值）
        user_input: str
        
        # 可选字段（有默认值）
        language: str = "zh"
        max_turns: int = 10
        
        # 必填字段，但有推荐默认值（用户必须确认）
        model_id: str = Field(default="gpt-4", required=True)
        
        # 带描述的字段
        temperature: float = Field(default=0.7, description="生成温度")
    ```
    
    规则：
    - 无默认值 = 必填
    - 有默认值 = 可选
    - Field(default=x, required=True) = 必填 + 有默认值
    """
    
    # 元类会填充这些
    __state_fields__: Dict[str, Any] = {}
    __state_defaults__: Dict[str, Any] = {}
    __state_required__: set = set()
    __state_descriptions__: Dict[str, str] = {}
    
    @classmethod
    def get_defaults(cls) -> Dict[str, Any]:
        """获取所有默认值（复制可变对象）"""
        defaults = {}
        for key, value in cls.__state_defaults__.items():
            # 复制可变对象，避免共享引用
            if isinstance(value, (list, dict, set)):
                defaults[key] = type(value)(value)
            else:
                defaults[key] = value
        return defaults
    
    @classmethod
    def get_required_fields(cls) -> set:
        """获取必填字段列表"""
        return cls.__state_required__.copy()
    
    @classmethod
    def validate(cls, data: Dict[str, Any]) -> None:
        """
        校验输入数据
        
        Args:
            data: 输入数据字典
            
        Raises:
            ValueError: 缺少必填字段
        """
        missing = cls.__state_required__ - set(data.keys())
        if missing:
            raise ValueError(f"缺少必填字段: {', '.join(sorted(missing))}")
    
    @classmethod
    def init_state(cls, data: Dict[str, Any], validate: bool = True) -> Dict[str, Any]:
        """
        初始化 state，填充默认值并校验
        
        Args:
            data: 输入数据
            validate: 是否校验必填字段
            
        Returns:
            填充默认值后的 state 字典
        """
        if validate:
            cls.validate(data)
        
        # 先填充默认值，再覆盖用户输入
        state = cls.get_defaults()
        state.update(data)
        
        return state
    
    @classmethod
    def to_typed_dict(cls):
        """转换为 TypedDict 类型（用于 LangGraph 兼容）"""
        return TypedDict(cls.__name__, cls.__state_fields__)
    
    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """
        获取 State schema 信息（用于前端展示）
        
        Returns:
            {
                "fields": [
                    {
                        "name": "user_input",
                        "type": "str",
                        "required": True,
                        "default": None,
                        "description": ""
                    },
                    {
                        "name": "language",
                        "type": "str",
                        "required": False,
                        "default": "zh",
                        "description": "语言设置"
                    }
                ],
                "required_fields": ["user_input"],
                "defaults": {"language": "zh"}
            }
        """
        fields = []
        descriptions = getattr(cls, "__state_descriptions__", {})
        
        for field_name, field_type in cls.__state_fields__.items():
            # 跳过系统字段
            if field_name in SYSTEM_STATE_FIELDS:
                continue
            
            # 获取类型名称
            type_name = _get_type_name(field_type)
            
            # 判断是否必填
            is_required = field_name in cls.__state_required__
            
            # 获取默认值
            default_value = cls.__state_defaults__.get(field_name)
            
            # 获取描述
            description = descriptions.get(field_name, "")
            
            fields.append({
                "name": field_name,
                "type": type_name,
                "required": is_required,
                "default": default_value,
                "description": description,
            })
        
        # 按必填优先排序
        fields.sort(key=lambda f: (not f["required"], f["name"]))
        
        return {
            "fields": fields,
            "required_fields": sorted(cls.__state_required__ - SYSTEM_STATE_FIELDS),
            "defaults": {
                k: v for k, v in cls.__state_defaults__.items()
                if k not in SYSTEM_STATE_FIELDS
            },
        }
    
    @classmethod
    def from_type(cls, type_class: type) -> type:
        """
        从其他类型（TypedDict/dataclass）转换为 State 类
        
        Args:
            type_class: TypedDict 或 dataclass 类型
            
        Returns:
            新的 State 子类
        """
        import dataclasses
        
        fields = {}
        defaults = {}
        required_fields = set()
        
        # 处理 TypedDict
        if hasattr(type_class, "__annotations__"):
            annotations = getattr(type_class, "__annotations__", {})
            
            # 检查是否是 TypedDict
            is_typed_dict = hasattr(type_class, "__total__") or (
                hasattr(type_class, "__bases__") and 
                any(b.__name__ == "TypedDict" for b in getattr(type_class, "__mro__", []))
            )
            
            # 检查是否是 dataclass
            is_dataclass = dataclasses.is_dataclass(type_class)
            
            if is_dataclass:
                # 处理 dataclass
                for field in dataclasses.fields(type_class):
                    field_name = field.name
                    field_type = field.type
                    
                    # 跳过私有字段
                    if field_name.startswith("_") and not field_name.startswith("__"):
                        continue
                    
                    fields[field_name] = field_type
                    
                    # 检查默认值
                    if field.default is not dataclasses.MISSING:
                        defaults[field_name] = field.default
                    elif field.default_factory is not dataclasses.MISSING:
                        defaults[field_name] = field.default_factory()
                    else:
                        required_fields.add(field_name)
            
            elif is_typed_dict:
                # 处理 TypedDict
                total = getattr(type_class, "__total__", True)
                required_keys = getattr(type_class, "__required_keys__", set())
                optional_keys = getattr(type_class, "__optional_keys__", set())
                
                for field_name, field_type in annotations.items():
                    # 跳过私有字段
                    if field_name.startswith("_") and not field_name.startswith("__"):
                        continue
                    
                    fields[field_name] = field_type
                    
                    # 判断是否必填
                    if required_keys and field_name in required_keys:
                        required_fields.add(field_name)
                    elif optional_keys and field_name in optional_keys:
                        pass  # 可选
                    elif total:
                        required_fields.add(field_name)
            
            else:
                # 普通类，只处理注解
                for field_name, field_type in annotations.items():
                    if field_name.startswith("_") and not field_name.startswith("__"):
                        continue
                    
                    fields[field_name] = field_type
                    
                    # 检查类属性作为默认值
                    if hasattr(type_class, field_name):
                        value = getattr(type_class, field_name)
                        if not callable(value):
                            defaults[field_name] = value
                        else:
                            required_fields.add(field_name)
                    else:
                        required_fields.add(field_name)
        
        # 创建新的 State 子类
        new_class = type(
            type_class.__name__,
            (State,),
            {
                "__annotations__": fields,
                "__state_fields__": fields,
                "__state_defaults__": defaults,
                "__state_required__": required_fields,
                **defaults,  # 设置默认值为类属性
            }
        )
        
        return new_class


def _get_type_name(field_type: Any) -> str:
    """获取类型的字符串表示"""
    if hasattr(field_type, "__name__"):
        return field_type.__name__
    elif hasattr(field_type, "__origin__"):
        # 处理泛型类型如 List[str], Optional[int]
        origin = field_type.__origin__
        args = getattr(field_type, "__args__", ())
        
        origin_name = getattr(origin, "__name__", str(origin))
        if args:
            args_str = ", ".join(_get_type_name(a) for a in args)
            return f"{origin_name}[{args_str}]"
        return origin_name
    else:
        return str(field_type)


def create_chat_state_type():
    """创建标准的聊天 State 类型"""
    try:
        from langgraph.graph.message import add_messages
        
        class ChatState(TypedDict):
            __messages__: Annotated[list, add_messages]
        
        return ChatState
    except ImportError:
        class ChatState(TypedDict):
            __messages__: list
        
        return ChatState