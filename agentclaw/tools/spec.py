"""
ToolSpec - 统一工具规范

把异构工具（Python 函数 / HTTP API / CLI 脚本）统一成一份规范，
供 MCP server 注册给 AI 使用。

规范字段：
    name          工具名（snake_case，AI 调用用）
    description   描述（AI 看这个决定何时调用，写清楚「做什么 + 何时用」）
    input_schema  JSON Schema（参数定义）
    handler       实现适配（type: python | http | cli + 类型特定字段）
    permission    权限（read_only / write_with_approval / write_auto，Phase 9 RBAC 接）
    domain        所属领域（可选，用于按 domain 过滤）
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


HandlerType = Literal["python", "http", "cli"]

PERMISSION_READ_ONLY = "read_only"
PERMISSION_WRITE_WITH_APPROVAL = "write_with_approval"
PERMISSION_WRITE_AUTO = "write_auto"
ALL_PERMISSIONS = frozenset({
    PERMISSION_READ_ONLY,
    PERMISSION_WRITE_WITH_APPROVAL,
    PERMISSION_WRITE_AUTO,
})


class HandlerSpec(BaseModel):
    """
    工具实现适配。按 type 提供对应字段：

    python: module + function（反射调用，支持 async）
    http:   method + url（{param} 占位）+ auth_env（env 变量名）+ body_template
    cli:    command + args（{param} 占位）+ cwd
    """
    type: HandlerType

    # python
    module: str = ""
    function: str = ""

    # http
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    auth_env: str = ""                # 环境变量名（Bearer token），密钥不进配置
    body_template: Optional[str] = None  # JSON 字符串模板，含 {param} 占位

    # cli
    command: str = ""
    args: List[str] = Field(default_factory=list)
    cwd: str = ""

    # 公共
    timeout: float = 30.0


class ToolSpec(BaseModel):
    """统一工具规范"""
    name: str
    description: str
    input_schema: Dict[str, Any]      # JSON Schema（type/properties/required）
    handler: HandlerSpec
    permission: str = PERMISSION_READ_ONLY
    domain: str = ""

    def to_mcp_tool(self):
        """转 MCP Tool 定义（name/description/inputSchema）"""
        from mcp import Tool  # type: ignore
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )
