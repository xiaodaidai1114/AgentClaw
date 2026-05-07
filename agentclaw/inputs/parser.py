"""
Input Parser - 输入参数解析器

支持三种输入定义方式的统一解析：
1. 字典简写: {"query": str, "count": int}
2. Input 对象列表: [Input("query", str, required=True)]
3. Pydantic BaseModel 类
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Type, Union, get_origin, get_args, get_type_hints
import inspect

from agentclaw.inputs.types import Input, InputSchema, Image, File, Files, Audio
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def parse_inputs(
    inputs: Union[
        None,
        Dict[str, Type],                    # 字典简写
        List[Input],                         # Input 对象列表
        Type,                                # Pydantic BaseModel 或其他类
    ]
) -> Optional[InputSchema]:
    """
    解析输入定义，统一转换为 InputSchema
    
    Args:
        inputs: 输入定义，支持多种格式
        
    Returns:
        InputSchema 对象，如果 inputs 为 None 则返回 None
    """
    if inputs is None:
        return None
    
    # 1. 字典简写: {"query": str, "count": int}
    if isinstance(inputs, dict):
        return _parse_dict_inputs(inputs)
    
    # 2. Input 对象列表: [Input("query", str)]
    if isinstance(inputs, list):
        return _parse_list_inputs(inputs)
    
    # 3. 类（Pydantic BaseModel 或其他）
    if isinstance(inputs, type):
        return _parse_class_inputs(inputs)
    
    logger.warning(f"无法解析 inputs 类型: {type(inputs)}")
    return None


def _parse_dict_inputs(inputs: Dict[str, Any]) -> InputSchema:
    """
    解析字典格式的输入定义
    
    支持格式：
    - 简单: {"query": str}
    - 带默认值: {"count": (int, 10)}
    - 完整: {"query": {"type": str, "required": True, "description": "..."}}
    """
    schema = InputSchema()
    
    for name, value in inputs.items():
        if isinstance(value, type):
            # 简单格式: {"query": str}
            schema.add(Input(
                name=name,
                type=value,
                required=True,
            ))
        elif isinstance(value, tuple) and len(value) == 2:
            # 带默认值: {"count": (int, 10)}
            field_type, default = value
            schema.add(Input(
                name=name,
                type=field_type,
                required=False,
                default=default,
            ))
        elif isinstance(value, dict):
            # 完整格式: {"query": {"type": str, "required": True}}
            field_type = value.get("type", str)
            if isinstance(field_type, str):
                field_type = _str_to_type(field_type)
            
            schema.add(Input(
                name=name,
                type=field_type,
                required=value.get("required", False),
                default=value.get("default"),
                description=value.get("description", ""),
                min=value.get("min"),
                max=value.get("max"),
                min_length=value.get("min_length"),
                max_length=value.get("max_length"),
                pattern=value.get("pattern"),
                choices=value.get("choices"),
                accept=value.get("accept"),
                max_size=value.get("max_size"),
            ))
        elif isinstance(value, Input):
            # 直接是 Input 对象
            schema.add(value)
        else:
            # 其他情况，当作字符串类型
            schema.add(Input(
                name=name,
                type=str,
                required=True,
            ))
    
    return schema


def _parse_list_inputs(inputs: List[Input]) -> InputSchema:
    """解析 Input 对象列表"""
    schema = InputSchema()
    for inp in inputs:
        if isinstance(inp, Input):
            schema.add(inp)
        elif isinstance(inp, dict) and "name" in inp:
            # dict 兼容：热注册 exec_module 可能导致 Input 类标识不一致
            field_type = inp.get("type", str)
            if isinstance(field_type, str):
                field_type = _str_to_type(field_type)
            schema.add(Input(
                name=inp["name"],
                type=field_type,
                required=inp.get("required", False),
                default=inp.get("default"),
                description=inp.get("description", ""),
            ))
        elif isinstance(inp, dict):
            # dict-shorthand 兼容：{"field_name": str} 或 {"field_name": {"type": "string", ...}}
            for name, value in inp.items():
                if isinstance(value, type):
                    schema.add(Input(name=name, type=value, required=True))
                elif isinstance(value, dict):
                    ft = value.get("type", str)
                    if isinstance(ft, str):
                        ft = _str_to_type(ft)
                    schema.add(Input(
                        name=name, type=ft,
                        required=value.get("required", False),
                        default=value.get("default"),
                        description=value.get("description", ""),
                    ))
                elif isinstance(value, str):
                    schema.add(Input(name=name, type=_str_to_type(value), required=True))
                else:
                    schema.add(Input(name=name, type=str, required=True))
        elif hasattr(inp, "name") and hasattr(inp, "type"):
            # duck-type 兼容：exec_module 导致 Input 类标识不一致时的降级处理
            schema.add(Input(
                name=inp.name,
                type=inp.type if not isinstance(inp.type, str) else _str_to_type(inp.type),
                required=getattr(inp, "required", False),
                default=getattr(inp, "default", None),
                description=getattr(inp, "description", ""),
                min=getattr(inp, "min", None),
                max=getattr(inp, "max", None),
                min_length=getattr(inp, "min_length", None),
                max_length=getattr(inp, "max_length", None),
                pattern=getattr(inp, "pattern", None),
                choices=getattr(inp, "choices", None),
                accept=getattr(inp, "accept", None),
                max_size=getattr(inp, "max_size", None),
            ))
        else:
            logger.warning(f"忽略非 Input 对象: {type(inp)}")
    return schema


def _parse_class_inputs(cls: Type) -> InputSchema:
    """
    解析类定义的输入
    
    支持：
    - Pydantic BaseModel
    - dataclass
    - TypedDict
    - 普通类（带 __annotations__）
    """
    schema = InputSchema()
    
    # 检查是否是 Pydantic BaseModel
    try:
        from pydantic import BaseModel
        if issubclass(cls, BaseModel):
            return _parse_pydantic_model(cls)
    except ImportError:
        pass
    
    # 检查是否是 dataclass
    import dataclasses
    if dataclasses.is_dataclass(cls):
        return _parse_dataclass(cls)
    
    # 普通类或 TypedDict
    return _parse_annotated_class(cls)


def _parse_pydantic_model(cls: Type) -> InputSchema:
    """解析 Pydantic BaseModel"""
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo
    
    schema = InputSchema()
    
    # 获取模型字段
    model_fields = getattr(cls, "model_fields", None) or getattr(cls, "__fields__", {})
    
    for field_name, field_info in model_fields.items():
        # Pydantic v2
        if hasattr(field_info, "annotation"):
            field_type = field_info.annotation
            is_required = field_info.is_required()
            default = field_info.default if not field_info.is_required() else None
            description = field_info.description or ""
            
            # 获取约束
            constraints = {}
            if hasattr(field_info, "metadata"):
                for meta in field_info.metadata:
                    if hasattr(meta, "ge"):
                        constraints["min"] = meta.ge
                    if hasattr(meta, "le"):
                        constraints["max"] = meta.le
                    if hasattr(meta, "min_length"):
                        constraints["min_length"] = meta.min_length
                    if hasattr(meta, "max_length"):
                        constraints["max_length"] = meta.max_length
        else:
            # Pydantic v1
            field_type = field_info.outer_type_
            is_required = field_info.required
            default = field_info.default if not field_info.required else None
            description = field_info.field_info.description or ""
            constraints = {}
        
        # 处理 Optional 类型
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                field_type = non_none_args[0]
                if type(None) in args:
                    is_required = False
        
        schema.add(Input(
            name=field_name,
            type=field_type,
            required=is_required,
            default=default,
            description=description,
            **constraints,
        ))
    
    return schema


def _parse_dataclass(cls: Type) -> InputSchema:
    """解析 dataclass"""
    import dataclasses
    
    schema = InputSchema()
    
    for field in dataclasses.fields(cls):
        has_default = (
            field.default is not dataclasses.MISSING or
            field.default_factory is not dataclasses.MISSING
        )
        
        default_value = None
        if field.default is not dataclasses.MISSING:
            default_value = field.default
        elif field.default_factory is not dataclasses.MISSING:
            default_value = field.default_factory()
        
        schema.add(Input(
            name=field.name,
            type=field.type,
            required=not has_default,
            default=default_value,
        ))
    
    return schema


def _parse_annotated_class(cls: Type) -> InputSchema:
    """解析普通类或 TypedDict"""
    schema = InputSchema()
    
    # 获取类型注解
    annotations = getattr(cls, "__annotations__", {})
    
    # 获取默认值
    defaults = {}
    for attr_name in dir(cls):
        if not attr_name.startswith("_"):
            try:
                value = getattr(cls, attr_name)
                if not callable(value):
                    defaults[attr_name] = value
            except Exception:
                pass
    
    # TypedDict 的必填/可选字段
    required_keys = getattr(cls, "__required_keys__", set())
    optional_keys = getattr(cls, "__optional_keys__", set())
    total = getattr(cls, "__total__", True)
    
    for field_name, field_type in annotations.items():
        if field_name.startswith("_"):
            continue
        
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
        
        # 处理 Optional 类型
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                field_type = non_none_args[0]
                if type(None) in args:
                    is_required = False
        
        schema.add(Input(
            name=field_name,
            type=field_type,
            required=is_required,
            default=default_value,
        ))
    
    return schema


def _str_to_type(type_str: str) -> Type:
    """字符串转类型"""
    type_map = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "number": float,
        "bool": bool,
        "boolean": bool,
        "list": list,
        "array": list,
        "dict": dict,
        "object": dict,
        "image": Image,
        "file": File,
        "files": Files,
        "audio": Audio,
    }
    return type_map.get(type_str.lower(), str)
