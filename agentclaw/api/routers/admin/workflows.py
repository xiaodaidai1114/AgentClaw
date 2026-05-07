"""
工作流 API 路由
"""

from typing import Optional, List
from datetime import datetime
from pathlib import Path
import importlib.util
import re
import traceback
import uuid
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel

from agentclaw.api.schemas import (
    WorkflowListResponse,
    WorkflowDetailResponse,
    WorkflowStats,
    WorkflowInfo,
    WorkflowStructure,
)
from agentclaw.api.schemas.common import ErrorCode, APIError
from agentclaw.api.schemas.dashboard import (
    NodeModelUpdateRequest,
    NodeModelUpdateResponse,
    TrendData,
)
from agentclaw.api.services import get_workflow_service, WorkflowService
from agentclaw.logger.config import get_logger
from agentclaw.runtime_paths import resolve_runtime_path_context

logger = get_logger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])

# 缓存 builtin server 的工具列表（启动一次子进程后永久缓存）
# key: (srv_name, skills_dir, working_dir) → [{name, description}]
_builtin_tool_schema_cache: dict = {}


class RegisterWorkflowFileRequest(BaseModel):
    file_path: str
    workflow_id: Optional[str] = None
    force_replace: bool = True
    ensure_prompt_loaded: bool = True


@router.get("", response_model=WorkflowListResponse, summary="List workflows")
async def list_workflows(
    include_builtin: bool = Query(False, description="Include built-in agent"),
    time_range: str = Query("24h", description="Stats time range: 24h, 7d, 30d"),
    service: WorkflowService = Depends(get_workflow_service),
):
    """List all registered workflows with basic info and stats summary."""
    workflows = await service.list_workflows_with_stats(
        include_builtin=include_builtin,
        time_range=time_range,
    )
    return WorkflowListResponse(workflows=[WorkflowInfo(**wf) for wf in workflows])


