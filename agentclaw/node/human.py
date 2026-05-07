"""
HumanNode - 人工审批节点
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional, TYPE_CHECKING

from agentclaw.node.base import BaseNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


@dataclass
class HumanNode(BaseNode):
    """
    人工审批节点

    等待人工操作后继续执行。工作流会在此节点中断，
    等待外部调用 resume 接口传入反馈后继续。

    Example:
        # 普通文本输入模式
        HumanNode(id="review", feedback_field="feedback")

        # 审批模式（前端显示 approve/reject 按钮）
        HumanNode(id="review", feedback_field="feedback", approval_mode=True)

    使用流程：
    1. 工作流执行到 HumanNode 时中断
    2. 返回当前状态，状态中包含 status="pending"
    3. 外部系统调用 workflow.resume(thread_id, {feedback_field: value})
    4. 工作流继续执行后续节点

    审批模式:
    - 前端显示 approve/reject 按钮
    - approve: state["__approved__"] = True, state[feedback_field] = 用户文本
    - reject: state["__approved__"] = False, state[feedback_field] = 用户文本
    """

    # 默认中断
    interrupt: bool = True

    # === 反馈配置 ===
    feedback_field: str = "feedback"        # 人工反馈写入的字段名
    pending_status: str = "pending"         # 待处理状态值

    # === 审批模式 ===
    approval_mode: bool = False             # 是否为审批模式（前端显示 approve/reject 按钮）

    # === 超时配置 ===
    timeout_seconds: Optional[int] = None
    on_timeout: Literal["approve", "reject", "error"] = "error"

    # === 上下文配置 ===
    save_to_context: bool = True            # 是否将用户输入保存到 __messages__

    async def _do_execute(self, state: dict, context: WorkflowContext) -> dict:
        """
        等待用户输入节点：触发中断，恢复后将用户输入写入 state

        两种模式：
        1. LangGraph 模式：始终调用 interrupt()，让 LangGraph 处理 resume
        2. 内置引擎模式：检查 feedback_field 是否已存在
        """
        logger.info(f"节点 {self.id} 等待人工反馈，字段: {self.feedback_field}")

        # 尝试使用 LangGraph 的 interrupt 机制
        try:
            from langgraph.types import interrupt

            interrupt_payload = {
                "node": self.id,
                "waiting_for": self.feedback_field,
                "__messages__": state.get("__messages__") or [],
                "status": "waiting_for_input",
            }
            if self.approval_mode:
                interrupt_payload["approval_mode"] = True

            user_input = interrupt(interrupt_payload)

            # 恢复后执行到这里，将用户输入写入 state
            if user_input:
                self._process_resume_input(state, user_input)

        except Exception as e:
            # 如果不在 LangGraph 上下文中，使用内置引擎的中断机制
            if "get_config" in str(e) or "runnable context" in str(e):
                logger.info(f"节点 {self.id} 使用内置引擎中断机制")

                # 内置引擎模式：检查是否已经有用户输入（恢复模式）
                if self.feedback_field in state and state[self.feedback_field]:
                    user_input = state[self.feedback_field]
                    self._process_resume_input(state, user_input)
                    return state

                # 标记为等待输入，由工作流引擎处理中断
                return state

            # 其他异常
            if "GraphInterrupt" not in str(type(e)):
                state["status"] = "error"
                state["__error__"] = str(e)
                logger.error(f"节点 {self.id} 执行失败: {e}")
            else:
                # GraphInterrupt 需要重新抛出，让 LangGraph 处理
                raise

        return state

    def _process_resume_input(self, state: dict, user_input) -> None:
        """处理恢复输入，支持普通文本和结构化审批数据"""
        # 结构化输入: {"__action__": "approve"/"reject", "text": "..."}
        if isinstance(user_input, dict) and "__action__" in user_input:
            action = user_input["__action__"]
            text = user_input.get("text", "")
            state["__approved__"] = (action == "approve")
            state[self.feedback_field] = text
            logger.info(f"节点 {self.id} 收到审批操作: {action}, 反馈: {str(text)[:50]}...")
        else:
            # 普通文本输入
            state[self.feedback_field] = user_input
            # 非审批模式下不设置 __approved__；审批模式下默认 approve
            if self.approval_mode:
                state["__approved__"] = True
            logger.info(f"节点 {self.id} 收到用户输入: {str(user_input)[:50]}...")

        state["status"] = "completed"

        # 将用户文本添加到对话历史
        text_for_context = state.get(self.feedback_field, "")
        if self.save_to_context and text_for_context:
            self._add_to_messages(state, text_for_context)

    def _add_to_messages(self, state: dict, user_input: str) -> None:
        """将用户输入添加到对话历史 __messages__"""
        if not user_input:
            return

        # 确保 user_input 是字符串
        if not isinstance(user_input, str):
            user_input = str(user_input)

        messages = state.get("__messages__") or []

        # 检查是否已经存在相同的用户消息（避免重复）
        for msg in messages[-3:]:  # 只检查最近3条
            if msg.get("role") == "user" and msg.get("content") == user_input:
                return

        # 添加用户消息
        messages.append({"role": "user", "content": user_input})
        state["__messages__"] = messages
        logger.debug(f"节点 {self.id} 将用户输入添加到对话历史")
