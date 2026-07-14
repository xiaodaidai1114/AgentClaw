"""
企业工具管理 Admin API

文件驱动（tools/specs/*.yaml）的工具 CRUD + 测试调用。
/admin/* 由 AuthMiddleware 统一校验 Admin Token。

- GET    /admin/enterprise-tools           — 列出所有工具
- POST   /admin/enterprise-tools           — 新增/导入工具（写 YAML）
- GET    /admin/enterprise-tools/{name}    — 工具详情
- PUT    /admin/enterprise-tools/{name}    — 更新工具
- DELETE /admin/enterprise-tools/{name}    — 删除工具
- POST   /admin/enterprise-tools/{name}/test — 测试调用工具（不经过 MCP，直接 executor）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentclaw.tools import ToolExecutor, ToolSpec, load_specs
from agentclaw.tools.spec import ALL_PERMISSIONS

router = APIRouter(prefix="/enterprise-tools", tags=["enterprise-tools"])


def _specs_dir() -> Path:
    from agentclaw.config import get_config

    return Path(get_config().project.project_dir) / "tools" / "specs"


def _yaml_path(name: str) -> Path:
    return _specs_dir() / f"{name}.yaml"


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        raise HTTPException(
            status_code=400,
            detail="name 必须以字母开头，仅含小写字母/数字/下划线，2-64 字符",
        )
    return name


class ToolRequest(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Dict[str, Any]
    permission: str = "read_only"
    domain: str = ""


class TestRequest(BaseModel):
    arguments: Dict[str, Any] = {}


def _to_spec(req: ToolRequest) -> ToolSpec:
    if req.permission not in ALL_PERMISSIONS:
        raise HTTPException(status_code=400, detail=f"非法 permission: {req.permission}")
    try:
        return ToolSpec(
            name=req.name,
            description=req.description,
            input_schema=req.input_schema,
            handler=req.handler,
            permission=req.permission,
            domain=req.domain,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"工具规范校验失败: {e}")


def _write_yaml(spec: ToolSpec) -> None:
    d = _specs_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump(mode="json")
    _yaml_path(spec.name).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@router.get("", summary="列出所有企业工具")
async def list_tools():
    specs = load_specs(_specs_dir())
    return {"tools": [s.model_dump(mode="json") for s in specs]}


@router.post("", summary="新增/导入工具")
async def create_tool(req: ToolRequest):
    _validate_name(req.name)
    if _yaml_path(req.name).exists():
        raise HTTPException(status_code=409, detail=f"工具已存在: {req.name}")
    spec = _to_spec(req)
    _write_yaml(spec)
    return {"status": "created", "tool": spec.model_dump(mode="json")}


@router.get("/{name}", summary="工具详情")
async def get_tool(name: str):
    specs = {s.name: s for s in load_specs(_specs_dir())}
    spec = specs.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
    return spec.model_dump(mode="json")


@router.put("/{name}", summary="更新工具")
async def update_tool(name: str, req: ToolRequest):
    _validate_name(req.name)
    if not _yaml_path(name).exists():
        raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
    spec = _to_spec(req)
    if name != spec.name:
        _yaml_path(name).unlink(missing_ok=True)  # 改名：删旧文件
    _write_yaml(spec)
    return {"status": "updated", "tool": spec.model_dump(mode="json")}


@router.delete("/{name}", summary="删除工具")
async def delete_tool(name: str):
    p = _yaml_path(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
    p.unlink()
    return {"status": "deleted", "name": name}


@router.post("/{name}/test", summary="测试调用工具")
async def test_tool(name: str, req: TestRequest):
    specs = {s.name: s for s in load_specs(_specs_dir())}
    spec = specs.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
    executor = ToolExecutor(list(specs.values()))
    result = await executor.execute(name, req.arguments)
    return {"result": result}
