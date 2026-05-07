# -*- coding: utf-8 -*-
"""
调试 API 端点

提供工作流调试功能的 REST API
"""

from typing import Optional, List
import asyncio
import json
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from agentclaw.runtime.debugger import (
    get_session_manager,
    WorkflowDebugger,
    BreakpointType,
    DebugStatus,
)
from agentclaw.api.registry import WorkflowRegistry
from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def _get_input_schema(workflow) -> dict:
    """
    获取工作流的输入参数 schema 信息
    """
    if workflow._input_schema:
        return workflow._input_schema.to_dict()
    return None

router = APIRouter(prefix="/debug", tags=["debug"])


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workflow_id: str
    thread_id: Optional[str] = Field(None, alias="conversation_id")


class CreateSessionResponse(BaseModel):
    session_id: str
    workflow_id: str
    status: str


class BreakpointRequest(BaseModel):
    node_id: str
    type: str = "before"  # before / after
    condition: Optional[str] = None


class BreakpointResponse(BaseModel):
    id: str
    node_id: str
    type: str
    condition: Optional[str]
    enabled: bool
    hit_count: int


class ModifyStateRequest(BaseModel):
    state: dict


class SessionStatusResponse(BaseModel):
    session_id: str
    workflow_id: str
    status: str
    current_node: Optional[str]
    breakpoints: List[dict]
    history_count: int
    created_at: str
    paused_at: Optional[str]


# ============================================================================
# Session Management
# ============================================================================

@router.get("/sessions")
async def list_sessions():
    """列出所有调试会话"""
    manager = get_session_manager()
    return {"sessions": manager.list_sessions()}


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建调试会话"""
    # 验证工作流存在
    workflow = WorkflowRegistry.get(request.workflow_id)
    if not workflow:
        raise HTTPException(404, f"工作流 '{request.workflow_id}' 不存在")
    
    manager = get_session_manager()
    session = manager.create_session(
        workflow_id=request.workflow_id,
        thread_id=request.thread_id,
    )
    
    return CreateSessionResponse(
        session_id=session.id,
        workflow_id=session.workflow_id,
        status=session.status.value,
    )


@router.get("/workflows/{workflow_id}/schema")
async def get_workflow_input_schema(workflow_id: str):
    """
    获取工作流的输入参数 schema 信息
    
    返回必填字段、默认值等信息，供前端展示输入表单
    """
    workflow = WorkflowRegistry.get(workflow_id)
    if not workflow:
        raise HTTPException(404, f"工作流 '{workflow_id}' 不存在")
    
    schema = _get_input_schema(workflow)
    
    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.name,
        "input_schema": schema,
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取调试会话详情"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    return {
        "session_id": session.id,
        "workflow_id": session.workflow_id,
        "thread_id": session.thread_id,
        "status": session.status.value,
        "current_node": session.current_node,
        "current_state": session.current_state,
        "breakpoints": [
            {
                "id": bp_id,
                "node_id": bp.node_id,
                "type": bp.type.value,
                "condition": bp.condition,
                "enabled": bp.enabled,
                "hit_count": bp.hit_count,
            }
            for bp_id, bp in session.breakpoints.items()
        ],
        "history": session.history[-20:],  # 最近 20 条
        "created_at": session.created_at.isoformat(),
        "paused_at": session.paused_at.isoformat() if session.paused_at else None,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除调试会话"""
    manager = get_session_manager()
    if manager.remove_session(session_id):
        return {"success": True}
    raise HTTPException(404, f"调试会话 '{session_id}' 不存在")


# ============================================================================
# Breakpoint Management
# ============================================================================

