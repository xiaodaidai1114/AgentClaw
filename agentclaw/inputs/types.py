"""
Input Types - 输入类型定义

提供 Input 类和特殊类型（Image, File, Audio）
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Type, Union, get_origin, get_args
from dataclasses import dataclass, field
import json


# ============================================================
# 特殊类型标记
# ============================================================

class _FileType:
    """文件类型基类"""
    pass


class Image(_FileType):
    """图片类型标记"""
    pass


class File(_FileType):
    """文件类型标记"""
    pass


class Audio(_FileType):
    """音频类型标记"""
    pass


class Files(_FileType):
    """多文件类型标记（允许上传多个文件）"""
    pass


# ============================================================
# Input 定义
# ============================================================

@dataclass
class Input:
    """
    输入参数定义
    
    Example:
        Input("query", str, required=True, description="查询内容")
        Input("count", int, default=10, min=1, max=100)
        Input("image", Image, description="上传图片")
        Input("mode", str, choices=["fast", "balanced", "quality"])
    """
    name: str
    type: Type = str
    required: bool = False
    default: Any = None
    description: str = ""
    
    # 约束参数
    min: Optional[Union[int, float]] = None
    max: Optional[Union[int, float]] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    choices: Optional[List[Any]] = None  # 枚举选项
    
    # 文件类型约束
    accept: Optional[List[str]] = None  # 接受的文件类型，如 [".pdf", ".docx"]
    max_size: Optional[str] = None  # 最大文件大小，如 "10MB"
    
    # 数组约束
    items: Optional[Type] = None  # 数组元素类型
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    
    def __post_init__(self):
        # 如果没有设置 required 且没有 default，则为必填
        if self.default is None and not self.required:
            # 检查是否显式设置了 required=False
            pass  # 保持默认行为
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        schema = {
            "type": _type_to_json_type(self.type),
        }
        
        if self.description:
            schema["description"] = self.description
        
        if self.default is not None:
            schema["default"] = self.default
        
        # 数值约束
        if self.min is not None:
            schema["minimum"] = self.min
        if self.max is not None:
            schema["maximum"] = self.max
        
        # 字符串约束
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        
        # 枚举
        if self.choices is not None:
            schema["enum"] = self.choices
        
        # 数组
        if self.items is not None:
            schema["items"] = {"type": _type_to_json_type(self.items)}
        if self.min_items is not None:
            schema["minItems"] = self.min_items
        if self.max_items is not None:
            schema["maxItems"] = self.max_items
        
        # 文件类型特殊处理
        if self.type in (Image, File, Audio):
            schema["format"] = _type_to_format(self.type)
            if self.accept:
                schema["accept"] = self.accept
            if self.max_size:
                schema["maxSize"] = self.max_size
        
        return schema
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 API 返回）"""
        return {
            "name": self.name,
            "type": _type_to_json_type(self.type),
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "constraints": self._get_constraints(),
        }
    
    def _get_constraints(self) -> Dict[str, Any]:
        """获取约束参数"""
        constraints = {}
        if self.min is not None:
            constraints["min"] = self.min
        if self.max is not None:
            constraints["max"] = self.max
        if self.min_length is not None:
            constraints["minLength"] = self.min_length
        if self.max_length is not None:
            constraints["maxLength"] = self.max_length
        if self.pattern is not None:
            constraints["pattern"] = self.pattern
        if self.choices is not None:
            constraints["choices"] = self.choices
        if self.accept is not None:
            constraints["accept"] = self.accept
        if self.max_size is not None:
            constraints["maxSize"] = self.max_size
        return constraints


# ============================================================
# InputSchema
# ============================================================

