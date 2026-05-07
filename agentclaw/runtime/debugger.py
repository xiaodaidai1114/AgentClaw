# -*- coding: utf-8 -*-
"""
WorkflowDebugger - 交互式工作流调试器

支持：
- 设置断点（节点前/后）
- 暂停执行
- 查看/修改 State
- 单步执行
- 继续执行

使用方式：
    # 开发模式启动
    workflow.run(inputs, debug=True)
    
    # 或通过环境变量
    AgentClaw_DEBUG=true
"""

from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING
from contextvars import ContextVar

from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


class BreakpointType(str, Enum):
    """断点类型"""
    BEFORE = "before"  # 节点执行前
    AFTER = "after"    # 节点执行后


class DebugAction(str, Enum):
    """调试动作"""
    CONTINUE = "continue"    # 继续执行
    STEP = "step"            # 单步执行
    STEP_OVER = "step_over"  # 跳过当前节点
    STOP = "stop"            # 停止执行
    RESTART = "restart"      # 重新开始


class DebugStatus(str, Enum):
    """调试状态"""
    RUNNING = "running"      # 正在执行
    PAUSED = "paused"        # 已暂停（断点）
    INTERRUPTED = "interrupted"  # 已中断（等待用户输入，如 HumanNode）
    STOPPED = "stopped"      # 已停止
    COMPLETED = "completed"  # 已完成
    ERROR = "error"          # 出错


@dataclass
class Breakpoint:
    """断点定义"""
    node_id: str
    type: BreakpointType = BreakpointType.BEFORE
    condition: Optional[str] = None  # 条件表达式（可选）
    enabled: bool = True
    hit_count: int = 0
    
    def matches(self, node_id: str, bp_type: BreakpointType) -> bool:
        """检查是否匹配"""
        return self.enabled and self.node_id == node_id and self.type == bp_type


@dataclass
class NodeExecution:
    """节点执行记录"""
    node_id: str
    node_type: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: int = 0
    state_before: Optional[dict] = None
    state_after: Optional[dict] = None
    status: str = "running"  # running, completed, error
    error: Optional[str] = None


@dataclass
class DebugSession:
    """调试会话"""
    id: str
    workflow_id: str
    thread_id: Optional[str]
    status: DebugStatus = DebugStatus.RUNNING
    current_node: Optional[str] = None
    current_state: Optional[dict] = None
    breakpoints: Dict[str, Breakpoint] = field(default_factory=dict)
    history: List[dict] = field(default_factory=list)
    node_executions: List[NodeExecution] = field(default_factory=list)  # 节点执行历史
    created_at: datetime = field(default_factory=datetime.now)
    paused_at: Optional[datetime] = None
    
    # 内部控制
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _action: DebugAction = field(default=DebugAction.CONTINUE, repr=False)
    _step_mode: bool = field(default=False, repr=False)
    _modified_state: Optional[dict] = field(default=None, repr=False)
    
    def __post_init__(self):
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 初始不暂停


# 当前调试会话（ContextVar 用于请求隔离）
_current_debug_session: ContextVar[Optional[DebugSession]] = ContextVar(
    "current_debug_session", default=None
)


class DebugSessionManager:
    """调试会话管理器（单例）"""
    
    _instance: Optional["DebugSessionManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: Dict[str, DebugSession] = {}
            cls._instance._callbacks: List[Callable] = []
        return cls._instance
    
    def create_session(
        self,
        workflow_id: str,
        thread_id: Optional[str] = None,
    ) -> DebugSession:
        """创建调试会话"""
        session_id = str(uuid.uuid4())[:8]
        session = DebugSession(
            id=session_id,
            workflow_id=workflow_id,
            thread_id=thread_id,
        )
        self._sessions[session_id] = session
        logger.info(f"创建调试会话: {session_id} (workflow={workflow_id})")
        return session
    
    def get_session(self, session_id: str) -> Optional[DebugSession]:
        """获取调试会话"""
        return self._sessions.get(session_id)
    
    def get_sessions_by_workflow(self, workflow_id: str) -> List[DebugSession]:
        """获取工作流的所有调试会话"""
        return [s for s in self._sessions.values() if s.workflow_id == workflow_id]
    
    def remove_session(self, session_id: str) -> bool:
        """移除调试会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"移除调试会话: {session_id}")
            return True
        return False
    
    def list_sessions(self) -> List[dict]:
        """列出所有调试会话"""
        return [
            {
                "id": s.id,
                "workflow_id": s.workflow_id,
                "thread_id": s.thread_id,
                "status": s.status.value,
                "current_node": s.current_node,
                "created_at": s.created_at.isoformat(),
                "paused_at": s.paused_at.isoformat() if s.paused_at else None,
            }
            for s in self._sessions.values()
        ]
    
    def on_event(self, callback: Callable) -> None:
        """注册事件回调（用于 WebSocket 通知）"""
        self._callbacks.append(callback)
    
    async def _notify(self, event_type: str, session: DebugSession, data: dict = None):
        """通知所有回调"""
        event = {
            "type": event_type,
            "session_id": session.id,
            "workflow_id": session.workflow_id,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"调试事件回调失败: {e}")


# 全局会话管理器
_session_manager = DebugSessionManager()


def get_session_manager() -> DebugSessionManager:
    """获取会话管理器"""
    return _session_manager


def get_current_session() -> Optional[DebugSession]:
    """获取当前调试会话"""
    return _current_debug_session.get()


def set_current_session(session: Optional[DebugSession]) -> None:
    """设置当前调试会话"""
    _current_debug_session.set(session)


class WorkflowDebugger:
    """
    工作流调试器
    
    在节点执行前后检查断点，支持暂停、单步、修改状态等操作。
    
    Example:
        debugger = WorkflowDebugger(workflow)
        debugger.set_breakpoint("classify", BreakpointType.BEFORE)
        
        # 在工作流执行中使用
        state = await debugger.check_breakpoint("classify", state, BreakpointType.BEFORE)
        # ... 执行节点 ...
        state = await debugger.check_breakpoint("classify", state, BreakpointType.AFTER)
    """
    
    def __init__(self, workflow: "Workflow", session: Optional[DebugSession] = None):
        self.workflow = workflow
        self.session = session or _session_manager.create_session(
            workflow_id=workflow.id,
        )
        self._manager = _session_manager
    
    def set_breakpoint(
        self,
        node_id: str,
        bp_type: BreakpointType = BreakpointType.BEFORE,
        condition: Optional[str] = None,
    ) -> str:
        """
        设置断点
        
        Args:
            node_id: 节点名称
            bp_type: 断点类型（before/after）
            condition: 条件表达式（可选，如 "state['count'] > 5"）
        
        Returns:
            断点 ID
        """
        bp_id = f"{node_id}:{bp_type.value}"
        self.session.breakpoints[bp_id] = Breakpoint(
            node_id=node_id,
            type=bp_type,
            condition=condition,
        )
        logger.info(f"设置断点: {bp_id}")
        return bp_id
    
    def remove_breakpoint(self, bp_id: str) -> bool:
        """移除断点"""
        if bp_id in self.session.breakpoints:
            del self.session.breakpoints[bp_id]
            logger.info(f"移除断点: {bp_id}")
            return True
        return False
    
    def clear_breakpoints(self) -> None:
        """清除所有断点"""
        self.session.breakpoints.clear()
        logger.info("清除所有断点")
    
    def list_breakpoints(self) -> List[dict]:
        """列出所有断点"""
        return [
            {
                "id": bp_id,
                "node_id": bp.node_id,
                "type": bp.type.value,
                "condition": bp.condition,
                "enabled": bp.enabled,
                "hit_count": bp.hit_count,
            }
            for bp_id, bp in self.session.breakpoints.items()
        ]
    
    def toggle_breakpoint(self, bp_id: str) -> bool:
        """切换断点启用状态"""
        if bp_id in self.session.breakpoints:
            bp = self.session.breakpoints[bp_id]
            bp.enabled = not bp.enabled
            return bp.enabled
        return False
    
    async def check_breakpoint(
        self,
        node_id: str,
        state: dict,
        bp_type: BreakpointType,
    ) -> dict:
        """
        检查断点（在节点执行前/后调用）
        
        如果命中断点，会暂停执行并等待用户操作。
        
        Args:
            node_id: 当前节点名称
            state: 当前状态
            bp_type: 断点类型
        
        Returns:
            可能被修改的状态
        """
        # 检查是否需要暂停（单步模式或命中断点）
        should_pause = self.session._step_mode
        
        if not should_pause:
            # 检查断点
            bp_id = f"{node_id}:{bp_type.value}"
            bp = self.session.breakpoints.get(bp_id)
            if bp and bp.enabled:
                # 检查条件
                if bp.condition:
                    try:
                        should_pause = eval(bp.condition, {"state": state})
                    except Exception as e:
                        logger.warning(f"断点条件求值失败: {e}")
                        should_pause = True
                else:
                    should_pause = True
                
                if should_pause:
                    bp.hit_count += 1
        
        if should_pause:
            return await self._pause(node_id, state, bp_type)
        
        return state
    
    async def _pause(
        self,
        node_id: str,
        state: dict,
        bp_type: BreakpointType,
    ) -> dict:
        """暂停执行"""
        self.session.status = DebugStatus.PAUSED
        self.session.current_node = node_id
        self.session.current_state = state.copy()
        self.session.paused_at = datetime.now()
        self.session._step_mode = False
        self.session._pause_event.clear()
        
        # 记录历史
        self.session.history.append({
            "action": "pause",
            "node": node_id,
            "type": bp_type.value,
            "state_keys": list(state.keys()),
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info(f"调试暂停: node={node_id}, type={bp_type.value}")
        
        # 通知 WebSocket 客户端
        await self._manager._notify("paused", self.session, {
            "node": node_id,
            "type": bp_type.value,
            "state": state,
        })
        
        # 等待用户操作
        await self.session._pause_event.wait()
        
        # 检查动作
        action = self.session._action
        
        if action == DebugAction.STOP:
            self.session.status = DebugStatus.STOPPED
            raise DebugStopException("调试已停止")
        
        if action == DebugAction.STEP:
            self.session._step_mode = True
        
        # 返回可能被修改的状态
        if self.session._modified_state is not None:
            result = self.session._modified_state
            self.session._modified_state = None
            self.session.status = DebugStatus.RUNNING
            return result
        
        self.session.status = DebugStatus.RUNNING
        return state
    
    def resume(self, modified_state: Optional[dict] = None) -> None:
        """
        继续执行
        
        Args:
            modified_state: 修改后的状态（可选，如果不传则使用 set_state 设置的状态）
        """
        self.session._action = DebugAction.CONTINUE
        # 如果传入了 modified_state，使用它；否则保留之前通过 set_state 设置的状态
        if modified_state is not None:
            self.session._modified_state = modified_state
        self.session._pause_event.set()
        
        self.session.history.append({
            "action": "resume",
            "modified": self.session._modified_state is not None,
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info("调试继续执行")
    
    def step(self) -> None:
        """单步执行（执行一个节点后再暂停）"""
        self.session._action = DebugAction.STEP
        self.session._step_mode = True
        self.session._pause_event.set()
        
        self.session.history.append({
            "action": "step",
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info("调试单步执行")
    
    def stop(self) -> None:
        """停止执行"""
        self.session._action = DebugAction.STOP
        self.session._pause_event.set()
        
        self.session.history.append({
            "action": "stop",
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info("调试停止")
    
    def get_state(self) -> Optional[dict]:
        """获取当前状态"""
        return self.session.current_state
    
    def set_state(self, state: dict) -> None:
        """设置状态（在暂停时修改）"""
        if self.session.status == DebugStatus.PAUSED:
            self.session._modified_state = state
            logger.info(f"修改状态: keys={list(state.keys())}")
    
    def get_status(self) -> dict:
        """获取调试状态"""
        return {
            "session_id": self.session.id,
            "workflow_id": self.session.workflow_id,
            "status": self.session.status.value,
            "current_node": self.session.current_node,
            "breakpoints": self.list_breakpoints(),
            "history_count": len(self.session.history),
            "node_executions_count": len(self.session.node_executions),
            "created_at": self.session.created_at.isoformat(),
            "paused_at": self.session.paused_at.isoformat() if self.session.paused_at else None,
        }
    
    def record_node_start(self, node_id: str, node_type: str, state: dict) -> None:
        """
        记录节点开始执行
        
        Args:
            node_id: 节点名称
            node_type: 节点类型
            state: 执行前状态
        """
        execution = NodeExecution(
            node_id=node_id,
            node_type=node_type,
            started_at=datetime.now(),
            state_before=state.copy(),
            status="running",
        )
        self.session.node_executions.append(execution)
        logger.debug(f"记录节点开始: {node_id}")
    
    def record_node_complete(self, node_id: str, state: dict, error: Optional[str] = None) -> None:
        """
        记录节点执行完成
        
        Args:
            node_id: 节点名称
            state: 执行后状态
            error: 错误信息（如果有）
        """
        # 找到最近一个该节点的执行记录
        for execution in reversed(self.session.node_executions):
            if execution.node_id == node_id and execution.status == "running":
                execution.finished_at = datetime.now()
                execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)
                execution.state_after = state.copy()
                execution.status = "error" if error else "completed"
                execution.error = error
                logger.debug(f"记录节点完成: {node_id}, 耗时: {execution.duration_ms}ms")
                break
    
    def get_node_executions(self) -> List[dict]:
        """获取节点执行历史（用于 API 返回）"""
        return [
            {
                "node_id": e.node_id,
                "node_type": e.node_type,
                "started_at": e.started_at.isoformat(),
                "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                "duration_ms": e.duration_ms,
                "state_before": e.state_before,
                "state_after": e.state_after,
                "status": e.status,
                "error": e.error,
            }
            for e in self.session.node_executions
        ]


class DebugStopException(Exception):
    """调试停止异常"""
    pass
