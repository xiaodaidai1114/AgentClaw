"""
WorkflowContext - 工作流执行上下文

在整个工作流执行过程中传递，包含：
- 请求级别信息（thread_id, user_id）
- 组件实例（prompt_manager, llm_manager 等）
- 执行状态（cancel_token, request_stream）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Callable, Awaitable
from datetime import datetime
import uuid

from agentclaw.exceptions import WorkflowCancelledError, WorkflowTimeoutError

if TYPE_CHECKING:
    from agentclaw.prompt.manager import PromptManager
    from agentclaw.model.manager import LLMManager
    from agentclaw.node.toolkit import ToolKit
    from agentclaw.skills.manager import SkillManager

# 流式回调类型：async def callback(node_id: str, chunk: str) -> None
StreamCallback = Callable[[str, str], Awaitable[None]]


@dataclass
class CancelToken:
    """取消令牌，用于支持工作流取消"""
    
    _cancelled: bool = False
    _cancel_reason: Optional[str] = None
    
    def cancel(self, reason: str = "用户取消") -> None:
        self._cancelled = True
        self._cancel_reason = reason
    
    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    @property
    def cancel_reason(self) -> Optional[str]:
        return self._cancel_reason


@dataclass
class WorkflowContext:
    """
    工作流执行上下文
    
    在工作流执行过程中自动注入到每个节点，提供：
    - 请求标识（thread_id, user_id）
    - 组件访问（prompt_manager, llm_manager）
    - 执行控制（cancel_token, timeout）
    
    Example:
        @workflow.node(id="处理")
        async def process(state: dict, context: WorkflowContext) -> dict:
            prompt = context.prompt_manager.get_prompt("key", state)
            response = await context.llm_manager.invoke(prompt)
            return state
    """
    
    # 请求标识
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)  # 自定义元数据
    
    # 工作流标识
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    
    # 组件实例（运行时注入）
    prompt_manager: Optional[PromptManager] = None
    llm_manager: Optional[LLMManager] = None
    toolkit: Optional[ToolKit] = None
    skill_manager: Optional[SkillManager] = None
    
    # 用户输入字段名（从 workflow 配置）
    user_input_field: Optional[str] = None

    # 请求级模型选择：仅用于未显式指定 model_id 的 LLM 节点
    runtime_model_id: Optional[str] = None
    
    # 工具配置（运行时禁用的 skills/tools）
    disabled_skills: set = field(default_factory=set)
    disabled_tools: set = field(default_factory=set)
    
    # 执行控制
    cancel_token: CancelToken = field(default_factory=CancelToken)
    request_stream: bool = True  # 是否请求流式输出
    timeout: Optional[int] = 300  # 超时时间（秒），None/<=0 表示不限制
    debug_mode: bool = False  # 调试模式（禁用超时检查）
    from_channel: bool = False  # 是否来自渠道调用
    public_mode: bool = False  # 是否来自匿名 Public Agent 入口
    disable_confirm_tool: bool = False  # 禁用 confirm_action 工具（自动批准）
    tool_confirmation_required: bool = False  # 是否由 Harness 在高风险工具执行前强制确认，默认关闭以兼容旧行为
    tool_confirmation_level: str = "off"  # off/high/medium/low：从哪个风险等级开始要求确认
    
    # 流式回调（用于 SSE 推送）
    stream_callback: Optional[StreamCallback] = None
    
    # 执行状态
    start_time: datetime = field(default_factory=datetime.now)
    current_node: Optional[str] = None
    
    # 扩展数据
    extra: dict = field(default_factory=dict)
    
    def copy(self) -> WorkflowContext:
        """创建上下文副本（用于子工作流）"""
        return WorkflowContext(
            thread_id=self.thread_id,
            user_id=self.user_id,
            metadata=self.metadata.copy(),
            workflow_id=self.workflow_id,
            workflow_name=self.workflow_name,
            prompt_manager=self.prompt_manager,
            llm_manager=self.llm_manager,
            toolkit=self.toolkit,
            skill_manager=self.skill_manager,
            user_input_field=self.user_input_field,
            runtime_model_id=self.runtime_model_id,
            disabled_skills=self.disabled_skills.copy(),
            disabled_tools=self.disabled_tools.copy(),
            cancel_token=self.cancel_token,  # 共享取消令牌
            request_stream=self.request_stream,
            timeout=self.timeout,
            debug_mode=self.debug_mode,  # 共享调试模式
            from_channel=self.from_channel,
            public_mode=self.public_mode,
            disable_confirm_tool=self.disable_confirm_tool,
            tool_confirmation_required=self.tool_confirmation_required,
            tool_confirmation_level=self.tool_confirmation_level,
            stream_callback=self.stream_callback,  # 共享回调
            start_time=self.start_time,
            extra=self.extra.copy(),
        )
    
    def with_workflow(self, workflow_id: str, workflow_name: str) -> WorkflowContext:
        """为子工作流创建新上下文"""
        ctx = self.copy()
        ctx.workflow_id = workflow_id
        ctx.workflow_name = workflow_name
        return ctx
    
    def elapsed_seconds(self) -> float:
        """获取已执行时间（秒）"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def is_timeout(self) -> bool:
        """检查是否超时（调试模式下禁用超时检查）"""
        if self.debug_mode:
            return False
        if self.timeout is None or self.timeout <= 0:
            return False
        return self.elapsed_seconds() > self.timeout
    
    def check_cancelled(self) -> None:
        """检查是否被取消，如果是则抛出异常"""
        if self.cancel_token.is_cancelled:
            raise WorkflowCancelledError(self.cancel_token.cancel_reason)
        if self.is_timeout():
            raise WorkflowTimeoutError(f"工作流执行超时 ({self.timeout}s)")
