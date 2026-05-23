"""
CustomNode - 自定义节点

两种方式：

1. 函数式:
    @node("calc")
    def calculate(a, b):  # 参数名自动从 state 取值
        return {"sum": a + b, "product": a * b}

2. 类式:
    class MyNode(CustomNode):
        def __init__(self, id, offset=0, **kwargs):
            super().__init__(id, **kwargs)
            self.offset = offset
        
        def process(self, a, b):  # 参数名自动从 state 取值
            return {"sum": a + b + self.offset}

规则：
- 输入: 函数参数名自动匹配 state 中的键
- 输出: 返回字典，直接合并到 state
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING
import asyncio
import inspect

from agentclaw.node.types import ErrorStrategy
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


def _get_args_from_state(func: Callable, state: dict) -> dict:
    """根据函数参数名从 state 中提取参数"""
    sig = inspect.signature(func)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            # **kwargs 参数：将所有 state 键值传入
            kwargs.update(state)
            continue
        if name in state:
            kwargs[name] = state[name]
        elif param.default is not inspect.Parameter.empty:
            kwargs[name] = param.default
        else:
            kwargs[name] = None
    return kwargs


# ============================================================================
# 函数式节点装饰器
# ============================================================================

def node(id: str, *, output_to_user: bool = True) -> Callable:
    """
    函数式节点装饰器
    
    Args:
        id: 节点 ID
        output_to_user: 是否对外输出
    
    Example:
        @node("upper")
        def to_upper(text):
            return {"upper_text": text.upper()}
        
        @node("calc")
        def calculate(a, b):
            return {"sum": a + b, "product": a * b}
        
        @node("fetch")
        async def fetch_data(url):
            data = await http_get(url)
            return {"data": data}
    """
    def decorator(func: Callable) -> "_FuncNode":
        return _FuncNode(id=id, func=func, output_to_user=output_to_user)
    return decorator


class _FuncNode:
    """函数节点包装器"""
    
    def __init__(self, id: str, func: Callable, output_to_user: bool = True):
        self.id = id
        self._func = func
        self.output_to_user = output_to_user
        self.output_key = None
        self.condition = None
        self.interrupt = False
        self.on_error = ErrorStrategy.ABORT
        self.max_retries = 3
        self.retry_delay = 1.0
        self.fallback_value = None
    
    def get_output_key(self) -> str:
        return self.output_key or self.id
    
    async def execute(self, state: dict, context: "WorkflowContext") -> dict:
        context.current_node = self.id
        context.check_cancelled()
        logger.info(f"执行节点: {self.id}")
        
        # 根据函数参数名从 state 取值
        kwargs = _get_args_from_state(self._func, state)
        
        if asyncio.iscoroutinefunction(self._func):
            result = await self._func(**kwargs)
        else:
            result = self._func(**kwargs)
        
        if result and isinstance(result, dict):
            state.update(result)
        
        return state


# ============================================================================
# 类式自定义节点
# ============================================================================

class CustomNode(ABC):
    """
    自定义节点基类
    
    Example:
        class CalcNode(CustomNode):
            def process(self, a, b):
                return {"sum": a + b, "product": a * b}
        
        class PrefixNode(CustomNode):
            def __init__(self, id, prefix=">>", **kwargs):
                super().__init__(id, **kwargs)
                self.prefix = prefix
            
            def process(self, text):
                return {"result": self.prefix + text}
    """
    
    def __init__(
        self,
        id: str,
        output_key: Optional[str] = None,
        output_to_user: bool = True,
        description: Optional[str] = None,
        condition: Optional[Callable[[dict], bool]] = None,
        interrupt: bool = False,
        on_error: ErrorStrategy = ErrorStrategy.ABORT,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        fallback_value: Optional[Any] = None,
    ):
        self.id = id
        self.output_key = output_key
        self.output_to_user = output_to_user
        self.description = description
        self.condition = condition
        self.interrupt = interrupt
        self.on_error = on_error
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.fallback_value = fallback_value
    
    def get_output_key(self) -> str:
        return self.output_key or self.id
    
    @abstractmethod
    def process(self, **kwargs) -> Dict[str, Any]:
        """
        处理逻辑 - 子类实现

        参数名自动从 state 中取值，返回字典合并到 state。
        """
        pass

    async def async_execute(self, state: dict, context: "WorkflowContext") -> Dict[str, Any]:
        """
        高级执行入口 - 需要访问 context 的子类可覆写此方法。

        返回字典合并到 state。若覆写此方法，process() 不会被调用。
        """
        raise NotImplementedError
    
    async def execute(self, state: dict, context: "WorkflowContext") -> dict:
        from agentclaw.exceptions import NodeExecutionError
        
        context.current_node = self.id
        context.check_cancelled()
        logger.info(f"执行节点: {self.id}")
        
        if self.condition and not self.condition(state):
            logger.info(f"节点 {self.id} 条件不满足，跳过")
            return state
        
        # 优先使用 async_execute（需要 context 的子类实现此方法）
        _use_async_execute = (
            hasattr(self, 'async_execute')
            and callable(getattr(self, 'async_execute'))
            and type(self).async_execute is not CustomNode.async_execute  # 确认子类覆写了
        )

        last_error = None
        for attempt in range(self.max_retries):
            try:
                if _use_async_execute:
                    result = await self.async_execute(state, context)
                else:
                    # 根据 process 参数名从 state 取值
                    kwargs = _get_args_from_state(self.process, state)
                    if asyncio.iscoroutinefunction(self.process):
                        result = await self.process(**kwargs)
                    else:
                        result = await asyncio.to_thread(self.process, **kwargs)
                
                if result and isinstance(result, dict):
                    state.update(result)
                
                return state
                
            except Exception as e:
                from langgraph.errors import GraphInterrupt
                if isinstance(e, GraphInterrupt):
                    raise
                
                last_error = e
                logger.warning(f"节点 {self.id} 第 {attempt + 1} 次执行失败: {e}")
                
                if self.on_error == ErrorStrategy.ABORT:
                    raise NodeExecutionError(self.id, str(e), e)
                elif self.on_error == ErrorStrategy.SKIP:
                    return state
                elif self.on_error == ErrorStrategy.FALLBACK:
                    if self.output_key and self.fallback_value is not None:
                        state[self.output_key] = self.fallback_value
                    return state
                elif self.on_error == ErrorStrategy.RETRY:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
        
        raise NodeExecutionError(self.id, f"重试 {self.max_retries} 次后仍失败", last_error)


SyncNode = CustomNode

__all__ = ["node", "CustomNode", "SyncNode"]
