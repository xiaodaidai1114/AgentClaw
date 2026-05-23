"""
HumanNode - 人工审批节点
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, TYPE_CHECKING

from agentclaw.node.base import BaseNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


@dataclass(frozen=True)
class HumanInput:
    """HumanNode 输入模式定义。"""

    type: Literal["text", "button"]
    label: Optional[str] = None
    value: Any = None
    confirm: bool = False
    placeholder: Optional[str] = None

    @classmethod
    def text(cls, placeholder: Optional[str] = None) -> "HumanInput":
        return cls(type="text", placeholder=placeholder)

    @classmethod
    def button(cls, label: str, value: Any = None, confirm: bool = False) -> "HumanInput":
        return cls(
            type="button",
            label=label,
            value=label if value is None else value,
            confirm=confirm,
        )


InputModes = list[HumanInput | dict]
InputModesProvider = Callable[[dict], InputModes]


def normalize_input_modes(input_modes: Optional[InputModes] = None, *, approval_mode: bool = False) -> list[dict]:
    """规范化 HumanNode 输入模式，供前端渲染。"""
    if input_modes is None:
        if approval_mode:
            input_modes = [
                HumanInput.text(),
                HumanInput.button("通过", value="approve"),
                HumanInput.button("驳回", value="reject"),
            ]
        else:
            input_modes = [HumanInput.text()]

    normalized = []
    for mode in input_modes:
        if isinstance(mode, HumanInput):
            if mode.type == "text":
                normalized.append({
                    "type": "text",
                    "placeholder": mode.placeholder,
                })
            elif mode.type == "button":
                normalized.append({
                    "type": "button",
                    "label": mode.label or "",
                    "value": mode.value,
                    "confirm": bool(mode.confirm),
                })
        elif isinstance(mode, dict):
            mode_type = mode.get("type", "button")
            if mode_type == "text":
                normalized.append({
                    "type": "text",
                    "placeholder": mode.get("placeholder"),
                })
            elif mode_type == "button":
                label = mode.get("label", "")
                normalized.append({
                    "type": "button",
                    "label": label,
                    "value": label if mode.get("value") is None else mode.get("value"),
                    "confirm": bool(mode.get("confirm", False)),
                })
    return normalized


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
    input_modes: Optional[InputModes | InputModesProvider] = None  # 输入模式：文本框、按钮或二者组合

    # === 超时配置 ===
    timeout_seconds: Optional[int] = None
    on_timeout: Literal["approve", "reject", "error"] = "error"

    # === 上下文配置 ===
    save_to_context: bool = True            # 是否将用户输入保存到 __messages__

    def resolve_input_modes(self, state: dict) -> Optional[InputModes]:
        if callable(self.input_modes):
            return self.input_modes(state)
        return self.input_modes

    def build_interrupt_payload(self, state: dict) -> dict:
        payload = {
            "node": self.id,
            "waiting_for": self.feedback_field,
            "__messages__": state.get("__messages__") or [],
            "status": "waiting_for_input",
            "input_modes": normalize_input_modes(
                self.resolve_input_modes(state),
                approval_mode=self.approval_mode,
            ),
        }
        if self.approval_mode:
            payload["approval_mode"] = True
        return payload

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

            interrupt_payload = self.build_interrupt_payload(state)

            user_input = interrupt(interrupt_payload)

            # 恢复后执行到这里，将用户输入写入 state
            if user_input is not None:
                self._process_resume_input(state, user_input)

        except Exception as e:
            # 如果不在 LangGraph 上下文中，使用内置引擎的中断机制
            if "get_config" in str(e) or "runnable context" in str(e):
                logger.info(f"节点 {self.id} 使用内置引擎中断机制")

                # 内置引擎模式：检查是否已经有用户输入（恢复模式）
                if self.feedback_field in state:
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
        if isinstance(user_input, dict) and "__human_input__" in user_input:
            human_input = user_input["__human_input__"]
            if isinstance(human_input, dict):
                value = human_input.get("value")
                state[self.feedback_field] = value
                state["__human_input__"] = human_input
                logger.info(f"节点 {self.id} 收到按钮输入: {str(value)[:50]}...")
            else:
                state[self.feedback_field] = human_input
                logger.info(f"节点 {self.id} 收到结构化人工输入: {str(human_input)[:50]}...")
        # 结构化输入: {"__action__": "approve"/"reject", "text": "..."}
        elif isinstance(user_input, dict) and "__action__" in user_input:
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
