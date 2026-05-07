"""
StateSchema - 状态 Schema 定义

用于：
- 定义工作流输入参数
- 生成 API 文档
- MCP 工具输入 Schema
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Type, get_type_hints
import dataclasses

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


class FieldSchema:
    """字段 Schema"""
    
    def __init__(
        self,
        name: str,
        field_type: str = "string",
        required: bool = False,
        default: Any = None,
        description: str = "",
    ):
        self.name = name
        self.field_type = field_type
        self.required = required
        self.default = default
        self.description = description
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "type": self.field_type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }


class StateSchema:
    """
    状态 Schema
    
    用于定义工作流的输入参数结构
    """
    
    def __init__(self):
        self.fields: Dict[str, FieldSchema] = {}
    
    def add_field(
        self,
        name: str,
        field_type: str = "string",
        required: bool = False,
        default: Any = None,
        description: str = "",
    ) -> "StateSchema":
        """添加字段"""
        self.fields[name] = FieldSchema(
            name=name,
            field_type=field_type,
            required=required,
            default=default,
            description=description,
        )
        return self
    
    @classmethod
    def from_dict(cls, schema_dict: Dict[str, Any]) -> "StateSchema":
        """
        从字典创建 StateSchema
        
        支持格式：
        - 简单格式: {"field_name": str}
        - 完整格式: {"field_name": {"type": str, "default": "", "description": "..."}}
        """
        schema = cls()
        
        for field_name, field_info in schema_dict.items():
            if isinstance(field_info, type):
                # 简单格式: {"field_name": str}
                schema.add_field(
                    name=field_name,
                    field_type=_get_type_name(field_info),
                    required=True,
                )
            elif isinstance(field_info, dict):
                # 完整格式
                field_type = field_info.get("type", "string")
                if isinstance(field_type, type):
                    field_type = _get_type_name(field_type)
                
                schema.add_field(
                    name=field_name,
                    field_type=field_type,
                    required=field_info.get("required", False),
                    default=field_info.get("default"),
                    description=field_info.get("description", ""),
                )
            else:
                # 其他情况，当作字符串类型
                schema.add_field(
                    name=field_name,
                    field_type="string",
                    required=True,
                )
        
        return schema
    
    @classmethod
    def from_class(cls, state_class: Type) -> "StateSchema":
        """
        从类创建 StateSchema
        
        支持：
        - TypedDict
        - dataclass
        - 普通类（带 __annotations__）
        - State 子类
        """
        schema = cls()
        
        # 检查是否是 State 子类
        from agentclaw.state.memory import State
        if isinstance(state_class, type) and issubclass(state_class, State):
            # 使用 State 的 get_schema 方法
            state_info = state_class.get_schema()
            for field in state_info.get("fields", []):
                schema.add_field(
                    name=field["name"],
                    field_type=field.get("type", "string"),
                    required=field.get("required", False),
                    default=field.get("default"),
                    description=field.get("description", ""),
                )
            return schema
        
        # 检查是否是 dataclass
        if dataclasses.is_dataclass(state_class):
            for field in dataclasses.fields(state_class):
                field_type = _get_type_name(field.type)
                has_default = field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
                default_value = None
                if field.default is not dataclasses.MISSING:
                    default_value = field.default
                elif field.default_factory is not dataclasses.MISSING:
                    default_value = field.default_factory()
                
                schema.add_field(
                    name=field.name,
                    field_type=field_type,
                    required=not has_default,
                    default=default_value,
                )
            return schema
        
        # 普通类或 TypedDict
        annotations = getattr(state_class, "__annotations__", {})
        
        # 获取默认值
        defaults = {}
        for attr_name in dir(state_class):
            if not attr_name.startswith("_"):
                try:
                    value = getattr(state_class, attr_name)
                    if not callable(value):
                        defaults[attr_name] = value
                except Exception:
                    pass
        
        # TypedDict 的必填/可选字段
        required_keys = getattr(state_class, "__required_keys__", set())
        optional_keys = getattr(state_class, "__optional_keys__", set())
        total = getattr(state_class, "__total__", True)
        
        for field_name, field_type in annotations.items():
            if field_name.startswith("_"):
                continue
            
            type_name = _get_type_name(field_type)
            default_value = defaults.get(field_name)
            
            # 判断是否必填
            if required_keys and field_name in required_keys:
                is_required = True
            elif optional_keys and field_name in optional_keys:
                is_required = False
            elif default_value is not None:
                is_required = False
            else:
                is_required = total
            
            schema.add_field(
                name=field_name,
                field_type=type_name,
                required=is_required,
                default=default_value,
            )
        
        return schema
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "fields": [f.to_dict() for f in self.fields.values()],
        }
    
    def to_input_schema(self) -> dict:
        """转换为 API 输入 Schema 格式"""
        properties = {}
        required = []
        
        for field in self.fields.values():
            prop = {
                "type": field.field_type,
            }
            if field.description:
                prop["description"] = field.description
            if field.default is not None:
                prop["default"] = field.default
            
            properties[field.name] = prop
            
            if field.required:
                required.append(field.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    
    def validate(self, data: dict) -> List[str]:
        """
        验证数据是否符合 Schema
        
        Returns:
            错误列表，空列表表示验证通过
        """
        errors = []
        
        for field in self.fields.values():
            if field.required and field.name not in data:
                errors.append(f"缺少必填字段: {field.name}")
        
        return errors


def _get_type_name(field_type: Any) -> str:
    """获取类型的字符串表示"""
    if field_type is None:
        return "string"
    
    if isinstance(field_type, str):
        return field_type
    
    if hasattr(field_type, "__name__"):
        return field_type.__name__
    
    if hasattr(field_type, "__origin__"):
        # 处理泛型类型如 List[str], Optional[int]
        origin = field_type.__origin__
        args = getattr(field_type, "__args__", ())
        
        origin_name = getattr(origin, "__name__", str(origin))
        if args:
            args_str = ", ".join(_get_type_name(a) for a in args)
            return f"{origin_name}[{args_str}]"
        return origin_name
    
    return str(field_type)
