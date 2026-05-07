"""
Inputs - 输入参数定义模块

提供工作流输入参数的定义和验证功能。

支持三种定义方式：
1. 字典简写: inputs={"query": str, "count": int}
2. Input 对象: inputs=[Input("query", str, required=True)]
3. Pydantic 类: inputs=MyInputs (BaseModel 子类)

Example:
    from agentclaw import Workflow, Input
    from agentclaw.inputs import Image, File, Audio
    
    # 简单写法
    workflow = Workflow(id="simple", inputs={"query": str})
    
    # 带约束
    workflow = Workflow(
        id="complex",
        inputs=[
            Input("query", str, required=True, description="查询内容"),
            Input("count", int, default=10, min=1, max=100),
            Input("image", Image, description="上传图片"),
        ]
    )
"""

from agentclaw.inputs.types import (
    Input,
    InputSchema,
    Image,
    File,
    Files,
    Audio,
)
from agentclaw.inputs.parser import parse_inputs

__all__ = [
    "Input",
    "InputSchema",
    "Image",
    "File",
    "Files",
    "Audio",
    "parse_inputs",
]
