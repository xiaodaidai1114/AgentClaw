"""
BaseComponent - 组件基类

所有可插拔组件的基类，定义标准生命周期钩子
"""

from __future__ import annotations
from abc import ABC
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    # 延迟导入以避免循环依赖
    from agentclaw.graph.workflow import Workflow


class BaseComponent(ABC):
    """
    组件基类
    
    所有可插拔组件都应继承此类，实现标准生命周期钩子：
    - on_init: 组件注册时调用
    - on_workflow_start: 工作流开始时调用
    - on_node_start: 节点开始时调用
    - on_node_end: 节点结束时调用
    - on_workflow_end: 工作流结束时调用
    - on_error: 发生错误时调用
    """
    
    def on_init(self, workflow: Workflow) -> None:
        """组件注册时调用"""
        pass
    
    def on_workflow_start(
        self, 
        workflow_id: str, 
        thread_id: str,
        initial_state: dict,
    ) -> None:
        """工作流开始执行时调用"""
        pass
    
    def on_node_start(
        self,
        node_id: str,
        state: dict,
    ) -> None:
        """节点开始执行时调用"""
        pass
    
    def on_node_end(
        self,
        node_id: str,
        state: dict,
        duration_ms: Optional[float] = None,
    ) -> None:
        """节点执行完成时调用"""
        pass
    
    def on_workflow_end(
        self,
        workflow_id: str,
        thread_id: str,
        final_state: dict,
        duration_ms: Optional[float] = None,
    ) -> None:
        """工作流执行完成时调用"""
        pass
    
    def on_error(
        self,
        node_id: Optional[str],
        error: Exception,
        state: dict,
    ) -> None:
        """发生错误时调用"""
        pass
    
    def on_stream_chunk(
        self,
        node_id: str,
        chunk: str,
    ) -> None:
        """流式输出时每个 chunk 调用"""
        pass
