"""
SubWorkflowNode - 声明式子工作流节点

支持在 JSON 配置或 UI 上直接调用子工作流，无需编写 Python 代码。
"""

from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, TYPE_CHECKING
import uuid

from agentclaw.graph.state_path import get_path, merge_path, set_path
from agentclaw.node.base import BaseNode
from agentclaw.exceptions import NodeExecutionError
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)
_MISSING = object()


@dataclass
class SubWorkflowNode(BaseNode):
    """
    声明式子工作流节点
    
    支持通过声明式配置调用子工作流，无需编写 Python 代码。
    
    Example:
        # 方式1：直接传入工作流对象
        workflow.add_node(SubWorkflowNode(
            name="call_sub",
            workflow=sub_workflow,
            input_map={
                "query": "user_input",      # 子工作流的 query <- 父 state 的 user_input
                "history": "chat_history"   # 子工作流的 history <- 父 state 的 chat_history
            },
            output_map={
                "final_answer": "sub_result"  # 父 state 的 sub_result <- 子工作流的 final_answer
            }
        ))
        
        # 方式2：通过 workflow_id 引用（用于 JSON 配置）
        workflow.add_node(SubWorkflowNode(
            name="call_sub",
            workflow_id="sub_workflow_001",
            input_map={"query": "user_input"},
            output_map={"result": "sub_result"}
        ))
    
    JSON 配置格式:
        {
            "type": "sub_workflow",
            "name": "call_sub",
            "workflow_id": "sub_workflow_001",
            "input_map": {"query": "user_input"},
            "output_map": {"result": "sub_result"}
        }
    """
    
    # === 子工作流配置 ===
    workflow: Optional["Workflow"] = None       # 子工作流对象
    workflow_id: Optional[str] = None           # 子工作流 ID（用于 JSON 配置）
    
    # === 声明式映射 ===
    input_map: Optional[Dict[str, str]] = None  # {子工作流 input_path: 父 state_path}
    output_map: Optional[Dict[str, str]] = None # {子工作流 output_path: 父 state_path}
    readonly_input_map: Optional[Dict[str, str]] = None  # 只传入子工作流，不回写
    state_map: Optional[Dict[str, str]] = None  # {子工作流 state_path: 父 state_path}，执行前后双向映射
    merge_strategy: Optional[Dict[str, str]] = None  # {子 state_path 或父 state_path: replace/deep_merge/...}
    instance_id: str = ""                       # 同一子工作流定义的实例 ID，如 p1/p2
    
    # === 上下文控制 ===
    pass_context: bool = True                   # 是否传递 context（thread_id, user_id 等）
    inherit_thread_id: bool = True              # 是否继承父工作流的 thread_id
    thread_id_strategy: Optional[str] = None     # inherit/derived/new/custom；None 时兼容 inherit_thread_id
    thread_id_template: str = ""                 # custom 策略模板
    isolated_state: bool = True                 # 是否隔离 state（子工作流不直接修改父 state）
    stream_child_events: bool = True            # 是否把子工作流内部节点事件透传到父输出通道
    stream_child_node_events: bool = True        # 是否透传子工作流内部节点开始/结束事件
    
    # === 超时配置 ===
    timeout: Optional[int] = None               # 子工作流超时时间（秒），None 表示使用子工作流默认值
    
    def __post_init__(self):
        """初始化后验证"""
        if self.workflow is None and self.workflow_id is None:
            raise ValueError("必须指定 workflow 或 workflow_id")
        
        # 默认映射
        if self.input_map is None:
            self.input_map = {}
        if self.output_map is None:
            self.output_map = {}
        if self.readonly_input_map is None:
            self.readonly_input_map = {}
        if self.state_map is None:
            self.state_map = {}
        if self.merge_strategy is None:
            self.merge_strategy = {}
    
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """执行子工作流"""
        # 1. 获取子工作流
        sub_workflow = self._resolve_workflow(context)
        if sub_workflow is None:
            raise NodeExecutionError(
                self.id,
                f"子工作流未找到: {self.workflow_id or 'workflow object is None'}"
            )
        
        # 2. 构建子工作流输入
        sub_input = self._build_sub_input(state)
        
        # 3. 准备子工作流上下文
        sub_context = None
        sub_thread_id = None
        sub_user_id = None
        
        if self.pass_context and context:
            sub_thread_id = self._resolve_thread_id(context, sub_workflow)
            sub_user_id = context.user_id
            sub_context = context.with_workflow(sub_workflow.id, sub_workflow.name)
            if sub_thread_id:
                sub_context.thread_id = sub_thread_id
        
        logger.info(
            f"节点 {self.id} 调用子工作流: {sub_workflow.id}, "
            f"instance_id={self.instance_id or self.id}, "
            f"input_keys={list(sub_input.keys())}"
        )
        
        # 4. 执行子工作流
        try:
            self._register_sub_state_fields(sub_workflow, sub_input)
            async with self._maybe_suppress_child_node_events():
                result = await sub_workflow.run(
                    inputs=sub_input,
                    context=sub_context,
                    thread_id=sub_thread_id,
                    user_id=sub_user_id,
                    timeout=self.timeout,
                )
            
            return await self._process_subworkflow_result(
                result=result,
                sub_workflow=sub_workflow,
                parent_state=state,
                sub_context=sub_context,
                sub_thread_id=sub_thread_id,
                sub_user_id=sub_user_id,
            )
            
        except Exception as e:
            from langgraph.errors import GraphInterrupt

            if isinstance(e, GraphInterrupt):
                raise
            logger.error(f"子工作流 {sub_workflow.id} 执行失败: {e}")
            raise NodeExecutionError(self.id, f"子工作流执行失败: {e}") from e

    @asynccontextmanager
    async def _maybe_suppress_child_node_events(self):
        if self.stream_child_events and self.stream_child_node_events:
            yield
            return

        from agentclaw.runtime.streaming.context import _suppress_node_events_var, get_output_channel

        channel = get_output_channel()
        if channel is None:
            yield
            return

        token = _suppress_node_events_var.set(_suppress_node_events_var.get() + 1)
        try:
            yield
        finally:
            _suppress_node_events_var.reset(token)
    
    def _resolve_workflow(self, context: "WorkflowContext") -> Optional["Workflow"]:
        """解析子工作流对象"""
        # 优先使用直接传入的 workflow 对象
        if self.workflow is not None:
            return self.workflow
        
        # 通过 workflow_id 从注册表获取
        if self.workflow_id:
            try:
                from agentclaw.api.registry import WorkflowRegistry
                return WorkflowRegistry.get(self.workflow_id)
            except ImportError:
                logger.warning("WorkflowRegistry 不可用，无法通过 workflow_id 解析子工作流")
                return None
        
        return None
    
    def _build_sub_input(self, state: dict) -> dict:
        """根据 input_map 构建子工作流输入"""
        sub_input = {} if self.isolated_state else deepcopy(state)

        self._apply_input_mapping(sub_input, state, self.readonly_input_map, "readonly_input_map")
        self._apply_input_mapping(sub_input, state, self.state_map, "state_map")
        self._apply_input_mapping(sub_input, state, self.input_map, "input_map")

        return sub_input

    def _map_output(self, sub_state: dict, parent_state: dict) -> dict:
        """根据 output_map 映射子工作流输出到父 state"""
        output = parent_state

        for sub_path, parent_path in self.state_map.items():
            value = get_path(sub_state, sub_path, _MISSING)
            if value is _MISSING:
                logger.warning(
                    f"SubWorkflowNode {self.id}: 子工作流 state 中未找到 '{sub_path}'，"
                    f"父 state '{parent_path}' 将不会更新"
                )
                continue
            strategy = self._resolve_merge_strategy(sub_path, parent_path)
            merge_path(output, parent_path, deepcopy(value), strategy=strategy)
        
        for sub_path, parent_path in self.output_map.items():
            value = get_path(sub_state, sub_path, _MISSING)
            if value is _MISSING:
                logger.warning(
                    f"SubWorkflowNode {self.id}: 子工作流 state 中未找到 '{sub_path}'，"
                    f"父 state '{parent_path}' 将不会更新"
                )
                continue
            set_path(output, parent_path, deepcopy(value))
        
        # 如果没有配置 output_map，使用默认输出键
        if not self.output_map:
            output_key = self.get_output_key()
            output[output_key] = sub_state
        
        return output

    async def _process_subworkflow_result(
        self,
        *,
        result: dict,
        sub_workflow: "Workflow",
        parent_state: dict,
        sub_context: Optional["WorkflowContext"],
        sub_thread_id: Optional[str],
        sub_user_id: Optional[str],
    ) -> dict:
        """Map a completed child result or bridge a child interrupt to parent."""
        sub_state = result.get("state", {})

        if sub_state.get("__interrupted__"):
            result = await self._interrupt_parent_and_resume_child(
                sub_workflow=sub_workflow,
                sub_state=sub_state,
                parent_state=parent_state,
                sub_context=sub_context,
                sub_thread_id=sub_thread_id,
                sub_user_id=sub_user_id,
            )
            if result.get("metadata", {}).get("parent_interrupted"):
                return result.get("state", parent_state)
            sub_state = result.get("state", {})
            if sub_state.get("__interrupted__"):
                return await self._process_subworkflow_result(
                    result=result,
                    sub_workflow=sub_workflow,
                    parent_state=parent_state,
                    sub_context=sub_context,
                    sub_thread_id=sub_thread_id,
                    sub_user_id=sub_user_id,
                )

        output = self._map_output(sub_state, parent_state)
        self._clear_interrupt_fields(output)
        output[f"__{self.id}_metadata__"] = {
            "sub_workflow_id": sub_workflow.id,
            "instance_id": self.instance_id or self.id,
            "thread_id": sub_thread_id,
            "sub_trace_id": result.get("metadata", {}).get("trace_id"),
            "sub_duration_ms": result.get("metadata", {}).get("duration_ms"),
        }

        logger.info(
            f"子工作流 {sub_workflow.id} 执行完成, "
            f"output_keys={list(output.keys())}"
        )
        return output

    async def _interrupt_parent_and_resume_child(
        self,
        *,
        sub_workflow: "Workflow",
        sub_state: dict,
        parent_state: dict,
        sub_context: Optional["WorkflowContext"],
        sub_thread_id: Optional[str],
        sub_user_id: Optional[str],
    ) -> dict:
        interrupt_payload = self._build_parent_interrupt_payload(
            sub_workflow=sub_workflow,
            sub_state=sub_state,
            sub_thread_id=sub_thread_id,
        )

        try:
            from langgraph.types import interrupt

            parent_resume_value = interrupt(interrupt_payload)
        except Exception as e:
            if "get_config" in str(e) or "runnable context" in str(e):
                parent_state["__interrupted__"] = True
                parent_state["__status__"] = "waiting_for_input"
                parent_state["__interrupt_info__"] = interrupt_payload
                parent_state["__subworkflow_interrupt__"] = interrupt_payload["subworkflow"]
                return {"state": parent_state, "metadata": {"parent_interrupted": True}}
            raise

        resume_inputs = self._build_child_resume_inputs(sub_workflow, parent_resume_value)
        return await sub_workflow.run(
            inputs=resume_inputs,
            context=sub_context,
            thread_id=sub_thread_id,
            user_id=sub_user_id,
            timeout=self.timeout,
        )

    def _build_parent_interrupt_payload(
        self,
        *,
        sub_workflow: "Workflow",
        sub_state: dict,
        sub_thread_id: Optional[str],
    ) -> dict:
        child_interrupt = dict(sub_state.get("__interrupt_info__") or {})
        input_field = (
            child_interrupt.get("waiting_for")
            or sub_workflow.get_user_input_field()
            or "user_input"
        )
        subworkflow_info = {
            "node_id": self.id,
            "sub_workflow_id": sub_workflow.id,
            "thread_id": sub_thread_id,
            "input_field": input_field,
        }
        payload = {
            **child_interrupt,
            "status": "waiting_for_input",
            "subworkflow": subworkflow_info,
        }
        payload.setdefault("node", child_interrupt.get("node") or self.id)
        payload.setdefault("waiting_for", input_field)
        return payload

    @staticmethod
    def _build_child_resume_inputs(sub_workflow: "Workflow", parent_resume_value: Any) -> dict:
        input_field = sub_workflow.get_user_input_field() or "user_input"
        if isinstance(parent_resume_value, dict) and "__action__" in parent_resume_value:
            return {
                input_field: parent_resume_value.get("text", ""),
                "__human_action__": parent_resume_value.get("__action__"),
            }
        return {input_field: parent_resume_value}

    @staticmethod
    def _clear_interrupt_fields(state: dict) -> None:
        for key in (
            "__interrupted__",
            "__interrupt_info__",
            "__subworkflow_interrupt__",
            "__interrupt_node__",
        ):
            state.pop(key, None)
        if state.get("__status__") == "waiting_for_input":
            state.pop("__status__", None)

    def get_state_output_keys(self) -> list[str]:
        """Return all top-level parent state fields this node may write."""
        keys: list[str] = []
        if not self.output_map:
            keys.append(self.get_output_key())
        for parent_path in list(self.output_map.values()) + list(self.state_map.values()):
            top_level_key = parent_path.split(".", 1)[0]
            if top_level_key and top_level_key not in keys:
                keys.append(top_level_key)
        metadata_key = f"__{self.id}_metadata__"
        if metadata_key not in keys:
            keys.append(metadata_key)
        for key in ("__interrupted__", "__status__", "__interrupt_info__", "__subworkflow_interrupt__"):
            if key not in keys:
                keys.append(key)
        return keys

    def get_state_merge_strategies(self) -> dict[str, str]:
        """Tell Workflow which top-level fields should merge parallel patches."""
        strategies: dict[str, str] = {}
        for parent_path in list(self.output_map.values()) + list(self.state_map.values()):
            if "." not in parent_path:
                continue
            top_level_key = parent_path.split(".", 1)[0]
            strategies[top_level_key] = "deep_merge"
        return strategies

    def _apply_input_mapping(
        self,
        sub_input: dict,
        parent_state: dict,
        mapping: Optional[Dict[str, str]],
        mapping_name: str,
    ) -> None:
        for sub_path, parent_path in (mapping or {}).items():
            value = get_path(parent_state, parent_path, _MISSING)
            if value is _MISSING:
                logger.warning(
                    f"SubWorkflowNode {self.id}: 父 state 中未找到 '{parent_path}'，"
                    f"{mapping_name} 的子工作流输入 '{sub_path}' 将为空"
                )
                continue
            set_path(sub_input, sub_path, deepcopy(value))

    def _resolve_thread_id(self, context: "WorkflowContext", sub_workflow: "Workflow") -> Optional[str]:
        strategy = self.thread_id_strategy
        if not strategy:
            strategy = "inherit" if self.inherit_thread_id else "new"
        strategy = strategy.lower()

        parent_thread_id = context.thread_id if context else None
        instance_id = self.instance_id or self.id

        if strategy == "inherit":
            return parent_thread_id
        if strategy == "derived":
            if parent_thread_id:
                return f"{parent_thread_id}:actor:{instance_id}"
            return f"actor:{instance_id}"
        if strategy == "new":
            return str(uuid.uuid4())
        if strategy == "custom":
            if not self.thread_id_template:
                raise ValueError("thread_id_strategy='custom' requires thread_id_template")
            return self.thread_id_template.format(
                parent_thread_id=parent_thread_id or "",
                instance_id=instance_id,
                node_id=self.id,
                workflow_id=sub_workflow.id,
            )
        raise ValueError(f"unsupported thread_id_strategy: {self.thread_id_strategy}")

    def _resolve_merge_strategy(self, sub_path: str, parent_path: str) -> str:
        return (
            self.merge_strategy.get(sub_path)
            or self.merge_strategy.get(parent_path)
            or "replace"
        )

    def _register_sub_state_fields(self, sub_workflow: "Workflow", sub_input: dict) -> None:
        """Ensure mapped child state paths survive the child workflow LangGraph schema."""
        for key, value in sub_input.items():
            field_type = type(value) if value is not None else str
            sub_workflow.register_state_field(key, field_type)
        for sub_path in (
            list(self.readonly_input_map.keys())
            + list(self.input_map.keys())
            + list(self.state_map.keys())
            + list(self.output_map.keys())
        ):
            top_level_key = sub_path.split(".", 1)[0]
            if top_level_key:
                sub_workflow.register_state_field(top_level_key, str)
