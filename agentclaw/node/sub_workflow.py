"""
SubWorkflowNode - 声明式子工作流节点

支持在 JSON 配置或 UI 上直接调用子工作流，无需编写 Python 代码。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING

from agentclaw.node.base import BaseNode
from agentclaw.exceptions import NodeExecutionError
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


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
    input_map: Optional[Dict[str, str]] = None  # {子工作流 input_key: 父 state_key}
    output_map: Optional[Dict[str, str]] = None # {子工作流 output_key: 父 state_key}
    
    # === 上下文控制 ===
    pass_context: bool = True                   # 是否传递 context（thread_id, user_id 等）
    inherit_thread_id: bool = True              # 是否继承父工作流的 thread_id
    isolated_state: bool = True                 # 是否隔离 state（子工作流不直接修改父 state）
    
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
    
    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        """执行子工作流"""
        # 1. 获取子工作流
        sub_workflow = self._resolve_workflow(context)
        if sub_workflow is None:
            raise NodeExecutionError(
                self.name, 
                f"子工作流未找到: {self.workflow_id or 'workflow object is None'}"
            )
        
        # 2. 构建子工作流输入
        sub_input = self._build_sub_input(state)
        
        # 3. 准备子工作流上下文
        sub_thread_id = None
        sub_user_id = None
        
        if self.pass_context and context:
            if self.inherit_thread_id:
                sub_thread_id = context.thread_id
            sub_user_id = context.user_id
        
        logger.info(
            f"节点 {self.name} 调用子工作流: {sub_workflow.id}, "
            f"input_keys={list(sub_input.keys())}"
        )
        
        # 4. 执行子工作流
        try:
            result = await sub_workflow.run(
                inputs=sub_input,
                thread_id=sub_thread_id,
                user_id=sub_user_id,
                timeout=self.timeout,
            )
            
            # 5. 提取子工作流输出
            sub_state = result.get("state", {})
            
            # 6. 根据 output_map 映射到父 state
            output = self._map_output(sub_state, state)
            
            # 7. 保存子工作流元数据（用于追踪）
            output[f"__{self.name}_metadata__"] = {
                "sub_workflow_id": sub_workflow.id,
                "sub_trace_id": result.get("metadata", {}).get("trace_id"),
                "sub_duration_ms": result.get("metadata", {}).get("duration_ms"),
            }
            
            logger.info(
                f"子工作流 {sub_workflow.id} 执行完成, "
                f"output_keys={list(output.keys())}"
            )
            
            return output
            
        except Exception as e:
            logger.error(f"子工作流 {sub_workflow.id} 执行失败: {e}")
            raise NodeExecutionError(self.name, f"子工作流执行失败: {e}") from e
    
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
        sub_input = {}
        
        for sub_key, parent_key in self.input_map.items():
            # 支持嵌套访问，如 "a.b.c"
            value = self._get_nested_value(state, parent_key)
            if value is not None:
                sub_input[sub_key] = value
            else:
                logger.warning(
                    f"SubWorkflowNode {self.name}: 父 state 中未找到 '{parent_key}'，"
                    f"子工作流输入 '{sub_key}' 将为空"
                )
        
        return sub_input
    
    def _map_output(self, sub_state: dict, parent_state: dict) -> dict:
        """根据 output_map 映射子工作流输出到父 state"""
        # 保留父 state 的所有字段，只更新映射的字段
        output = dict(parent_state)
        
        for sub_key, parent_key in self.output_map.items():
            value = self._get_nested_value(sub_state, sub_key)
            if value is not None:
                output[parent_key] = value
            else:
                logger.warning(
                    f"SubWorkflowNode {self.name}: 子工作流 state 中未找到 '{sub_key}'，"
                    f"父 state '{parent_key}' 将不会更新"
                )
        
        # 如果没有配置 output_map，使用默认输出键
        if not self.output_map:
            output_key = self.get_output_key()
            output[output_key] = sub_state
        
        return output
    
    @staticmethod
    def _get_nested_value(data: dict, key: str) -> Any:
        """获取嵌套字段值，支持 a.b.c 格式"""
        parts = key.split(".")
        value = data
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value