@router.get("/sessions/{session_id}/breakpoints")
async def list_breakpoints(session_id: str):
    """列出会话的所有断点"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    
    return {"breakpoints": debugger.list_breakpoints()}


@router.post("/sessions/{session_id}/breakpoints", response_model=BreakpointResponse)
async def add_breakpoint(session_id: str, request: BreakpointRequest):
    """添加断点"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    if not workflow:
        raise HTTPException(404, f"工作流 '{session.workflow_id}' 不存在")
    
    # 验证节点存在
    if request.node_id not in workflow._nodes:
        raise HTTPException(400, f"节点 '{request.node_id}' 不存在")
    
    # 解析断点类型
    try:
        bp_type = BreakpointType(request.type)
    except ValueError:
        raise HTTPException(400, f"无效的断点类型: {request.type}")
    
    debugger = WorkflowDebugger(workflow, session)
    bp_id = debugger.set_breakpoint(
        node_id=request.node_id,
        bp_type=bp_type,
        condition=request.condition,
    )
    
    bp = session.breakpoints[bp_id]
    return BreakpointResponse(
        id=bp_id,
        node_id=bp.node_id,
        type=bp.type.value,
        condition=bp.condition,
        enabled=bp.enabled,
        hit_count=bp.hit_count,
    )


@router.delete("/sessions/{session_id}/breakpoints/{bp_id}")
async def remove_breakpoint(session_id: str, bp_id: str):
    """移除断点"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    
    if debugger.remove_breakpoint(bp_id):
        return {"success": True}
    raise HTTPException(404, f"断点 '{bp_id}' 不存在")


@router.post("/sessions/{session_id}/breakpoints/{bp_id}/toggle")
async def toggle_breakpoint(session_id: str, bp_id: str):
    """切换断点启用状态"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    
    enabled = debugger.toggle_breakpoint(bp_id)
    return {"enabled": enabled}


# ============================================================================
# Debug Control
# ============================================================================

@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, request: Optional[ModifyStateRequest] = None):
    """继续执行"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    if session.status != DebugStatus.PAUSED:
        raise HTTPException(400, f"会话未暂停，当前状态: {session.status.value}")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    
    modified_state = request.state if request else None
    debugger.resume(modified_state)
    
    return {"success": True, "status": "running"}


@router.post("/sessions/{session_id}/step")
async def step_session(session_id: str):
    """单步执行"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    if session.status != DebugStatus.PAUSED:
        raise HTTPException(400, f"会话未暂停，当前状态: {session.status.value}")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    debugger.step()
    
    return {"success": True, "status": "stepping"}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    """停止执行"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    debugger.stop()
    
    return {"success": True, "status": "stopped"}


# ============================================================================
# State Management
# ============================================================================

@router.get("/sessions/{session_id}/state")
async def get_state(session_id: str):
    """获取当前状态"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    return {
        "state": session.current_state,
        "status": session.status.value,
        "current_node": session.current_node,
    }