@router.post("/register-file", summary="Register workflow from file at runtime")
async def register_workflow_from_file(request: RegisterWorkflowFileRequest):
    """
    在运行中的服务进程内导入 workflow 文件并完成注册，无需重启服务。
    """
    from agentclaw.api.registry import WorkflowRegistry
    from agentclaw.config import get_config

    config = get_config()
    project_dir = Path(config.project.project_dir or Path.cwd()).resolve()

    raw_path = Path(request.file_path)
    target_path = raw_path if raw_path.is_absolute() else (project_dir / raw_path)
    target_path = target_path.resolve()

    try:
        target_path.relative_to(project_dir)
    except ValueError:
        raise APIError(
            error=f"文件路径超出项目目录: {request.file_path}",
            code=ErrorCode.INVALID_REQUEST,
            status_code=400,
        )

    if not target_path.is_file():
        raise APIError(
            error=f"文件不存在: {target_path}",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
        )

    before_ids = {wf.id for wf in WorkflowRegistry.list_all()}
    replaced_id = None
    module_name = ""

    def _import_once():
        module_alias = f"_agentclaw_hotload_{target_path.stem}_{uuid.uuid4().hex[:8]}"
        spec = importlib.util.spec_from_file_location(module_alias, str(target_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载模块规格: {target_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return module_alias, mod

    loaded_module = None
    try:
        module_name, loaded_module = _import_once()
    except Exception as first_error:
        err_msg = str(first_error)
        duplicate_match = re.search(r"Workflow ID '([^']+)' already registered", err_msg)
        duplicate_id = request.workflow_id or (duplicate_match.group(1) if duplicate_match else None)
        if request.force_replace and duplicate_id:
            replaced_id = duplicate_id
            WorkflowRegistry.unregister(duplicate_id)
            try:
                module_name, loaded_module = _import_once()
            except Exception as retry_error:
                raise APIError(
                    error=f"热注册失败（重试后仍失败）: {retry_error}",
                    code=ErrorCode.OPERATION_FAILED,
                    status_code=500,
                    detail=traceback.format_exc()[-4000:],
                )
        else:
            raise APIError(
                error=f"热注册失败: {first_error}",
                code=ErrorCode.OPERATION_FAILED,
                status_code=500,
                detail=traceback.format_exc()[-4000:],
            )

    # Fallback: auto-discover factory functions if exec_module didn't register workflows
    if loaded_module is not None and {wf.id for wf in WorkflowRegistry.list_all()} == before_ids:
        for attr_name in dir(loaded_module):
            if attr_name.startswith("create_") and attr_name.endswith("_workflow"):
                factory = getattr(loaded_module, attr_name, None)
                if callable(factory):
                    try:
                        factory()
                    except Exception:
                        pass
        # Fallback 2: find Workflow instances and publish directly
        if {wf.id for wf in WorkflowRegistry.list_all()} == before_ids:
            from agentclaw.graph.workflow import Workflow as _Workflow
            for attr_name in dir(loaded_module):
                obj = getattr(loaded_module, attr_name, None)
                if isinstance(obj, _Workflow) and obj.id and obj.id not in before_ids:
                    try:
                        obj.publish()
                    except Exception:
                        pass

    after_ids = {wf.id for wf in WorkflowRegistry.list_all()}
    added_ids = sorted(after_ids - before_ids)

    touched_ids: list[str] = []
    if request.workflow_id and WorkflowRegistry.get(request.workflow_id):
        touched_ids = [request.workflow_id]
    elif added_ids:
        touched_ids = added_ids
    elif replaced_id and WorkflowRegistry.get(replaced_id):
        touched_ids = [replaced_id]

    if request.ensure_prompt_loaded:
        for wf_id in touched_ids:
            wf = WorkflowRegistry.get(wf_id)
            if not wf:
                continue
            try:
                wf._ensure_components()
                if wf._prompt_manager and hasattr(wf._prompt_manager, "_ensure_db_loaded"):
                    await wf._prompt_manager._ensure_db_loaded()
            except Exception as e:
                logger.warning(f"工作流 {wf_id} 延迟加载提示词失败: {e}")

    return {
        "success": True,
        "project_dir": str(project_dir),
        "file_path": str(target_path),
        "module_name": module_name,
        "replaced_workflow_id": replaced_id,
        "registered_workflow_ids": touched_ids,
        "added_workflow_ids": added_ids,
    }


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse, summary="Get workflow detail")
async def get_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Get workflow structure (nodes, edges) and statistics."""
    structure = service.get_workflow_structure(workflow_id)
    if not structure:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )

    feedback = await service.get_workflow_feedback_summary(workflow_id)
    structure["like_count"] = feedback.get("like_count", 0)
    structure["dislike_count"] = feedback.get("dislike_count", 0)
    
    stats = await service.get_workflow_stats_summary(workflow_id)
    
    return WorkflowDetailResponse(
        workflow=WorkflowStructure(**structure),
        stats=WorkflowStats(**stats) if stats else None,
    )


@router.get("/{workflow_id}/stats", response_model=WorkflowStats, summary="Get workflow stats")
async def get_workflow_stats(
    workflow_id: str,
    start_date: Optional[datetime] = Query(None, description="Start time filter"),
    end_date: Optional[datetime] = Query(None, description="End time filter"),
    service: WorkflowService = Depends(get_workflow_service),
):
    """Get workflow execution statistics, optionally filtered by time range."""
    # 验证工作流存在
    wf = service.get_workflow(workflow_id)
    if not wf:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    
    stats = await service.get_workflow_stats(workflow_id, start_date, end_date)
    return WorkflowStats(**stats)


@router.get("/{workflow_id}/trends", response_model=TrendData, summary="Get workflow trends")
async def get_workflow_trends(
    workflow_id: str,
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    service: WorkflowService = Depends(get_workflow_service),
):
    """Get workflow execution trends aggregated by time."""
    # 验证工作流存在
    wf = service.get_workflow(workflow_id)
    if not wf:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    
    trends = await service.get_workflow_trends(workflow_id, time_range)
    return TrendData(**trends)


@router.put("/{workflow_id}/nodes/{node_id}/model", response_model=NodeModelUpdateResponse, summary="Update node model")
async def update_node_model(
    workflow_id: str,
    node_id: str,
    request: NodeModelUpdateRequest,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Switch the LLM model used by a specific node."""
    # 验证工作流存在
    wf = service.get_workflow(workflow_id)
    if not wf:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    
    result = service.update_node_model(workflow_id, node_id, request.model_id)
    
    if not result["success"]:
        raise APIError(
            error=result.get("message", "更新失败"),
            code=ErrorCode.OPERATION_FAILED,
            status_code=400,
        )
    
    return NodeModelUpdateResponse(
        success=True,
        workflow_id=workflow_id,
        node_id=node_id,
        model_id=request.model_id,
        message="模型切换成功",
    )


# ============================================================
# 工具配置 API（Skills / MCP 工具启用/禁用）
# ============================================================

class ToolConfigRequest(BaseModel):
    disabled_skills: Optional[list] = None
    disabled_tools: Optional[list] = None


@router.get("/{workflow_id}/tool-config")
async def get_tool_config(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
):
    """
    获取工作流的工具配置（可用的 skills/tools 列表 + 禁用状态）
    """
    wf = service.get_workflow(workflow_id)
    if not wf:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    
    from agentclaw.api.services.tool_config_service import get_tool_config_manager
    from agentclaw.api.registry import WorkflowRegistry
    
    manager = get_tool_config_manager()
    config = manager.get_config(workflow_id)
    
    workflow = WorkflowRegistry.get(workflow_id)
    available_skills = []
    available_tools = []
    
    if workflow:
        workflow._ensure_components()
        
        # 收集 LLMNode 中实际引用的 tools 和 skills
        from agentclaw.node.llm import LLMNode
        
        llm_uses_skills = False       # 是否有 LLMNode 使用了 skills
        llm_uses_builtin_skills = False  # 是否有 LLMNode 启用了内置 skills
        llm_tool_names: set = set()   # LLMNode 引用的 MCP 工具名
        llm_tools_wildcard = False    # 是否有 LLMNode 使用 tools="*"
        
        for node in workflow._nodes.values():
            if not isinstance(node, LLMNode):
                continue
            # skills
            if node.skills:
                llm_uses_skills = True
            if node.enable_builtin_skills:
                llm_uses_builtin_skills = True
                llm_uses_skills = True
            # tools
            if node.tools:
                if node.tools == "*" or node.tools == ["*"]:
                    llm_tools_wildcard = True
                elif isinstance(node.tools, list):
                    llm_tool_names.update(node.tools)
                elif isinstance(node.tools, str):
                    llm_tool_names.add(node.tools)
        
        # Skills — 只在有 LLMNode 使用 skills 时才列出（项目 skills + 内置 skills）
        if llm_uses_skills:
            disabled_skills_set = set(config.get("disabled_skills", []))
            seen_skills = set()

            if workflow._skill_manager:
                for skill in workflow._skill_manager.list():
                    if skill.name in seen_skills:
                        continue
                    seen_skills.add(skill.name)
                    available_skills.append({
                        "name": skill.name,
                        "description": skill.description,
                        "disabled": skill.name in disabled_skills_set,
                    })

            if llm_uses_builtin_skills:
                try:
                    from agentclaw.skills import get_builtin_skill_manager

                    builtin_skill_manager = get_builtin_skill_manager(auto_init=True)
                    if builtin_skill_manager:
                        for skill in builtin_skill_manager.list():
                            if skill.name in seen_skills:
                                continue
                            seen_skills.add(skill.name)
                            available_skills.append({
                                "name": skill.name,
                                "description": f"{skill.description} (builtin)",
                                "disabled": skill.name in disabled_skills_set,
                            })
                except Exception as e:
                    logger.warning(f"获取 builtin skills 失败: {e}")
        
        # MCP Tools — 按 server 分组，只列出 LLMNode 引用的工具（MCPNode 的工具不可关）
        tool_groups = []  # [{server: str, tools: [{name, description, disabled}]}]
        disabled_tools_set = set(config.get("disabled_tools", []))

        # 收集 LLMNode 的 builtin 配置
        llm_uses_builtin_tools = False
        for node in workflow._nodes.values():
            if not isinstance(node, LLMNode):
                continue
            if node.enable_builtin_tools:
                llm_uses_builtin_tools = True

        # Custom Tools — @workflow.tool 注册的自定义工具
        from agentclaw.node.toolkit import ToolKit
        custom_tools = []
        if isinstance(workflow._toolkit, ToolKit) and workflow._toolkit._tools:
            for tool_name, tool_def in workflow._toolkit._tools.items():
                if llm_tools_wildcard or tool_name in llm_tool_names:
                    custom_tools.append({
                        "name": tool_name,
                        "description": getattr(tool_def, "description", "") or "",
                        "disabled": tool_name in disabled_tools_set,
                    })
        if custom_tools:
            tool_groups.append({
                "server": "🔧 custom-tools",
                "tools": custom_tools,
            })

        # Framework-published MCP tools — functions/ToolKit exposed through AgentClaw MCP routes
        try:
            from agentclaw.mcp.token_manager import MCPServerRegistry

            for server_name, published_tools in MCPServerRegistry.get_instance().get_published_tool_groups():
                server_tools = []
                for tool in published_tools:
                    if llm_tools_wildcard or llm_uses_builtin_tools or tool.name in llm_tool_names:
                        server_tools.append({
                            "name": tool.name,
                            "description": tool.description,
                            "disabled": tool.name in disabled_tools_set,
                        })
                if server_tools:
                    tool_groups.append({
                        "server": f"🌐 {server_name} (published MCP)",
                        "tools": server_tools,
                    })
        except Exception as e:
            logger.warning(f"获取框架发布 MCP 工具列表失败: {e}")

        if (llm_tools_wildcard or llm_tool_names) and workflow._mcp_toolkit:
            try:
                # 只在 MCP 已连接时列出工具，不在页面加载时阻塞连接
                if workflow._mcp_toolkit.is_connected:
                    mcp_manager = workflow._mcp_toolkit._manager
                    if mcp_manager:
                        # 按 server 遍历
                        for server_name in mcp_manager.list_servers():
                            server_tools = []
                            for tool in mcp_manager.list_tools(server_name):
                                if not tool.name:
                                    continue
                                if llm_tools_wildcard or tool.name in llm_tool_names:
                                    server_tools.append({
                                        "name": tool.name,
                                        "description": getattr(tool, "description", ""),
                                        "disabled": tool.name in disabled_tools_set,
                                    })
                            if server_tools:
                                tool_groups.append({
                                    "server": server_name,
                                    "tools": server_tools,
                                })
                else:
                    # MCP 未连接，在后台触发连接（不阻塞当前请求）
                    import asyncio
                    asyncio.create_task(workflow._ensure_mcp_connected())
            except Exception as e:
                logger.warning(f"获取 MCP 工具列表失败: {e}")
        
        # Builtin Tools — 动态获取所有激活的内置 MCP server 的工具列表
        # 所有内置 MCP server（含 planning-tools）统一由 enable_builtin_tools 控制
        builtin_conditions = {
            "skill-tools": llm_uses_builtin_tools,
            "planning-tools": llm_uses_builtin_tools,
        }
        # enable_builtin_tools 控制所有 builtin server
        from agentclaw.mcp.builtin_servers import BUILTIN_SERVERS
        for srv_name in BUILTIN_SERVERS:
            if srv_name not in builtin_conditions:
                builtin_conditions[srv_name] = llm_uses_builtin_tools

        # 构建缓存 key 所需的参数
        runtime_paths = resolve_runtime_path_context(
            workflow_id=workflow.id,
            skill_manager=workflow._skill_manager,
        )
        _skills_dir = runtime_paths.skills_dir
        _working_dir = runtime_paths.skill_tools_working_dir

        # 使用 LLMNode 的全局共享缓存，这样 tool-config 启动的 server 可被 LLMNode 复用
        from agentclaw.node.llm import (
            _shared_builtin_mcp_cache,
            _shared_builtin_mcp_cache_sig,
            _shared_builtin_mcp_cache_lock,
            LLMNode,
        )

        for srv_name, is_active in builtin_conditions.items():
            if not is_active:
                continue
            try:
                # 1. 先检查 schema 缓存（不需要启动子进程）
                schema_cache_key = (srv_name, _skills_dir, _working_dir)
                cached_tools = _builtin_tool_schema_cache.get(schema_cache_key)
                if cached_tools is not None:
                    if cached_tools:
                        tool_groups.append({
                            "server": f"⚙️ {srv_name} (builtin)",
                            "tools": [
                                {**t, "disabled": t["name"] in disabled_tools_set}
                                for t in cached_tools
                            ],
                        })
                    continue

                from agentclaw.mcp import MCPManager, MCPServerConfig
                from agentclaw.mcp.builtin_servers import get_builtin_server_config
                srv_config = get_builtin_server_config(
                    srv_name,
                    skills_dir=_skills_dir,
                    working_dir=_working_dir,
                    models_config=runtime_paths.models_config,
                    project_dir=runtime_paths.coding_tools_project_dir,
                )
                if not srv_config:
                    _builtin_tool_schema_cache[schema_cache_key] = []
                    continue
                srv_config["disabled"] = False

                # 2. 检查 LLMNode 共享缓存（可能已有运行中的 manager）
                signature = LLMNode._builtin_mcp_signature(srv_name, srv_config)
                manager = None
                async with _shared_builtin_mcp_cache_lock:
                    existing = _shared_builtin_mcp_cache.get(srv_name)
                    if existing and _shared_builtin_mcp_cache_sig.get(srv_name) == signature:
                        manager = existing

                # 3. 没有缓存：创建并存入共享缓存（不断开，给 LLMNode 复用）
                if not manager:
                    manager = MCPManager()
                    manager.add_server(MCPServerConfig.from_dict(srv_name, srv_config))
                    await manager.connect(srv_name)
                    async with _shared_builtin_mcp_cache_lock:
                        old = _shared_builtin_mcp_cache.get(srv_name)
                        if old and old is not manager:
                            try:
                                await old.disconnect_all()
                            except Exception:
                                pass
                        _shared_builtin_mcp_cache[srv_name] = manager
                        _shared_builtin_mcp_cache_sig[srv_name] = signature

                server_tools = []
                for tool in manager.list_tools(srv_name):
                    if tool.name:
                        server_tools.append({
                            "name": tool.name,
                            "description": getattr(tool, "description", ""),
                        })

                # 缓存工具列表（后续请求直接用 schema 缓存，不再查 manager）
                _builtin_tool_schema_cache[schema_cache_key] = server_tools

                if server_tools:
                    tool_groups.append({
                        "server": f"⚙️ {srv_name} (builtin)",
                        "tools": [
                            {**t, "disabled": t["name"] in disabled_tools_set}
                            for t in server_tools
                        ],
                    })
            except Exception as e:
                logger.warning(f"获取 builtin server '{srv_name}' 工具列表失败: {e}")

    # 生成 warnings（仅对 __builtin__ 工作流）
    warnings = []
    if workflow_id == "__builtin__":
        # 收集当前实际可用的工具名
        actual_tools = set()
        for group in tool_groups:
            for tool in group["tools"]:
                actual_tools.add(tool["name"])
        actual_skills = {skill["name"] for skill in available_skills}

        # 检查配置文件中禁用的工具是否仍然可用
        disabled_tools_set = set(config.get("disabled_tools", []))
        disabled_skills_set = set(config.get("disabled_skills", []))

        for tool_name in disabled_tools_set:
            if tool_name not in actual_tools:
                warnings.append({
                    "type": "tool",
                    "name": tool_name,
                    "message": f"工具 '{tool_name}' 已不可用（可能已被移除或 MCP server 未启动）",
                })

        for skill_name in disabled_skills_set:
            if skill_name not in actual_skills:
                warnings.append({
                    "type": "skill",
                    "name": skill_name,
                    "message": f"Skill '{skill_name}' 已不可用（可能已被移除）",
                })

    return {
        "workflow_id": workflow_id,
        "skills": available_skills,
        "tool_groups": tool_groups,
        "disabled_skills": config.get("disabled_skills", []),
        "disabled_tools": config.get("disabled_tools", []),
        "warnings": warnings,
    }


@router.put("/{workflow_id}/tool-config")
async def update_tool_config(
    workflow_id: str,
    request: ToolConfigRequest,
    service: WorkflowService = Depends(get_workflow_service),
):
    """
    更新工作流的工具配置（禁用/启用 skills 和 tools）
    
    内存级配置，重启后恢复默认
    """
    wf = service.get_workflow(workflow_id)
    if not wf:
        raise APIError(
            error=f"工作流 '{workflow_id}' 不存在",
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            status_code=404,
        )
    
    from agentclaw.api.services.tool_config_service import get_tool_config_manager
    
    manager = get_tool_config_manager()
    config = manager.set_config(
        workflow_id,
        disabled_skills=request.disabled_skills,
        disabled_tools=request.disabled_tools,
    )
    
    return {"success": True, **config}


@router.post("/{workflow_id}/tool-config/reset")
async def reset_tool_config(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
):
    """重置工具配置（全部启用）"""
    from agentclaw.api.services.tool_config_service import get_tool_config_manager
    
    manager = get_tool_config_manager()
    config = manager.reset_config(workflow_id)
    
    return {"success": True, **config}