class InputSchema:
    """
    输入参数 Schema
    
    统一管理工作流的输入参数定义，支持：
    - 生成 JSON Schema（用于 MCP、API 文档）
    - 生成前端表单配置
    - 运行时参数验证
    """
    
    def __init__(self, inputs: Optional[List[Input]] = None):
        self.inputs: Dict[str, Input] = {}
        if inputs:
            for inp in inputs:
                self.inputs[inp.name] = inp
    
    def add(self, inp: Input) -> "InputSchema":
        """添加输入参数"""
        self.inputs[inp.name] = inp
        return self
    
    def get(self, name: str) -> Optional[Input]:
        """获取输入参数"""
        return self.inputs.get(name)
    
    def to_json_schema(self) -> Dict[str, Any]:
        """转换为 JSON Schema 格式"""
        properties = {}
        required = []
        
        for inp in self.inputs.values():
            properties[inp.name] = inp.to_json_schema()
            if inp.required:
                required.append(inp.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 API 返回）"""
        return {
            "inputs": [inp.to_dict() for inp in self.inputs.values()],
        }
    
    def to_form_config(self) -> List[Dict[str, Any]]:
        """转换为前端表单配置"""
        form_fields = []
        for inp in self.inputs.values():
            field_config = {
                "name": inp.name,
                "type": _type_to_form_type(inp.type),
                "label": inp.description or inp.name,
                "required": inp.required,
                "default": inp.default,
            }
            
            # 添加约束
            if inp.choices:
                field_config["options"] = inp.choices
            if inp.min is not None:
                field_config["min"] = inp.min
            if inp.max is not None:
                field_config["max"] = inp.max
            if inp.accept:
                field_config["accept"] = inp.accept
            if inp.max_size:
                field_config["maxSize"] = inp.max_size
            
            form_fields.append(field_config)
        
        return form_fields
    
    def validate(self, data: Dict[str, Any]) -> List[str]:
        """
        验证输入数据
        
        Returns:
            错误列表，空列表表示验证通过
        """
        errors = []
        
        for inp in self.inputs.values():
            value = data.get(inp.name)
            
            # 检查必填
            if inp.required and value is None:
                errors.append(f"缺少必填参数: {inp.name}")
                continue
            
            if value is None:
                continue
            
            # 类型检查（简单检查）
            expected_type = inp.type
            if expected_type == int and not isinstance(value, int):
                errors.append(f"参数 {inp.name} 应为整数")
            elif expected_type == float and not isinstance(value, (int, float)):
                errors.append(f"参数 {inp.name} 应为数字")
            elif expected_type == bool and not isinstance(value, bool):
                errors.append(f"参数 {inp.name} 应为布尔值")
            elif expected_type == str and not isinstance(value, str):
                errors.append(f"参数 {inp.name} 应为字符串")
            
            # 数值范围检查
            if isinstance(value, (int, float)):
                if inp.min is not None and value < inp.min:
                    errors.append(f"参数 {inp.name} 不能小于 {inp.min}")
                if inp.max is not None and value > inp.max:
                    errors.append(f"参数 {inp.name} 不能大于 {inp.max}")
            
            # 字符串长度检查
            if isinstance(value, str):
                if inp.min_length is not None and len(value) < inp.min_length:
                    errors.append(f"参数 {inp.name} 长度不能小于 {inp.min_length}")
                if inp.max_length is not None and len(value) > inp.max_length:
                    errors.append(f"参数 {inp.name} 长度不能大于 {inp.max_length}")
            
            # 枚举检查
            if inp.choices is not None and value not in inp.choices:
                errors.append(f"参数 {inp.name} 必须是以下值之一: {inp.choices}")
        
        return errors
    
    def get_defaults(self) -> Dict[str, Any]:
        """获取所有默认值"""
        defaults = {}
        for inp in self.inputs.values():
            if inp.default is not None:
                defaults[inp.name] = inp.default
        return defaults


# ============================================================
# 辅助函数
# ============================================================

def _type_to_json_type(t: Type) -> str:
    """Python 类型转 JSON Schema 类型"""
    if t is None:
        return "string"
    
    # 处理特殊类型
    if t in (Image, File, Audio):
        return "string"  # 文件类型在 JSON Schema 中用 string + format
    if t is Files:
        return "array"  # 多文件类型用 array
    
    # 处理基础类型
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    
    if t in type_map:
        return type_map[t]
    
    # 处理泛型类型 (List[str], Optional[int] 等)
    origin = get_origin(t)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    if origin is Union:
        # Optional[X] 是 Union[X, None]
        args = get_args(t)
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _type_to_json_type(non_none_args[0])
    
    # 处理 Literal
    if hasattr(t, "__origin__") and str(t.__origin__) == "typing.Literal":
        return "string"
    
    return "string"


def _type_to_format(t: Type) -> str:
    """类型转 JSON Schema format"""
    format_map = {
        Image: "image",
        File: "file",
        Audio: "audio",
        Files: "files",
    }
    return format_map.get(t, "")


def _type_to_form_type(t: Type) -> str:
    """类型转前端表单组件类型"""
    form_type_map = {
        str: "text",
        int: "number",
        float: "number",
        bool: "switch",
        list: "array",
        dict: "object",
        Image: "image-upload",
        File: "file-upload",
        Audio: "audio-upload",
        Files: "files-upload",
    }
    
    if t in form_type_map:
        return form_type_map[t]
    
    # 处理泛型
    origin = get_origin(t)
    if origin is list:
        return "array"
    
    # Literal 类型用下拉选择
    if hasattr(t, "__origin__") and str(t.__origin__) == "typing.Literal":
        return "select"
    
    return "text"