@router.put("/sessions/{session_id}/state")
async def update_state(session_id: str, request: ModifyStateRequest):
    """修改状态（仅在暂停时有效）"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    if session.status != DebugStatus.PAUSED:
        raise HTTPException(400, f"只能在暂停时修改状态，当前状态: {session.status.value}")
    
    workflow = WorkflowRegistry.get(session.workflow_id)
    debugger = WorkflowDebugger(workflow, session)
    debugger.set_state(request.state)
    
    return {"success": True, "state": request.state}


# ============================================================================
# Debug Run (启动带调试的工作流执行)
# ============================================================================

class DebugRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workflow_id: str
    input_data: dict = {}
    thread_id: Optional[str] = Field(None, alias="conversation_id")
    breakpoints: List[BreakpointRequest] = []


@router.post("/run")
async def debug_run(request: DebugRunRequest):
    """
    启动带调试的工作流执行
    
    这个端点会：
    1. 创建调试会话
    2. 设置断点
    3. 启动工作流执行（异步后台任务）
    
    客户端需要通过轮询 /sessions/{session_id} 获取状态
    """
    workflow = WorkflowRegistry.get(request.workflow_id)
    if not workflow:
        raise HTTPException(404, f"工作流 '{request.workflow_id}' 不存在")
    
    # 获取输入参数 schema
    schema = _get_input_schema(workflow)
    
    # 校验必填字段
    if schema and schema.get("required"):
        missing = set(schema["required"]) - set(request.input_data.keys())
        if missing:
            raise HTTPException(
                400, 
                f"缺少必填字段: {', '.join(sorted(missing))}"
            )
    
    manager = get_session_manager()
    session = manager.create_session(
        workflow_id=request.workflow_id,
        thread_id=request.thread_id,
    )
    
    debugger = WorkflowDebugger(workflow, session)
    
    # 设置断点
    for bp in request.breakpoints:
        try:
            bp_type = BreakpointType(bp.type)
        except ValueError:
            bp_type = BreakpointType.BEFORE
        debugger.set_breakpoint(bp.node_id, bp_type, bp.condition)
    
    # 填充默认值
    input_data = request.input_data.copy()
    if schema and schema.get("defaults"):
        for key, value in schema["defaults"].items():
            if key not in input_data:
                # 复制可变对象
                if isinstance(value, (list, dict, set)):
                    input_data[key] = type(value)(value)
                else:
                    input_data[key] = value
    
    # 处理文件类型输入（将 base64 保存为本地文件）
    from agentclaw.database import process_file_inputs
    workflow_inputs = workflow._input_schema.inputs.values() if workflow._input_schema else None
    input_data = await process_file_inputs(input_data, list(workflow_inputs) if workflow_inputs else None)
    
    # 启动异步执行任务
    import asyncio
    asyncio.create_task(_execute_debug_workflow(
        workflow=workflow,
        session_id=session.id,
        input_data=input_data,
        thread_id=request.thread_id,
    ))
    
    return {
        "session_id": session.id,
        "workflow_id": session.workflow_id,
        "thread_id": session.thread_id,
        "status": session.status.value,
        "breakpoints": debugger.list_breakpoints(),
        "input_schema": schema,
        "message": "调试执行已启动，请轮询会话状态",
    }


async def _execute_debug_workflow(
    workflow,
    session_id: str,
    input_data: dict,
    thread_id: Optional[str] = None,
):
    """
    后台任务：执行带调试的工作流
    
    这个函数会在后台运行工作流，并在遇到断点时暂停。
    注意：debug 模式不记录到执行追踪（trace）中。
    """
    from agentclaw.runtime.debugger import set_current_session
    
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        logger.error(f"调试会话 {session_id} 不存在")
        return
    
    # 设置当前调试会话（重要：在后台任务中需要手动设置）
    set_current_session(session)
    
    # 创建输出队列
    debug_queue = get_output_queue(session_id)
    
    try:
        logger.info(f"开始调试执行: workflow={workflow.id}, session={session_id}")
        
        # 推送开始事件
        push_output(session_id, "status", {"status": "running", "message": "工作流开始执行"})
        
        # 使用内置引擎执行，直接传入调试队列
        result = await workflow.run(
            inputs=input_data,
            debug=True,
            debug_queue=debug_queue,
        )
        
        # 获取执行结果状态
        result_state = result.get("state", result) if isinstance(result, dict) else {}
        is_interrupted = result_state.get("__interrupted__", False)
        interrupt_node = result_state.get("__interrupt_node__")
        
        # 更新会话状态
        session.current_state = result_state
        
        if is_interrupted:
            # 工作流被中断（等待用户输入，如 HumanNode）
            session.status = DebugStatus.INTERRUPTED
            session.current_node = interrupt_node
            session.history.append({
                "action": "interrupted",
                "node": interrupt_node,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "detail": f"工作流在节点 {interrupt_node} 等待用户输入",
            })
            
            # 推送中断事件
            push_output(session_id, "status", {
                "status": "interrupted",
                "message": f"工作流在节点 {interrupt_node} 等待用户输入",
                "current_node": interrupt_node,
                "waiting_for_input": True,
            })
            
            logger.info(f"调试执行中断: session={session_id}, node={interrupt_node}")
        else:
            # 执行完成
            session.status = DebugStatus.COMPLETED
            session.current_node = None
            session.history.append({
                "action": "completed",
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "detail": "工作流执行完成",
            })
            
            # 推送完成事件
            push_output(session_id, "status", {"status": "completed", "message": "工作流执行完成"})
            
            logger.info(f"调试执行完成: session={session_id}")
        
    except asyncio.CancelledError:
        # 客户端断开连接，优雅处理
        logger.info(f"调试执行被取消（客户端断开）: session={session_id}")
        session.status = DebugStatus.STOPPED
        session.history.append({
            "action": "cancelled",
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "detail": "执行被取消（客户端断开）",
        })
        
    except Exception as e:
        logger.error(f"调试执行失败: session={session_id}, error={e}")
        session.status = DebugStatus.STOPPED
        session.history.append({
            "action": "error",
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "detail": f"执行失败: {str(e)}",
        })
        
        # 推送错误事件
        push_output(session_id, "error", {"message": str(e)})
    finally:
        # 清理当前会话
        set_current_session(None)


# ============================================================================
# Debug Stream (SSE 流式输出)
# ============================================================================

# 存储每个会话的输出队列
_session_output_queues: dict = {}


def get_output_queue(session_id: str) -> asyncio.Queue:
    """获取或创建会话的输出队列"""
    if session_id not in _session_output_queues:
        _session_output_queues[session_id] = asyncio.Queue(maxsize=1000)
    return _session_output_queues[session_id]


def push_output(session_id: str, event_type: str, data: dict):
    """推送输出到会话队列（供状态事件使用）"""
    if session_id in _session_output_queues:
        try:
            queue = _session_output_queues[session_id]
            queue.put_nowait({"event": event_type, "data": data})
        except asyncio.QueueFull:
            pass  # 队列满了就丢弃


def cleanup_output_queue(session_id: str):
    """清理会话的输出队列"""
    if session_id in _session_output_queues:
        del _session_output_queues[session_id]


@router.get("/sessions/{session_id}/stream")
async def stream_session_output(session_id: str):
    """
    SSE 流式输出调试会话的实时内容
    
    事件类型：
    - message: LLM 输出的文本片段
    - node_started: 节点开始执行
    - node_finished: 节点执行完成
    - tool: 工具调用
    - status: 会话状态变化
    - ping: 心跳
    """
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(404, f"调试会话 '{session_id}' 不存在")
    
    async def event_generator():
        queue = get_output_queue(session_id)
        last_status = session.status.value
        
        try:
            while True:
                # 检查会话状态
                current_session = manager.get_session(session_id)
                if not current_session:
                    yield f"event: status\ndata: {json.dumps({'status': 'deleted'})}\n\n"
                    break
                
                # 状态变化通知
                if current_session.status.value != last_status:
                    last_status = current_session.status.value
                    status_data = {
                        'status': last_status,
                        'current_node': current_session.current_node
                    }
                    
                    # 如果是中断状态，添加额外信息
                    if last_status == 'interrupted' and current_session.current_state:
                        status_data['waiting_for_input'] = True
                        status_data['interrupt_node'] = current_session.current_state.get("__interrupt_node__")
                    
                    yield f"event: status\ndata: {json.dumps(status_data)}\n\n"
                    
                    # 如果会话结束，发送最终状态后退出
                    # completed: 正常完成
                    # stopped: 手动停止
                    # error: 执行出错
                    # interrupted: 等待用户输入（本次执行已结束）
                    if last_status in ['completed', 'stopped', 'error', 'interrupted']:
                        await asyncio.sleep(0.5)  # 等待最后的输出
                        # 清空队列中剩余的消息
                        while not queue.empty():
                            try:
                                item = queue.get_nowait()
                                yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                            except asyncio.QueueEmpty:
                                break
                        break
                
                # 尝试从队列获取输出
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                except asyncio.TimeoutError:
                    # 发送心跳
                    yield f"event: ping\ndata: {json.dumps({'time': __import__('time').time()})}\n\n"
                    
        except asyncio.CancelledError:
            # 客户端断开连接，优雅退出
            logger.debug(f"调试 SSE 流被取消（客户端断开）: session={session_id}")
        except GeneratorExit:
            # 生成器被关闭
            logger.debug(f"调试 SSE 生成器关闭: session={session_id}")
        finally:
            # 不要在这里清理队列，因为可能有多个客户端连接
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
