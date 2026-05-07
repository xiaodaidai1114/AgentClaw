"""
Traced Wrappers - 追踪包装器

提供：
- TracedWorkflow: 包装 Workflow，自动记录 Trace 和 Span
- TracedLLMManager: 包装 LLMManager，自动记录 Generation

设计原则：
- 解耦：不修改原有类，通过包装实现追踪
- 透明：包装器对外接口与原类一致
- 可选：可以选择是否使用追踪
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional
from datetime import datetime
from contextvars import ContextVar
import time

from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow
    from agentclaw.model.manager import LLMManager
    from agentclaw.runtime.tracing.base import BaseTracer

logger = get_logger(__name__)

_TRACE_OUTPUT_MAX = 2000  # trace output 最大长度


def _usage_summary(usage: Optional[dict]) -> str:
    if not usage:
        return "usage=none"
    return (
        f"prompt={usage.get('prompt_tokens', 0)}, "
        f"completion={usage.get('completion_tokens', 0)}, "
        f"total={usage.get('total_tokens', 0)}"
    )


def _extract_trace_output(result: dict) -> Optional[dict]:
    """从工作流执行结果中提取用户输出。

    优先从 OutputChannel.outputs 获取（流式累积文本），
    回退到 __messages__ 最后一条 assistant 消息，
    再回退到 state 中常见的输出 key。
    """
    if not isinstance(result, dict):
        return None

    # 尝试从 OutputChannel 获取累积输出
    try:
        from agentclaw.runtime.streaming.context import get_output_channel
        channel = get_output_channel()
        logger.debug(
            "_extract_trace_output: has_channel=%s, outputs_count=%s",
            bool(channel),
            len(channel.outputs) if channel and hasattr(channel, "outputs") else "N/A",
        )
        if channel and channel.outputs:
            answer = "".join(channel.outputs)
            if answer:
                if len(answer) > _TRACE_OUTPUT_MAX:
                    answer = answer[:_TRACE_OUTPUT_MAX] + "..."
                return {"answer": answer}
    except Exception as e:
        logger.debug(f"_extract_trace_output: channel error: {e}")

    # result 可能是 {"state": {...}, "metadata": {...}} 或直接是 state dict
    state = result.get("state", result)
    logger.debug(f"_extract_trace_output: state keys={list(state.keys())[:10]}, has __messages__={'__messages__' in state}")

    # 从 __messages__ 取最后一条 assistant 消息
    messages = state.get("__messages__") or []
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content", "")
            if content:
                if len(content) > _TRACE_OUTPUT_MAX:
                    content = content[:_TRACE_OUTPUT_MAX] + "..."
                return {"answer": content}

    # 从 state 中常见的输出 key 提取（final_answer, answer, output, result 等）
    for key in ("final_answer", "answer", "output", "result", "response"):
        val = state.get(key)
        if val and isinstance(val, str):
            if len(val) > _TRACE_OUTPUT_MAX:
                val = val[:_TRACE_OUTPUT_MAX] + "..."
            return {"answer": val}

    return None

# ContextVar 用于在节点执行时获取当前 span
_current_span_id: ContextVar[Optional[str]] = ContextVar('_current_span_id', default=None)
_current_trace_id: ContextVar[Optional[str]] = ContextVar('_current_trace_id', default=None)


class StateProxy(dict):
    """
    State 代理，用于追踪节点实际访问的字段
    
    每个节点执行时创建新实例，记录该节点访问过的 key
    """
    
    def __init__(self, data: dict, accessed_keys: Optional[set] = None):
        super().__init__(data)
        # 支持共享 accessed_keys（用于 copy 场景）
        self._accessed_keys: set = accessed_keys if accessed_keys is not None else set()
    
    def __getitem__(self, key):
        self._accessed_keys.add(key)
        return super().__getitem__(key)
    
    def get(self, key, default=None):
        self._accessed_keys.add(key)
        return super().get(key, default)
    
    def copy(self) -> "StateProxy":
        """返回共享 _accessed_keys 的新 StateProxy"""
        return StateProxy(dict(self), self._accessed_keys)
    
    def get_accessed(self, exclude_keys: Optional[set] = None, max_length: int = 500) -> dict:
        """
        返回实际访问过的字段
        
        Args:
            exclude_keys: 要排除的 key 集合
            max_length: 值的最大长度，超过则截断
        """
        exclude = exclude_keys or set()
        result = {}
        for k in self._accessed_keys:
            if k in exclude or k not in self:
                continue
            v = super().__getitem__(k)  # 用 super 避免再次记录
            # __messages__ 保持原始类型，由调用方处理摘要
            if k == "__messages__":
                result[k] = v
            elif isinstance(v, str) and len(v) > max_length:
                result[k] = v[:max_length] + "..."
            elif isinstance(v, (dict, list)) and len(str(v)) > max_length:
                result[k] = str(v)[:max_length] + "..."
            else:
                result[k] = v
        return result


_TRACE_MSG_CONTENT_MAX = 200
_TRACE_MSG_TAIL_COUNT = 6


def _truncate_msg_content(msg: dict, max_len: int = _TRACE_MSG_CONTENT_MAX) -> dict:
    """截断单条消息的 content 字段"""
    out = dict(msg)
    content = out.get("content")
    if isinstance(content, str) and len(content) > max_len:
        out["content"] = content[:max_len] + f"...({len(content)} chars)"
    # tool_calls 的 arguments 也可能很长
    tcs = out.get("tool_calls")
    if isinstance(tcs, list):
        trimmed = []
        for tc in tcs:
            tc_copy = dict(tc) if isinstance(tc, dict) else tc
            if isinstance(tc_copy, dict):
                func = tc_copy.get("function")
                if isinstance(func, dict):
                    args = func.get("arguments", "")
                    if isinstance(args, str) and len(args) > max_len:
                        func = dict(func)
                        func["arguments"] = args[:max_len] + f"...({len(args)} chars)"
                        tc_copy = dict(tc_copy)
                        tc_copy["function"] = func
            trimmed.append(tc_copy)
        out["tool_calls"] = trimmed
    return out


def _summarize_messages(msgs: list, tail: int = _TRACE_MSG_TAIL_COUNT) -> dict:
    """将消息列表压缩为摘要：总数 + 最近 N 条（内容截断）"""
    if not msgs:
        return {"count": 0, "messages": []}
    total = len(msgs)
    recent = msgs[-tail:] if total > tail else msgs
    return {
        "count": total,
        "messages": [_truncate_msg_content(m) if isinstance(m, dict) else m for m in recent],
    }


def get_current_span_id() -> Optional[str]:
    """获取当前 Span ID"""
    return _current_span_id.get()


def get_current_trace_id() -> Optional[str]:
    """获取当前 Trace ID"""
    return _current_trace_id.get()


class TracedLLMManager:
    """
    LLMManager 追踪包装器
    
    自动记录每次 LLM 调用的 Generation 数据
    
    Example:
        llm_manager = LLMManager()
        tracer = DatabaseTracer(db)
        traced_llm = TracedLLMManager(llm_manager, tracer)
        
        # 使用方式与 LLMManager 一致
        result = await traced_llm.invoke(messages)
    """
    
    def __init__(self, llm_manager: "LLMManager", tracer: "BaseTracer"):
        self._llm = llm_manager
        self._tracer = tracer
        self._last_generation_id: Optional[str] = None
    
    @property
    def llm_manager(self) -> "LLMManager":
        """获取原始 LLMManager"""
        return self._llm
    
    def __getattr__(self, name: str) -> Any:
        """代理未覆盖的属性到原始 LLMManager"""
        return getattr(self._llm, name)

    async def update_tool_results(self, tool_results: list) -> None:
        """工具执行完成后，把结果补充到最近一次 generation 的 metadata 中"""
        if not self._last_generation_id or not self._tracer.enabled:
            return
        tool_results_data = [
            {"id": r.get("tool_call_id", ""), "name": r.get("tool_name", ""), "result": r.get("result", ""), "status": r.get("status", "")}
            for r in tool_results
        ]
        await self._tracer.update_generation_metadata(
            self._last_generation_id, {"tool_results": tool_results_data}
        )
    
    async def invoke(
        self,
        messages: List[dict],
        *,
        response_format: Optional[dict] = None,
        model_id: Optional[str] = None,
        images: Optional[List] = None,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        非流式调用 LLM（带追踪）
        """
        start_time = time.perf_counter()
        prompt_json = self._serialize_messages(messages)
        
        try:
            result = await self._llm.invoke(
                messages,
                response_format=response_format,
                model_id=model_id,
                images=images,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # 获取 usage 信息
            usage = self._get_last_usage()
            
            # 更新 OutputChannel 的 token 统计
            from agentclaw.runtime.streaming.context import get_output_channel
            channel = get_output_channel()
            if channel and usage:
                channel.add_usage(usage)
            
            # 序列化 completion（可能是 str 或 LLMResponse）
            completion_str = ""
            tool_calls_metadata = None
            
            if hasattr(result, 'content'):
                # LLMResponse 对象
                completion_str = result.content or ""
                if hasattr(result, 'tool_calls') and result.tool_calls:
                    tool_calls_metadata = [
                        {
                            "id": tc.id,
                            "name": tc.name, 
                            "arguments": tc.arguments
                        } 
                        for tc in result.tool_calls
                    ]
            else:
                completion_str = str(result) if result else ""
            
            # 记录 Generation
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                metadata = {}
                if tool_calls_metadata:
                    metadata["tool_calls"] = tool_calls_metadata
                if tools:
                    metadata["tools_available"] = [t.get("function", {}).get("name", "") for t in tools]
                
                gen_record = await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion=completion_str,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency_ms,
                    status="success",
                    metadata=metadata if metadata else None,
                )
                if gen_record:
                    self._last_generation_id = gen_record.id

            return result
            
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion="",
                    latency_ms=latency_ms,
                    status="error",
                    error=str(e),
                )
            raise
    
    async def stream(
        self,
        messages: List[dict],
        *,
        model_id: Optional[str] = None,
        images: Optional[List] = None,
        push_to_context: bool = True,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        流式调用 LLM（带追踪）
        """
        start_time = time.perf_counter()
        prompt_json = self._serialize_messages(messages)
        completion_chunks = []
        
        try:
            async for chunk in self._llm.stream(
                messages,
                model_id=model_id,
                images=images,
                push_to_context=push_to_context,
                **kwargs,
            ):
                completion_chunks.append(chunk)
                yield chunk
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            completion = "".join(completion_chunks)

            # 从 LLMManager 获取精确的 token 统计
            usage = self._get_last_usage()

            # 更新 OutputChannel 的 token 统计（无论 tracer 是否启用）
            from agentclaw.runtime.streaming.context import get_output_channel
            channel = get_output_channel()
            if channel and usage:
                logger.debug(f"TracedLLMManager: add_usage to channel ({_usage_summary(usage)})")
                channel.add_usage(usage)
                logger.debug(f"TracedLLMManager: Channel token stats after add_usage - prompt={channel._prompt_tokens}, completion={channel._completion_tokens}")
            else:
                if not channel:
                    logger.warning("TracedLLMManager: No output channel found")
                if not usage:
                    logger.warning("TracedLLMManager: No usage data available")

            # 记录 Generation
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion=completion,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency_ms,
                    status="success",
                )
                
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion="".join(completion_chunks),
                    latency_ms=latency_ms,
                    status="error",
                    error=str(e),
                )
            raise
    
    async def stream_with_tools(
        self,
        messages: List[dict],
        *,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        model_id: Optional[str] = None,
        images: Optional[List] = None,
        push_to_context: bool = True,
        **kwargs,
    ) -> AsyncIterator:
        """
        流式调用 LLM + 工具调用（带追踪）
        """
        from agentclaw.model.manager import LLMResponse
        
        start_time = time.perf_counter()
        prompt_json = self._serialize_messages(messages)
        completion_chunks = []
        final_response = None
        
        try:
            async for item in self._llm.stream_with_tools(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                model_id=model_id,
                images=images,
                push_to_context=push_to_context,
                **kwargs,
            ):
                if isinstance(item, str):
                    completion_chunks.append(item)
                    yield item
                elif isinstance(item, LLMResponse):
                    final_response = item
                    yield item
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            completion = "".join(completion_chunks)

            # 从 LLMManager 获取精确的 token 统计
            usage = self._get_last_usage()

            # 更新 OutputChannel 的 token 统计（无论 tracer 是否启用）
            from agentclaw.runtime.streaming.context import get_output_channel
            channel = get_output_channel()
            if channel and usage:
                logger.debug(f"TracedLLMManager: add_usage to channel ({_usage_summary(usage)})")
                channel.add_usage(usage)
                logger.debug(f"TracedLLMManager: Channel token stats after add_usage - prompt={channel._prompt_tokens}, completion={channel._completion_tokens}")
            else:
                if not channel:
                    logger.warning("TracedLLMManager: No output channel found")
                if not usage:
                    logger.warning("TracedLLMManager: No usage data available")

            # 记录 Generation
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                metadata = {}
                if final_response and final_response.tool_calls:
                    metadata["tool_calls"] = [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in final_response.tool_calls
                    ]
                if tools:
                    metadata["tools_available"] = [t.get("function", {}).get("name", "") for t in tools]

                gen_record = await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion=completion or (final_response.content if final_response else ""),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency_ms,
                    status="success",
                    metadata=metadata if metadata else None,
                )
                if gen_record:
                    self._last_generation_id = gen_record.id
                
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if self._tracer.enabled:
                config = self._llm.get_model(model_id)
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion="".join(completion_chunks),
                    latency_ms=latency_ms,
                    status="error",
                    error=str(e),
                )
            raise
    
    async def invoke_with_tools(
        self,
        messages: List[dict],
        tools: List[dict],
        **kwargs,
    ) -> dict:
        """
        带工具调用的 LLM 调用（带追踪）
        """
        start_time = time.perf_counter()
        prompt_json = self._serialize_messages(messages)
        
        try:
            result = await self._llm.invoke_with_tools(messages, tools, **kwargs)
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            completion = result.get("content", "") or ""
            
            if self._tracer.enabled:
                config = self._llm.get_model()
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion=completion,
                    latency_ms=latency_ms,
                    status="success",
                    metadata={"tool_calls": result.get("tool_calls")},
                )
            
            return result
            
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if self._tracer.enabled:
                config = self._llm.get_model()
                await self._tracer.log_generation(
                    model_id=config.id,
                    model_name=config.model,
                    prompt=prompt_json,
                    completion="",
                    latency_ms=latency_ms,
                    status="error",
                    error=str(e),
                )
            raise
    
    def _serialize_messages(self, messages: List[dict]) -> str:
        """将 messages 序列化为 JSON 字符串"""
        import json
        # 保留完整的消息结构，包括 tool_calls 和 tool 消息
        clean_messages = []
        for msg in messages:
            clean_msg = {
                "role": msg.get("role", ""),
            }
            # 处理 content
            content = msg.get("content")
            if content is not None:
                clean_msg["content"] = content
            # 处理 tool_calls（assistant 消息）
            if msg.get("tool_calls"):
                clean_msg["tool_calls"] = msg["tool_calls"]
            # 处理 tool_call_id（tool 消息）
            if msg.get("tool_call_id"):
                clean_msg["tool_call_id"] = msg["tool_call_id"]
            clean_messages.append(clean_msg)
        return json.dumps(clean_messages, ensure_ascii=False)
    
    def _get_last_usage(self) -> dict:
        """获取最后一次调用的 usage 信息"""
        if self._llm._usage_history:
            last = self._llm._usage_history[-1]
            return {
                "prompt_tokens": last.prompt_tokens,
                "completion_tokens": last.completion_tokens,
                "total_tokens": last.total_tokens,
            }
        return {}


class TracedWorkflow:
    """
    Workflow 追踪包装器
    
    自动记录：
    - Trace: 工作流执行（开始/结束时间、状态、输入输出）
    - Span: 每个节点执行（运行时间、状态）
    - 自动将 TracedLLMManager 注入到 context
    
    Example:
        workflow = Workflow(id="my_workflow", name="My Workflow")
        workflow.add_node(LLMNode(...))
        
        tracer = DatabaseTracer(db)
        traced = TracedWorkflow(workflow, tracer)
        
        # 使用方式与 Workflow 一致
        result = await traced.run({"user_input": "hello"}, thread_id="xxx")
    """
    
    def __init__(self, workflow: "Workflow", tracer: "BaseTracer"):
        self._workflow = workflow
        self._tracer = tracer
        self._traced_llm: Optional[TracedLLMManager] = None
        self._nodes_wrapped = False
    
    @property
    def workflow(self) -> "Workflow":
        """获取原始 Workflow"""
        return self._workflow
    
    @property
    def id(self) -> str:
        return self._workflow.id
    
    @property
    def name(self) -> str:
        return self._workflow.name
    
    def __getattr__(self, name: str) -> Any:
        """代理未覆盖的属性到原始 Workflow"""
        return getattr(self._workflow, name)
    
    def run(
        self,
        inputs: Optional[dict] = None,
        context=None,
        *,
        stream: bool = False,
        thread_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout: Optional[int] = None,
        metadata: Optional[dict] = None,
    ):
        """执行工作流（带追踪）"""
        if stream:
            return self._run_stream_traced(
                inputs, context, thread_id, user_id, timeout, metadata
            )
        else:
            return self._run_blocking_traced(
                inputs, context, thread_id, user_id, timeout, metadata
            )
    
    async def _run_blocking_traced(
        self,
        inputs: Optional[dict],
        context,
        thread_id: Optional[str],
        user_id: Optional[str],
        timeout: Optional[int],
        metadata: Optional[dict],
    ) -> dict:
        """非流式执行（带追踪）"""
        effective_thread_id = thread_id or (inputs or {}).get("thread_id", "")
        start_time = time.perf_counter()
        
        # 包装 LLMManager 和节点
        self._wrap_llm_manager()
        self._wrap_nodes()
        
        # 确保有 OutputChannel，以便节点的 output_to_user 内容能被累积
        from agentclaw.runtime.streaming.context import (
            OutputChannel,
            _output_channel_var,
            get_output_channel,
        )
        existing_channel = get_output_channel()
        if existing_channel:
            channel_token = None
        else:
            channel = OutputChannel(
                workflow_id=self._workflow.id,
                thread_id=effective_thread_id,
                stream_mode=False,
            )
            channel_token = _output_channel_var.set(channel)

        async with self._tracer.trace(
            name=self._workflow.id,
            workflow_id=self._workflow.id,
            thread_id=effective_thread_id,
            user_id=user_id,
            input_data=inputs,
            metadata=metadata,
            run_type="blocking",
        ) as trace:
            try:
                # 设置 trace_id 到 ContextVar
                if trace:
                    _current_trace_id.set(trace.id)

                result = await self._workflow._run_blocking(
                    inputs, context, thread_id, user_id, timeout, metadata
                )

                duration_ms = (time.perf_counter() - start_time) * 1000

                # 捕获用户输出到 trace
                if trace:
                    trace.output_data = _extract_trace_output(result)
                    answer = (trace.output_data or {}).get("answer", "")
                    logger.debug(
                        "_run_blocking_traced: trace output captured (has_answer=%s, answer_len=%s)",
                        bool(answer),
                        len(answer),
                    )

                # 添加追踪元数据
                if "metadata" not in result:
                    result["metadata"] = {}
                result["metadata"]["trace_id"] = trace.id if trace else None
                result["metadata"]["duration_ms"] = duration_ms
                
                return result
                
            except Exception as e:
                if trace:
                    trace.status = "error"
                    trace.error = str(e)
                raise
            finally:
                _current_trace_id.set(None)
                if channel_token is not None:
                    _output_channel_var.reset(channel_token)

    async def _run_stream_traced(
        self,
        inputs: Optional[dict],
        context,
        thread_id: Optional[str],
        user_id: Optional[str],
        timeout: Optional[int],
        metadata: Optional[dict],
    ):
        """流式执行（带追踪）"""
        effective_thread_id = thread_id or (inputs or {}).get("thread_id", "")
        start_time = time.perf_counter()
        
        # 包装 LLMManager 和节点
        self._wrap_llm_manager()
        self._wrap_nodes()
        
        async with self._tracer.trace(
            name=self._workflow.id,
            workflow_id=self._workflow.id,
            thread_id=effective_thread_id,
            user_id=user_id,
            input_data=inputs,
            metadata=metadata,
            run_type="stream",
        ) as trace:
            try:
                if trace:
                    _current_trace_id.set(trace.id)
                
                yield {"type": "start", "workflow_id": self._workflow.id, "trace_id": trace.id if trace else None}
                
                async for event in self._workflow._run_stream(
                    inputs, context, thread_id, user_id, timeout, metadata
                ):
                    yield event
                
                duration_ms = (time.perf_counter() - start_time) * 1000

                # 捕获用户输出到 trace
                if trace:
                    trace.output_data = _extract_trace_output({})

                yield {"type": "trace_complete", "duration_ms": duration_ms, "trace_id": trace.id if trace else None}
                
            except Exception as e:
                if trace:
                    trace.status = "error"
                    trace.error = str(e)
                yield {"type": "error", "data": str(e)}
            finally:
                _current_trace_id.set(None)
    
    def _wrap_llm_manager(self) -> None:
        """包装 LLMManager 以支持 Generation 追踪"""
        self._workflow._ensure_components()
        
        if self._workflow._llm_manager:
            # 检查是否已经是 TracedLLMManager
            if isinstance(self._workflow._llm_manager, TracedLLMManager):
                self._traced_llm = self._workflow._llm_manager
                return
            
            self._traced_llm = TracedLLMManager(
                self._workflow._llm_manager,
                self._tracer,
            )
            # 替换 workflow 的 llm_manager
            self._workflow._llm_manager = self._traced_llm
            logger.debug("已包装 LLMManager 为 TracedLLMManager")
    
    def _wrap_nodes(self) -> None:
        """包装节点以支持 Span 追踪"""
        if self._nodes_wrapped:
            return
        
        # 检查 workflow 是否已经被包装过（防止多个 TracedWorkflow 实例重复包装）
        if getattr(self._workflow, '_tracing_nodes_wrapped', False):
            self._nodes_wrapped = True
            return
        
        # 保存原始的 _wrap_node_for_langgraph 方法
        original_wrap = self._workflow._wrap_node_for_langgraph
        tracer = self._tracer
        
        def traced_wrap_node(node):
            """包装节点，添加 Span 追踪"""
            original_fn = original_wrap(node)
            
            async def traced_node(state: dict):
                import copy
                node_type = type(node).__name__
                # 只排除内部系统字段
                exclude_keys = {"__interrupt__", "__interrupted__", "__status__", "__interrupt_info__"}
                
                # 在节点执行前，先捕获 __messages__ 的快照
                # 因为 LLMNode 会在执行过程中修改 __messages__
                messages_snapshot = None
                if "__messages__" in state:
                    try:
                        messages_snapshot = copy.deepcopy(state["__messages__"])
                    except Exception:
                        # 如果深拷贝失败，尝试浅拷贝
                        messages_snapshot = list(state["__messages__"])
                
                # 为每个节点创建独立的 StateProxy
                proxy = StateProxy(state)
                
                def _summarize_input(data: dict, messages_before: list = None) -> dict:
                    """对输入数据做摘要处理"""
                    result = {}
                    for k, v in data.items():
                        if k == "__messages__":
                            msgs = messages_before if messages_before is not None else v
                            if isinstance(msgs, list) and len(msgs) > 0:
                                result[k] = _summarize_messages(msgs)
                            else:
                                result[k] = {"count": 0, "messages": []}
                        elif k == "messages" and isinstance(v, list):
                            result[k] = _summarize_messages(v)
                        else:
                            result[k] = v
                    return result
                
                async with tracer.span(
                    name=node.id,
                    node_type=node_type,
                    input_data={},  # 先置空，执行后再填充
                ) as span:
                    try:
                        # 传入代理，记录实际访问的字段
                        result = await original_fn(proxy)
                        
                        if span:
                            # input_data: 只记录节点实际访问过的字段
                            # 对于 __messages__，使用执行前的快照
                            accessed = proxy.get_accessed(exclude_keys=exclude_keys)
                            span.input_data = _summarize_input(accessed, messages_snapshot)
                            
                            # output_data: 只保留本节点新增/修改的字段
                            output_data = {}
                            pre_msg_count = len(messages_snapshot) if messages_snapshot else 0
                            for k, v in result.items():
                                if k in exclude_keys:
                                    continue
                                old_value = dict.get(state, k)
                                if old_value != v:
                                    if k == "__messages__" and isinstance(v, list):
                                        # 只记录本节点新增的消息
                                        new_msgs = v[pre_msg_count:]
                                        output_data[k] = {
                                            "added": len(new_msgs),
                                            "total": len(v),
                                            "new_messages": [
                                                _truncate_msg_content(m) if isinstance(m, dict) else m
                                                for m in new_msgs
                                            ],
                                        }
                                    elif isinstance(v, str) and len(v) > 500:
                                        output_data[k] = v[:500] + "..."
                                    else:
                                        output_data[k] = v
                            span.output_data = output_data
                            
                            # 追加 node_log_id 到 trace
                            from agentclaw.runtime.tracing.db_tracer import _current_trace
                            trace = _current_trace.get()
                            if trace:
                                trace.append_node_log(span.id)
                        return result
                    except Exception as e:
                        # GraphInterrupt 是正常的中断信号，标记为 interrupted 而非 error
                        from langgraph.errors import GraphInterrupt
                        if span:
                            accessed = proxy.get_accessed(exclude_keys=exclude_keys)
                            span.input_data = _summarize_input(accessed, messages_snapshot)
                            if isinstance(e, GraphInterrupt):
                                span.status = "interrupted"
                                # 记录中断时的状态
                                span.output_data = {"__interrupted__": True}
                            else:
                                span.status = "error"
                                span.error = str(e)
                        raise
            
            return traced_node
        
        # 替换方法
        self._workflow._wrap_node_for_langgraph = traced_wrap_node
        # 清除已编译的图，强制重新编译
        self._workflow._compiled_graph = None
        self._nodes_wrapped = True
        # 标记 workflow 已被包装，防止其他 TracedWorkflow 实例重复包装
        self._workflow._tracing_nodes_wrapped = True
        logger.debug("已包装节点以支持 Span 追踪")


def create_traced_workflow(
    workflow: "Workflow",
    tracer: Optional["BaseTracer"] = None,
) -> TracedWorkflow:
    """
    创建追踪工作流
    
    Args:
        workflow: 原始工作流
        tracer: 追踪器（不传则使用全局追踪器）
    
    Returns:
        TracedWorkflow 包装器
    
    Example:
        from agentclaw import Workflow, LLMNode
        from agentclaw.runtime.tracing import create_traced_workflow, setup_db_tracing
        
        # 设置追踪
        tracer = setup_db_tracing(db)
        
        # 创建工作流
        workflow = Workflow(id="my_workflow", name="My Workflow")
        workflow.add_node(LLMNode(...))
        
        # 包装为追踪工作流
        traced = create_traced_workflow(workflow, tracer)
        
        # 执行
        result = await traced.run({"user_input": "hello"}, thread_id="xxx")
    """
    if tracer is None:
        from agentclaw.runtime.tracing import get_db_tracer
        tracer = get_db_tracer()
    
    if tracer is None:
        from agentclaw.runtime.tracing.noop_tracer import get_noop_tracer
        tracer = get_noop_tracer()
        logger.warning("未配置追踪器，使用 NoopTracer")
    
    return TracedWorkflow(workflow, tracer)
