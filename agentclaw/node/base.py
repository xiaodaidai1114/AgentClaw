"""
BaseNode - 节点抽象基类
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING
import asyncio

from agentclaw.node.types import ErrorStrategy
from agentclaw.exceptions import NodeExecutionError
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


@dataclass
class BaseNode(ABC):
    """
    节点抽象基类
    
    所有节点类型的通用配置和行为。
    子类必须实现 _do_execute 方法。
    
    Example:
        class CustomNode(BaseNode):
            async def _do_execute(self, state, context):
                # 自定义逻辑
                return state
    """
    
    # === 必需 ===
    id: str  # 节点唯一标识
    
    # === 输出配置 ===
    output_key: Optional[str] = None        # 输出存储键，默认为 id
    output_to_user: bool = True             # 是否对外输出
    description: Optional[str] = None       # 节点描述（用于前端展示，如"初始化智能体"）
    
    # === 执行控制 ===
    condition: Optional[Callable[[dict], bool]] = None  # 条件执行函数
    interrupt: bool = False                 # 是否中断等待
    
    # === 错误处理 ===
    on_error: ErrorStrategy = ErrorStrategy.ABORT
    max_retries: int = 3
    retry_delay: float = 1.0
    fallback_value: Optional[Any] = None
    
    @abstractmethod
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """
        执行节点核心逻辑 - 子类必须实现
        
        Args:
            state: 工作流状态
            context: 工作流上下文
            
        Returns:
            更新后的状态
        """
        pass
    
    async def execute(self, state: dict, context: "WorkflowContext") -> dict:
        """
        执行节点（包含条件检查和重试逻辑）
        
        Args:
            state: 工作流状态
            context: 工作流上下文
            
        Returns:
            更新后的状态
        """
        context.current_node = self.id
        context.check_cancelled()
        
        logger.info(f"执行节点: {self.id}")
        
        # 条件检查
        if self.condition and not self.condition(state):
            logger.info(f"节点 {self.id} 条件不满足，跳过")
            return state
        
        # 重试循环
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await self._do_execute(state, context)
            except Exception as e:
                # GraphInterrupt 是正常的中断信号，直接透传
                from langgraph.errors import GraphInterrupt
                if isinstance(e, GraphInterrupt):
                    raise
                
                last_error = e
                logger.warning(f"节点 {self.id} 第 {attempt + 1} 次执行失败: {e}")
                
                if self.on_error == ErrorStrategy.ABORT:
                    raise NodeExecutionError(self.id, str(e), e)
                elif self.on_error == ErrorStrategy.SKIP:
                    logger.info(f"节点 {self.id} 跳过")
                    return state
                elif self.on_error == ErrorStrategy.FALLBACK:
                    if self.output_key and self.fallback_value is not None:
                        state[self.output_key] = self.fallback_value
                    logger.info(f"节点 {self.id} 使用降级值")
                    return state
                elif self.on_error == ErrorStrategy.RETRY:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
        
        raise NodeExecutionError(
            self.id, 
            f"重试 {self.max_retries} 次后仍失败", 
            last_error
        )
    
    def get_output_key(self) -> str:
        """获取输出键"""
        return self.output_key or self.id


@dataclass
class FunctionNode(BaseNode):
    """
    函数节点（内部使用）
    
    用于 @workflow.node() 装饰器创建的自定义函数节点。
    推荐用户直接使用装饰器而非手动创建此类。
    """
    
    handler: Optional[Callable] = None
    
    def __post_init__(self):
        if self.handler is None:
            raise ValueError(f"FunctionNode '{self.id}' 必须指定 handler")
    
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """执行处理函数"""
        import inspect
        
        sig = inspect.signature(self.handler)
        has_context = len(sig.parameters) >= 2
        
        if asyncio.iscoroutinefunction(self.handler):
            result = await (self.handler(state, context) if has_context else self.handler(state))
        else:
            call = self.handler
            if has_context:
                result = await asyncio.to_thread(call, state, context)
            else:
                result = await asyncio.to_thread(call, state)
        
        if result is not None and isinstance(result, dict):
            state.update(result)
        
        return state
