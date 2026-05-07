"""
流式输出上下文管理

参考 Dify API 格式，支持：
- blocking 模式：返回完整 JSON
- streaming 模式：SSE 事件流

事件类型（streaming 模式）：
- workflow_started: 工作流开始
- node_started: 节点开始执行
- node_finished: 节点执行完成
- message: LLM 流式输出 token
- message_end: 消息结束（包含 usage）
- workflow_finished: 工作流完成
- error: 错误
"""

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional, Any, AsyncIterator, List, Dict
from datetime import datetime

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def _timestamp() -> int:
    """返回当前时间戳（秒）"""
    return int(time.time())


@dataclass
class OutputChannel:
    """
    输出通道
    
    管理单个请求的输出事件，支持：
    - 流式模式：事件逐个推送（Dify 格式）
    - 非流式模式：收集所有输出，最后汇总
    - 调试模式：同时推送到调试队列
    """
    workflow_id: str = ""
    thread_id: str = ""
    stream_mode: bool = False
    maxsize: int = 100
    state: Optional[dict] = None  # 当前 state 引用，用于 save_to_context
    debug_queue: Optional[asyncio.Queue] = None  # 调试队列（直接引用）
    
    # 运行时 ID
    task_id: str = ""
    workflow_run_id: str = ""
    message_id: str = ""
    
    # 内部状态
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    outputs: List[str] = field(default_factory=list)  # 收集所有输出文本
    done: bool = False
    error: Optional[str] = None
    _current_node: Optional[str] = None
    _node_index: int = 0
    _start_time: float = 0.0
    _pre_run_msg_count: int = 0  # 执行前 __messages__ 的数量
    
    # Usage 统计
    _total_tokens: int = 0
    _prompt_tokens: int = 0
    _completion_tokens: int = 0
    _latency: float = 0.0

    # Tool call 时间追踪
    _tool_start_times: Dict[str, float] = field(default_factory=dict)
    confirmation_requests: List[dict] = field(default_factory=list)

    def __post_init__(self):
        self.queue = asyncio.Queue(maxsize=self.maxsize)
        self.outputs = []
        self._start_time = time.perf_counter()
        self._tool_start_times = {}
        self.confirmation_requests = []
        
        # 生成运行时 ID（如果未提供）
        import uuid
        if not self.task_id:
            self.task_id = str(uuid.uuid4())
        if not self.workflow_run_id:
            self.workflow_run_id = str(uuid.uuid4())
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
    
    async def __aenter__(self):
        """进入上下文"""
        _output_channel_var.set(self)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        if exc_val:
            self.error = str(exc_val)
            await self._push_error(str(exc_val))
        await self.finish()
        _output_channel_var.set(None)
        return False
    
    async def _push(self, event: dict):
        """内部：推送事件"""
        if self.stream_mode:
            await self.queue.put(event)
        
        # 如果有调试队列，直接推送（简化路径）
        if self.debug_queue is not None:
            debug_event = self._convert_to_debug_event(event)
            if debug_event:
                try:
                    self.debug_queue.put_nowait(debug_event)
                except asyncio.QueueFull:
                    pass  # 队列满了就丢弃
    
    def _convert_to_debug_event(self, event: dict) -> Optional[dict]:
        """转换为调试事件格式"""
        event_type = event.get("event", "unknown")
        
        if event_type == "message":
            return {
                "event": "message",
                "data": {
                    "content": event.get("answer", ""),
                    "node": event.get("node_id"),
                }
            }
        elif event_type == "node_started":
            data = event.get("data", {})
            return {
                "event": "node_started",
                "data": {
                    "node": data.get("node_id"),
                    "type": data.get("node_type"),
                }
            }
        elif event_type == "node_finished":
            data = event.get("data", {})
            return {
                "event": "node_finished",
                "data": {
                    "node": data.get("node_id"),
                    "status": data.get("status"),
                    "elapsed_time": data.get("elapsed_time"),
                }
            }
        elif event_type == "tool":
            return {
                "event": "tool",
                "data": {
                    "tool_name": event.get("tool_call", {}).get("function", {}).get("name"),
                    "tool_result": event.get("tool_result"),
                    "status": event.get("status"),
                    "batch_id": event.get("batch_id"),
                }
            }
        elif event_type == "workflow_finished":
            data = event.get("data", {})
            return {
                "event": "status",
                "data": {
                    "status": data.get("status"),
                    "elapsed_time": data.get("elapsed_time"),
                }
            }
        return None
    
    # === Dify 格式事件 ===
    
    async def push_workflow_started(self):
        """推送 workflow_started 事件"""
        await self._push({
            "event": "workflow_started",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "data": {
                "id": self.workflow_run_id,
                "workflow_id": self.workflow_id,
                "conversation_id": self.thread_id,
                "created_at": _timestamp(),
            }
        })
    
    async def push_node_started(
        self,
        node_id: str,
        node_type: str = "llm",
        inputs: Optional[dict] = None,
        parallel_group_id: Optional[str] = None,
        title: Optional[str] = None,
    ):
        """推送 node_started 事件"""
        self._current_node = node_id
        self._node_index += 1
        data = {
            "id": f"{self.workflow_run_id}-{self._node_index}",
            "node_id": node_id,
            "node_type": node_type,
            "title": title or node_id,
            "index": self._node_index,
            "created_at": _timestamp(),
        }
        if inputs is not None:
            data["inputs"] = inputs
        if parallel_group_id is not None:
            data["parallel_group_id"] = parallel_group_id
        await self._push({
            "event": "node_started",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "data": data,
        })
    
    async def push_node_finished(
        self,
        node_id: str,
        status: str = "succeeded",
        outputs: Optional[dict] = None,
        elapsed_time: float = 0.0,
        error: Optional[str] = None,
        parallel_group_id: Optional[str] = None,
    ):
        """推送 node_finished 事件"""
        data = {
            "id": f"{self.workflow_run_id}-{self._node_index}",
            "node_id": node_id,
            "status": status,
            "outputs": outputs or {},
            "elapsed_time": elapsed_time,
            "created_at": _timestamp(),
        }
        if error:
            data["error"] = error
        if parallel_group_id is not None:
            data["parallel_group_id"] = parallel_group_id

        await self._push({
            "event": "node_finished",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "data": data,
        })
        self._current_node = None
    
    async def push_message(self, content: str, node: Optional[str] = None):
        """推送 message 事件（流式 token）"""
        # 收集输出
        self.outputs.append(content)
        
        # 使用传入的 node 或当前节点
        node_id = node or self._current_node
        
        event = {
            "event": "message",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "answer": content,
            "created_at": _timestamp(),
        }
        if node_id:
            event["node_id"] = node_id
        
        await self._push(event)
    
    async def push_reasoning(self, content: str, node: Optional[str] = None):
        """推送 reasoning 事件（思考内容，用于 reasoning/thinking 模型）"""
        node_id = node or self._current_node
        
        event = {
            "event": "reasoning",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "content": content,
            "created_at": _timestamp(),
        }
        if node_id:
            event["node_id"] = node_id
        
        await self._push(event)
    
    async def push_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: str,
        tool_result: str,
        tool_status: str = "succeeded",
        batch_id: Optional[str] = None,
        node: Optional[str] = None,
    ):
        """
        推送 tool 事件（工具调用完成）

        Args:
            tool_call_id: 工具调用 ID
            tool_name: 工具名称
            tool_arguments: 工具参数（JSON 字符串）
            tool_result: 工具执行结果
            tool_status: 工具执行状态（succeeded/failed/cancelled/timeout/unknown）
            batch_id: 并发批次标识（例如 round-1）
            node: 节点名称
        """
        # 计算工具执行时长
        duration_ms = None
        if tool_call_id in self._tool_start_times:
            start_time = self._tool_start_times.pop(tool_call_id)
            duration_ms = (time.perf_counter() - start_time) * 1000

        node_id = node or self._current_node

        event = {
            "event": "tool",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "tool_call": {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": tool_arguments,
                }
            },
            "tool_result": tool_result,
            "status": tool_status,
            "batch_id": batch_id,
            "created_at": _timestamp(),
        }
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        if node_id:
            event["node_id"] = node_id

        await self._push(event)
    
    async def push_harness_feedback(
        self,
        feedback: str,
        batch_id: Optional[str] = None,
        node: Optional[str] = None,
    ):
        """推送 Harness 后处理反馈；空内容也作为工具批次分隔事件。"""
        node_id = node or self._current_node
        event = {
            "event": "harness_feedback",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "content": feedback or "",
            "batch_id": batch_id,
            "empty": not bool(feedback),
            "created_at": _timestamp(),
        }
        if node_id:
            event["node_id"] = node_id

        logger.info(
            "Push harness_feedback SSE: node=%s batch=%s empty=%s content_len=%s content=%r",
            node_id,
            batch_id,
            event["empty"],
            len(event["content"]),
            event["content"][:120],
        )
        await self._push(event)

    async def push_tool_start(
        self,
        tool_call_id: str,
        tool_name: str,
        tool_arguments: str,
        batch_id: Optional[str] = None,
        node: Optional[str] = None,
    ):
        """
        推送 tool_start 事件（工具调用开始）

        在工具执行前调用，让前端知道正在调用什么工具

        Args:
            tool_call_id: 工具调用 ID
            tool_name: 工具名称
            tool_arguments: 工具参数（JSON 字符串）
            batch_id: 并发批次标识（例如 round-1）
            node: 节点名称
        """
        # 记录工具调用开始时间
        self._tool_start_times[tool_call_id] = time.perf_counter()

        node_id = node or self._current_node

        event = {
            "event": "tool_start",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "tool_call": {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": tool_arguments,
                }
            },
            "batch_id": batch_id,
            "created_at": _timestamp(),
        }
        if node_id:
            event["node_id"] = node_id

        await self._push(event)
    
    def add_usage(self, usage: dict):
        """累加 token 使用量（用于多次 LLM 调用）"""
        self._prompt_tokens += usage.get("prompt_tokens", 0)
        self._completion_tokens += usage.get("completion_tokens", 0)
        self._total_tokens += usage.get("total_tokens", 0)
    
    async def push_message_end(self, usage: Optional[dict] = None, context_tokens: Optional[int] = None):
        """
        推送 message_end 事件

        Args:
            usage: LLM 调用的 token 使用情况（包括系统提示词）
            context_tokens: 会话上下文的 token 数（历史消息，不包括系统提示词）
        """
        has_accumulated_usage = any((
            self._prompt_tokens,
            self._completion_tokens,
            self._total_tokens,
        ))
        if usage and not has_accumulated_usage:
            self._prompt_tokens = usage.get("prompt_tokens", 0)
            self._completion_tokens = usage.get("completion_tokens", 0)
            self._total_tokens = usage.get("total_tokens", 0)

        self._latency = time.perf_counter() - self._start_time

        metadata = {
            "usage": {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
                "latency": self._latency,
            }
        }

        # 如果提供了会话上下文 token 数，添加到 metadata
        if context_tokens is not None:
            metadata["context_tokens"] = context_tokens

        # 添加日志
        logger.debug(
            "push_message_end: prompt=%s, completion=%s, total=%s, context_tokens=%s, latency=%.3fs",
            self._prompt_tokens,
            self._completion_tokens,
            self._total_tokens,
            context_tokens,
            self._latency,
        )

        await self._push({
            "event": "message_end",
            "task_id": self.task_id,
            "id": self.message_id,
            "conversation_id": self.thread_id,
            "metadata": metadata
        })

        logger.debug(f"message_end event pushed to queue, stream_mode={self.stream_mode}")
    
    async def push_workflow_finished(
        self,
        status: str = "succeeded",
        outputs: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        """推送 workflow_finished 事件"""
        elapsed_time = time.perf_counter() - self._start_time

        data = {
            "id": self.workflow_run_id,
            "workflow_id": self.workflow_id,
            "conversation_id": self.thread_id,
            "status": status,
            "outputs": outputs or {},
            "elapsed_time": elapsed_time,
            "total_tokens": self._total_tokens,
            "total_steps": self._node_index,
            "created_at": _timestamp(),
            "finished_at": _timestamp(),
        }
        if error:
            data["error"] = error

        await self._push({
            "event": "workflow_finished",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "data": data,
        })

    async def push_context_compression_started(
        self,
        original_tokens: int,
    ):
        """推送 context_compression_started 事件（上下文压缩开始）"""
        await self._push({
            "event": "context_compression_started",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "conversation_id": self.thread_id,
            "data": {
                "original_tokens": original_tokens,
                "created_at": _timestamp(),
            },
        })

    async def push_context_compression_finished(
        self,
        compressed_tokens: int,
        compressed_message_count: int,
        original_message_count: int,
    ):
        """推送 context_compression_finished 事件（上下文压缩完成）"""
        await self._push({
            "event": "context_compression_finished",
            "task_id": self.task_id,
            "workflow_run_id": self.workflow_run_id,
            "conversation_id": self.thread_id,
            "data": {
                "compressed_tokens": compressed_tokens,
                "compressed_message_count": compressed_message_count,
                "original_message_count": original_message_count,
                "created_at": _timestamp(),
            },
        })
    
    async def _push_error(self, error: str):
        """推送 error 事件"""
        await self._push({
            "event": "error",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "status": 500,
            "code": "workflow_error",
            "message": error,
        })
    
    async def push_model_retry(
        self,
        *,
        error: str,
        model: Optional[str] = None,
        node: Optional[str] = None,
        attempt: int = 1,
        max_attempts: int = 1,
        delay: float = 0.0,
        call_type: Optional[str] = None,
    ):
        """推送模型调用重试事件。"""
        data = {
            "error": error,
            "model": model,
            "node_id": node or self._current_node,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "delay": delay,
            "call_type": call_type,
            "created_at": _timestamp(),
        }
        await self._push({
            "event": "model_retry",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "data": data,
        })

    async def push_model_error(
        self,
        error: str,
        node: Optional[str] = None,
        model_id: Optional[str] = None,
        *,
        model: Optional[str] = None,
        call_type: Optional[str] = None,
    ):
        """推送模型调用失败事件。"""
        model_value = model or model_id
        node_id = node or self._current_node
        data = {
            "error": str(error or "Model call failed"),
            "model": model_value,
            "model_id": model_value,
            "node_id": node_id,
            "call_type": call_type,
            "created_at": _timestamp(),
        }
        event = {
            "event": "model_error",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "error": data["error"],
            "model_id": model_value,
            "data": data,
        }
        if node_id:
            event["node_id"] = node_id
        await self._push(event)
    
    async def push_confirm_request(
        self,
        confirm_id: str,
        action: str,
        description: str,
        require_sudo: bool = False,
        node: Optional[str] = None,
    ):
        """
        推送 confirm_request 事件（请求用户确认危险操作）

        前端收到后应弹出确认对话框，用户确认/拒绝后调用
        POST /api/confirm/{confirm_id} 接口

        Args:
            confirm_id: 确认 ID
            action: 操作描述
            description: 详细说明
            require_sudo: 是否需要 sudo 密码
            node: 节点 ID
        """
        node_id = node or self._current_node
        event = {
            "event": "confirm_request",
            "task_id": self.task_id,
            "message_id": self.message_id,
            "conversation_id": self.thread_id,
            "confirm_id": confirm_id,
            "action": action,
            "description": description,
            "require_sudo": require_sudo,
            "created_at": _timestamp(),
        }
        if node_id:
            event["node_id"] = node_id
        self.confirmation_requests.append(event)
        await self._push(event)
    
    async def finish(self):
        """结束流"""
        if not self.done:
            self.done = True
            await self.queue.put(None)  # 结束标记
    
    # === 兼容旧 API ===
    
    async def push_start(self):
        """兼容旧 API"""
        await self.push_workflow_started()
    
    async def push_output(self, data: str, node: Optional[str] = None):
        """兼容旧 API - 推送输出"""
        await self.push_message(data, node)
    
    async def push_chunk(self, data: str, node: Optional[str] = None):
        """兼容旧 API - 推送 chunk"""
        await self.push_message(data, node)
    
    async def push_result(self, state: dict, metadata: dict):
        """兼容旧 API - 推送最终结果"""
        # 提取 answer
        answer = "".join(self.outputs)
        if not answer:
            messages = state.get("__messages__") or []
            # 只取最后一条 assistant 消息（可能是本轮新增的）
            # 注意：这里无法精确区分新旧消息，但 outputs 为空时说明没有通过 channel 输出
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    answer = msg.get("content", "")
                    break
        
        # 检查状态
        is_interrupted = state.get("__interrupted__", False)
        status = "succeeded" if not is_interrupted else "interrupted"
        
        # 推送 message_end
        await self.push_message_end()
        
        # 推送 workflow_finished
        await self.push_workflow_finished(
            status=status,
            outputs={
                "answer": answer,
                "conversation_id": self.thread_id,
                "trace_id": metadata.get("trace_id"),
                "interrupted": is_interrupted,
            }
        )
    
    # === 事件消费 ===
    
    async def events(self) -> AsyncIterator[dict]:
        """消费事件流（流式模式）"""
        while True:
            event = await self.queue.get()
            if event is None:
                break
            yield event
    
    def get_answer(self) -> str:
        """获取完整的 answer（所有输出拼接）"""
        return "".join(self.outputs)
    
    def get_usage(self) -> dict:
        """获取 usage 统计"""
        return {
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._total_tokens,
            "latency": self._latency,
        }


# === ContextVar ===

_output_channel_var: ContextVar[Optional[OutputChannel]] = ContextVar(
    '_output_channel', 
    default=None
)


def get_output_channel() -> Optional[OutputChannel]:
    """获取当前输出通道"""
    return _output_channel_var.get()


async def output(
    content: Any, 
    node: Optional[str] = None,
    save_to_context: bool = False,
    stream: bool = False,
    silent: bool = False,
) -> str:
    """
    输出内容给用户
    
    Args:
        content: 输出内容（字符串或 async iterator）
        node: 节点名称（可选，用于标识输出来源）
        save_to_context: 是否保存到 __messages__
        stream: 是否流式输出（默认 True）
        silent: 是否静默模式（只保存到上下文，不输出给用户）
    
    Returns:
        输出的完整内容
    """
    channel = _output_channel_var.get()
    
    # 检查是否为 async iterator
    if hasattr(content, '__aiter__'):
        chunks = []
        async for chunk in content:
            chunks.append(chunk)
            if not silent and stream and channel:
                await channel.push_message(chunk, node)
        full_content = "".join(chunks)
        if not silent and not stream and channel:
            await channel.push_message(full_content, node)
    else:
        full_content = str(content)
        if not silent and channel:
            await channel.push_message(full_content, node)
    
    # 保存到上下文
    if save_to_context and channel and channel.state is not None:
        messages = channel.state.get("__messages__") or []
        messages.append({"role": "assistant", "content": full_content})
        channel.state["__messages__"] = messages
    
    return full_content
