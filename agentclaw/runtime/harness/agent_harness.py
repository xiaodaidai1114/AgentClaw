"""Agentic runtime harness helpers."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from agentclaw.logger.config import get_logger

from agentclaw.node.llm_tools import _build_tool_failure_summary, _detect_repeated_calls
from agentclaw.runtime.harness.decisions import ContinueDecision
from agentclaw.runtime.harness.model_output import AssistantTurnOutput, postprocess_model_output
from agentclaw.runtime.harness.model_turn import ModelTurnResult
from agentclaw.runtime.harness.post_tool import (
    PostToolProcessingResult,
    build_post_tool_processing_messages,
    parse_post_tool_processing_response,
)
from agentclaw.runtime.harness.state import HarnessRunState, HarnessTurnState
from agentclaw.runtime.harness.tool_executor import HarnessToolExecutor
from agentclaw.runtime.harness.tool_env import ToolExecutionEnvironment
from agentclaw.runtime.harness.tool_result import ToolResultEnvelope


logger = get_logger(__name__)
_POST_TOOL_MAX_RETRIES = 3
_POST_TOOL_TIMEOUT_SECONDS = 60.0
_MAX_MISSING_TOOL_CONTINUATION_RETRIES = 3


def _get_post_tool_timeout_seconds() -> float:
    raw = os.getenv("HARNESS_POST_TOOL_TIMEOUT", "").strip()
    if not raw:
        return _POST_TOOL_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return _POST_TOOL_TIMEOUT_SECONDS
    return parsed if parsed > 0 else _POST_TOOL_TIMEOUT_SECONDS


def _harness_message_debug_shape(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            parts.append(f"{index}:invalid")
            continue
        content = message.get("content")
        content_text = content if isinstance(content, str) else str(content or "")
        tool_calls = message.get("tool_calls") or []
        marker = ""
        if "<HARNESS_POST_TOOL_PROCESSING>" in content_text:
            marker = "/post_prompt"
        elif "Compact tool results JSON:" in content_text:
            marker = "/post_results"
        elif "<HARNESS_POST_TOOL_RESULT>" in content_text:
            marker = "/post_result"
        elif "<TOOL_EXECUTION_SUMMARY>" in content_text:
            marker = "/tool_summary"
        parts.append(
            f"{index}:{message.get('role')}:{len(content_text)}"
            f"/{len(tool_calls)}tc{marker}"
        )
    return ",".join(parts)


def _harness_message_tail_preview(messages: list[dict[str, Any]], *, limit: int = 5) -> str:
    previews: list[str] = []
    start = max(0, len(messages) - limit)
    for index, message in enumerate(messages[start:], start=start):
        content = message.get("content") if isinstance(message, dict) else ""
        content_text = content if isinstance(content, str) else str(content or "")
        preview = content_text[:160].replace("\n", "\\n")
        previews.append(f"{index}:{message.get('role') if isinstance(message, dict) else 'invalid'}:{preview!r}")
    return " | ".join(previews)


def _extract_latest_user_request(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        if _is_harness_internal_user_message(text):
            continue
        return text
    return ""


def _is_harness_internal_user_message(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "<TOOL_EXECUTION_SUMMARY>",
            "<REPEATED_CALL_WARNING>",
            "<HARNESS_POST_TOOL_RESULT>",
            "<HARNESS_CONTINUE_REQUIRED>",
            "<HARNESS_NEXT_INSTRUCTION>",
        )
    )


def _build_post_tool_context_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        content_text = content if isinstance(content, str) else str(content or "")
        if role == "user" and _is_harness_internal_user_message(content_text):
            continue
        if role == "assistant" and not message.get("tool_calls"):
            continue
        compacted.append(message)
    return compacted


def _stringify_post_tool_response(response: Any) -> str:
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if content is not None:
        return content if isinstance(content, str) else str(content or "")
    return str(response or "")


def _describe_invalid_post_tool_response(response: Any, raw_text: str) -> str:
    tool_calls = getattr(response, "tool_calls", None)
    if tool_calls:
        names = [
            str(getattr(call, "name", "") or "").strip()
            for call in tool_calls
            if str(getattr(call, "name", "") or "").strip()
        ]
        suffix = f": {', '.join(names[:3])}" if names else ""
        return f"后处理阶段返回了工具调用而不是 JSON{suffix}"
    if not str(raw_text or "").strip():
        return "后处理阶段返回空响应"
    return "后处理阶段返回非 JSON 内容"


class AgentRunHarness:
    """Control-plane adapter for one agentic LLMNode run."""

    def __init__(
        self,
        *,
        node_id: str,
        workflow_id: Optional[str],
        thread_id: Optional[str],
        model_id: Optional[str],
        messages: list[dict[str, Any]],
    ):
        self.state = HarnessRunState(
            run_id=f"{thread_id or 'run'}:{node_id}",
            node_id=node_id,
            workflow_id=workflow_id,
            thread_id=thread_id,
            model_id=model_id,
            messages=messages,
        )
        self.tool_executor = HarnessToolExecutor(node_id=node_id)
        self.tool_environment = ToolExecutionEnvironment()
        self.tool_results_history: list[dict[str, Any]] = []
        self.previous_call_signatures: list[str] = []

    def decide(self, action: str, reason: str, **metadata: Any) -> ContinueDecision:
        return self.state.decide(action, reason, **metadata)

    def record_event(self, name: str, **metadata: Any) -> dict[str, Any]:
        return self.state.record_event(name, **metadata)

    def before_model_call(self, *, message_count: int, tool_count: int = 0, stream: bool = False) -> None:
        self.record_event("before_model_call", message_count=message_count, tool_count=tool_count, stream=stream)

    def after_model_response(self, output: AssistantTurnOutput) -> None:
        self.record_event(
            "after_model_response",
            text_len=len(output.text),
            reasoning_len=len(output.reasoning),
            tool_call_count=len(output.tool_calls),
            malformed=output.malformed,
        )

    def after_tool_execute(self, *, result_count: int, feedback_count: int) -> None:
        self.record_event("after_tool_execute", result_count=result_count, feedback_count=feedback_count)

    def on_finish(self, response: str, reason: str, *, round_index: int | None = None, **metadata: Any) -> ContinueDecision:
        self.record_event("on_finish", response_len=len(response or ""), reason=reason)
        return self.decide_finish(reason, round_index=round_index, **metadata)

    def on_error(self, error: Exception | str, **metadata: Any) -> ContinueDecision:
        message = str(error)
        self.state.errors.append(message)
        self.record_event("on_error", error=message, **metadata)
        return self.decide_abort(message, **metadata)

    def begin_turn(self, turn_index: int) -> HarnessTurnState:
        return self.state.begin_turn(turn_index)

    def set_tool_environment(self, environment: ToolExecutionEnvironment) -> None:
        self.tool_environment = environment

    def build_tool_exec_kwargs(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.tool_environment.to_kwargs(state)

    def decide_continue_for_tools(self, *, round_index: int, tool_call_count: int) -> ContinueDecision:
        return self.decide(
            "continue",
            "model requested tool calls",
            round=round_index,
            tool_call_count=tool_call_count,
        )

    def decide_finish(self, reason: str, *, round_index: int | None = None, **metadata: Any) -> ContinueDecision:
        if round_index is not None:
            metadata.setdefault("round", round_index)
        return self.decide("finish", reason, **metadata)

    def decide_abort(self, reason: str, **metadata: Any) -> ContinueDecision:
        return self.decide("abort", reason, **metadata)

    def decide_retry_empty_response(self, *, round_index: int, retries: int) -> ContinueDecision:
        return self.decide(
            "continue",
            "retry empty model response",
            round=round_index,
            retries=retries,
        )

    def record_empty_response(self, *, round_index: int, max_retries: int) -> tuple[bool, int, ContinueDecision]:
        self.state.consecutive_empty_responses += 1
        retries = self.state.consecutive_empty_responses
        current_turn = self.state.current_turn()
        if current_turn is not None:
            current_turn.warnings.append("empty model response")
        if retries >= max_retries:
            return True, retries, self.decide_abort(
                "model returned empty response repeatedly",
                round=round_index,
                retries=retries,
            )
        return False, retries, self.decide_retry_empty_response(round_index=round_index, retries=retries)

    def reset_empty_response_count(self) -> None:
        self.state.consecutive_empty_responses = 0

    def requires_tool_continuation(self) -> bool:
        """Whether the previous post-tool controller explicitly required another tool step."""
        return self.state.pending_continue_rounds > 0

    def consume_tool_continuation_retry(self) -> None:
        if self.state.pending_continue_rounds > 0:
            self.state.pending_continue_rounds -= 1

    def mark_tool_continuation_satisfied(self) -> None:
        """Clear pending forced-tool state once the model actually emits a tool call."""
        self.state.pending_continue_rounds = 0
        self.state.missing_tool_continuation_count = 0

    def should_continue_after_model_text(self, text: str, *, round_index: int) -> ContinueDecision | None:
        """Retry briefly when a post-tool continue decision expected a tool call but got text."""
        content = str(text or "").strip()
        if not content or self.state.pending_continue_rounds <= 0:
            return None
        self.state.missing_tool_continuation_count += 1
        if self.state.missing_tool_continuation_count > _MAX_MISSING_TOOL_CONTINUATION_RETRIES:
            self.consume_tool_continuation_retry()
            self.state.warnings.append("post-tool continue exhausted without a tool call")
            return None
        return self.decide(
            "continue",
            "previous post-tool decision required a tool call but model returned text",
            round=round_index,
            text_len=len(content),
            pending_continue_rounds=self.state.pending_continue_rounds,
            missing_tool_continuation_count=self.state.missing_tool_continuation_count,
            max_missing_tool_continuation_retries=_MAX_MISSING_TOOL_CONTINUATION_RETRIES,
        )

    def postprocess_model_output(self, response: Any = None, *, chunks: list[str] | None = None) -> AssistantTurnOutput:
        output = postprocess_model_output(response, chunks=chunks)
        self.after_model_response(output)
        self.state.assistant_text = output.text
        self.state.reasoning_text = output.reasoning
        current_turn = self.state.current_turn()
        if current_turn is not None:
            current_turn.assistant_text = output.text
            current_turn.reasoning_text = output.reasoning
            current_turn.tool_call_count = len(output.tool_calls)
            current_turn.warnings.extend(output.warnings)
        if output.warnings:
            self.state.warnings.extend(output.warnings)
        return output

    def process_model_response(
        self,
        response: Any = None,
        *,
        chunks: list[str] | None = None,
        round_index: int,
        max_empty_retries: int,
    ) -> ModelTurnResult:
        if response is None and not chunks:
            should_abort, retries, decision = self.record_empty_response(
                round_index=round_index,
                max_retries=max_empty_retries,
            )
            return ModelTurnResult(
                is_empty=True,
                should_abort=should_abort,
                retries=retries,
                decision=decision,
            )
        self.reset_empty_response_count()
        output = self.postprocess_model_output(response, chunks=chunks)
        return ModelTurnResult(output=output)

    def build_assistant_tool_messages(
        self,
        *,
        tool_calls: list[Any],
        tool_results: list[ToolResultEnvelope],
        text_content: str = "",
        reasoning_content: str = "",
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Build assistant/tool messages from normalized tool results."""
        combined_content = "\n".join(part for part in (reasoning_content, text_content) if part) or None
        tool_call_dicts: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        trace_results: list[dict[str, Any]] = []
        for tool_call, envelope in zip(tool_calls, tool_results):
            trace_result = envelope.to_trace_dict()
            trace_results.append(trace_result)
            tool_call_dicts.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": trace_result.get("tool_arguments") or getattr(tool_call, "arguments", "{}"),
                },
            })
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": envelope.model_content,
            })
        assistant_msg = {
            "role": "assistant",
            "content": combined_content,
            "tool_calls": tool_call_dicts,
        }
        return assistant_msg, tool_messages, trace_results

    def append_assistant_tool_messages(
        self,
        *,
        state: dict[str, Any],
        messages: list[dict[str, Any]],
        assistant_msg: dict[str, Any],
        tool_messages: list[dict[str, Any]],
    ) -> None:
        messages.append(assistant_msg)
        messages.extend(tool_messages)
        context_messages = [m for m in (state.get("__messages__") or []) if isinstance(m, dict)]
        context_messages.append(assistant_msg)
        context_messages.extend(tool_messages)
        state["__messages__"] = context_messages


    async def update_trace_tool_results(self, context: Any, round_tool_results: list[dict[str, Any]]) -> None:
        if context and hasattr(context.llm_manager, "update_tool_results"):
            await context.llm_manager.update_tool_results(round_tool_results)

    async def apply_tool_results(
        self,
        *,
        state: dict[str, Any],
        messages: list[dict[str, Any]],
        context: Any,
        tool_calls: list[Any],
        tool_results: list[ToolResultEnvelope],
        text_content: str = "",
        reasoning_content: str = "",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, int]:
        assistant_msg, tool_messages, round_tool_results = self.build_assistant_tool_messages(
            tool_calls=tool_calls,
            tool_results=tool_results,
            text_content=text_content,
            reasoning_content=reasoning_content,
        )
        combined_content = assistant_msg.get("content") or ""
        self.append_assistant_tool_messages(
            state=state,
            messages=messages,
            assistant_msg=assistant_msg,
            tool_messages=tool_messages,
        )
        await self.update_trace_tool_results(context, round_tool_results)
        feedback_messages = self.build_tool_feedback_messages(round_tool_results)
        if feedback_messages:
            messages = self.replace_tool_feedback_messages(messages, feedback_messages)
        current_turn = self.state.current_turn()
        if current_turn is not None:
            current_turn.tool_result_count = len(round_tool_results)
            current_turn.feedback_count = len(feedback_messages)
        self.after_tool_execute(result_count=len(round_tool_results), feedback_count=len(feedback_messages))
        return messages, round_tool_results, combined_content, len(feedback_messages)

    def build_tool_feedback_messages(self, round_tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        feedback_messages: list[dict[str, Any]] = []
        self.tool_results_history.extend(round_tool_results)
        execution_summary = _build_tool_failure_summary(self.tool_results_history)
        if execution_summary:
            feedback_messages.append({"role": "user", "content": execution_summary})
        repeat_warning = _detect_repeated_calls(round_tool_results, self.previous_call_signatures)
        if repeat_warning:
            feedback_messages.append({"role": "user", "content": repeat_warning})
        return feedback_messages

    def replace_tool_feedback_messages(
        self,
        messages: list[dict[str, Any]],
        feedback_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cleaned = [m for m in messages if not (
            m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and (
                "<TOOL_EXECUTION_SUMMARY>" in m["content"]
                or "<REPEATED_CALL_WARNING>" in m["content"]
            )
        )]
        cleaned.extend(feedback_messages)
        return cleaned

    async def run_post_tool_processing(
        self,
        *,
        context: Any,
        messages: list[dict[str, Any]],
        round_tool_results: list[dict[str, Any]],
        model_id: str | None = None,
        params: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> PostToolProcessingResult:
        user_request = _extract_latest_user_request(messages)
        post_context_messages = _build_post_tool_context_messages(messages)
        post_control_messages = build_post_tool_processing_messages(
            round_tool_results,
            user_request=user_request,
        )
        post_messages = [*post_context_messages, *post_control_messages]
        post_prompt_present = any(
            isinstance(message, dict)
            and isinstance(message.get("content"), str)
            and "<HARNESS_POST_TOOL_PROCESSING>" in message["content"]
            for message in post_messages
        )
        post_results_present = any(
            isinstance(message, dict)
            and isinstance(message.get("content"), str)
            and "Compact tool results JSON:" in message["content"]
            for message in post_messages
        )
        logger.info(
            "Harness post-tool request: node=%s base_messages=%s post_messages=%s round_results=%s tools=%s prompt_present=%s results_present=%s shape=%s tail=%s",
            self.state.node_id,
            len(messages or []),
            len(post_messages),
            len(round_tool_results or []),
            len(tool_schemas or []),
            post_prompt_present,
            post_results_present,
            _harness_message_debug_shape(post_messages),
            _harness_message_tail_preview(post_messages),
        )
        self.record_event("before_post_tool_model_call", result_count=len(round_tool_results))
        post_params: dict[str, Any] = {}
        post_params["_call_type"] = "harness_post_tool"
        result, raw_post_text, attempt_count = await self._invoke_post_tool_controller(
            context=context,
            post_messages=post_messages,
            model_id=model_id,
            params=post_params,
            tool_schemas=tool_schemas,
        )
        feedback_preview = (result.user_feedback or "")[:120].replace("\n", "\\n")
        raw_preview = (raw_post_text or "")[:300].replace("\n", "\\n")
        logger.info(
            "Harness post-tool parsed: node=%s round_results=%s action=%s status=%s feedback_len=%s next_len=%s raw_len=%s valid_json=%s attempts=%s feedback=%r raw_preview=%r",
            self.state.node_id,
            len(round_tool_results or []),
            result.flow_action,
            result.tool_status,
            len(result.user_feedback or ""),
            len(result.next_instruction or ""),
            len(raw_post_text or ""),
            bool(getattr(result, "valid_json", True)),
            attempt_count,
            feedback_preview,
            raw_preview,
        )
        self.record_event(
            "after_post_tool_model_response",
            flow_action=result.flow_action,
            tool_status=result.tool_status,
            feedback_len=len(result.user_feedback),
            raw_len=len(result.raw_text or ""),
        )
        self.apply_post_tool_result(result, messages=messages)
        return result

    async def _invoke_post_tool_controller(
        self,
        *,
        context: Any,
        post_messages: list[dict[str, Any]],
        model_id: str | None,
        params: dict[str, Any],
        tool_schemas: list[dict[str, Any]] | None,
    ) -> tuple[PostToolProcessingResult, str, int]:
        raw_post_text = ""
        post_tool_timeout = _get_post_tool_timeout_seconds()
        last_result = PostToolProcessingResult(
            flow_action="continue",
            tool_status="unknown",
            reason="post-tool response was not valid JSON",
            valid_json=False,
        )
        for attempt in range(1, _POST_TOOL_MAX_RETRIES + 1):
            attempt_messages = post_messages
            if attempt > 1 and last_result.reason:
                attempt_messages = [
                    *post_messages,
                    {
                        "role": "user",
                        "content": (
                            "Your previous control response was invalid: "
                            f"{last_result.reason}. Return exactly one strict JSON object now. "
                            "Do not call tools, do not use Markdown, and do not include prose."
                        ),
                    },
                ]
            try:
                raw_response = await asyncio.wait_for(
                    context.llm_manager.invoke(
                        attempt_messages,
                        model_id=model_id,
                        response_format={"type": "json_object"},
                        tools=tool_schemas,
                        tool_choice="none" if tool_schemas else None,
                        max_tokens=384,
                        temperature=0,
                        _max_attempts=1,
                        **params,
                    ),
                    timeout=post_tool_timeout,
                )
                raw_post_text = _stringify_post_tool_response(raw_response)
                last_result = parse_post_tool_processing_response(raw_post_text)
                if last_result.valid_json:
                    return last_result, raw_post_text, attempt
                last_result.reason = _describe_invalid_post_tool_response(raw_response, raw_post_text)
                logger.warning(
                    "Harness post-tool invalid JSON: node=%s attempt=%s/%s raw_len=%s raw_preview=%r",
                    self.state.node_id,
                    attempt,
                    _POST_TOOL_MAX_RETRIES,
                    len(raw_post_text or ""),
                    (raw_post_text or "")[:200].replace("\n", "\\n"),
                )
                await self._push_post_tool_retry(
                    error=last_result.reason,
                    attempt=attempt,
                    max_attempts=_POST_TOOL_MAX_RETRIES,
                )
            except asyncio.TimeoutError:
                raw_post_text = ""
                last_result = PostToolProcessingResult(
                    flow_action="continue",
                    tool_status="unknown",
                    reason=f"post-tool model call timed out after {post_tool_timeout:g}s",
                    raw_text="",
                    valid_json=False,
                )
                logger.warning(
                    "Harness post-tool call timed out: node=%s attempt=%s/%s timeout=%ss",
                    self.state.node_id,
                    attempt,
                    _POST_TOOL_MAX_RETRIES,
                    f"{post_tool_timeout:g}",
                )
                await self._push_post_tool_retry(
                    error=last_result.reason,
                    attempt=attempt,
                    max_attempts=_POST_TOOL_MAX_RETRIES,
                )
            except Exception as exc:
                raw_post_text = ""
                last_result = PostToolProcessingResult(
                    flow_action="continue",
                    tool_status="unknown",
                    reason=f"post-tool model call failed: {exc}",
                    raw_text="",
                    valid_json=False,
                )
                logger.warning(
                    "Harness post-tool call failed: node=%s attempt=%s/%s error=%s",
                    self.state.node_id,
                    attempt,
                    _POST_TOOL_MAX_RETRIES,
                    str(exc)[:300],
                )
                await self._push_post_tool_retry(
                    error=last_result.reason,
                    attempt=attempt,
                    max_attempts=_POST_TOOL_MAX_RETRIES,
                )
        return last_result, raw_post_text, _POST_TOOL_MAX_RETRIES

    async def _push_post_tool_retry(self, *, error: str, attempt: int, max_attempts: int) -> None:
        if attempt >= max_attempts:
            return
        try:
            from agentclaw.runtime.streaming import get_output_channel

            channel = get_output_channel()
            if not channel:
                return
            await channel.push_model_retry(
                error=error,
                model=self.state.model_id,
                node=self.state.node_id,
                attempt=attempt,
                max_attempts=max_attempts,
                delay=0.0,
                call_type="harness_post_tool",
            )
        except Exception as event_exc:
            logger.debug("推送后处理重试事件失败: %s", event_exc)

    def apply_post_tool_result(self, result: PostToolProcessingResult, *, messages: list[dict[str, Any]] | None = None) -> ContinueDecision:
        decision = self._apply_post_tool_decision(result)
        if result.flow_action == "continue":
            self.state.pending_continue_rounds = max(self.state.pending_continue_rounds, 1)
            self.state.missing_tool_continuation_count = 0
        else:
            self.state.pending_continue_rounds = 0
            self.state.missing_tool_continuation_count = 0
        if messages is not None:
            messages.append(self._build_post_tool_context_message(result))
        return decision

    def _build_post_tool_context_message(self, result: PostToolProcessingResult) -> dict[str, Any]:
        payload = {
            "action": result.flow_action,
            "status": result.tool_status,
            "feedback": result.user_feedback or "",
            "next": result.next_instruction or "",
            "valid_json": bool(getattr(result, "valid_json", True)),
        }
        if result.reason:
            payload["reason"] = result.reason[:120]
        content = (
            "<HARNESS_POST_TOOL_RESULT>\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n</HARNESS_POST_TOOL_RESULT>"
        )
        return {"role": "user", "content": content}

    def _apply_post_tool_decision(self, result: PostToolProcessingResult) -> ContinueDecision:
        reason = result.reason or "post-tool model decision"
        current_turn = self.state.current_turn()
        round_index = current_turn.turn_index if current_turn else None
        if result.flow_action == "finish":
            return self.on_finish(result.user_feedback, reason, round_index=round_index, tool_status=result.tool_status)
        if result.flow_action == "abort":
            return self.decide_abort(reason, tool_status=result.tool_status)
        if result.flow_action == "ask_user":
            return self.decide("finish", reason, needs_user_input=True, tool_status=result.tool_status)
        return self.decide_continue_for_tools(round_index=round_index or 0, tool_call_count=0)

    async def run_tool_turn(
        self,
        *,
        state: dict[str, Any],
        messages: list[dict[str, Any]],
        context: Any,
        tool_calls: list[Any],
        tool_exec_kwargs: dict[str, Any],
        batch_id: str,
        tool_schemas: list[dict[str, Any]] | None = None,
        text_content: str = "",
        reasoning_content: str = "",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, int, ContinueDecision]:
        tool_results = await self.execute_tools(
            tool_calls,
            state=state,
            context=context,
            tool_exec_kwargs=tool_exec_kwargs,
            batch_id=batch_id,
            tool_schemas=tool_schemas,
        )
        messages, round_tool_results, combined_content, feedback_count = await self.apply_tool_results(
            state=state,
            messages=messages,
            context=context,
            tool_calls=tool_calls,
            tool_results=tool_results,
            text_content=text_content,
            reasoning_content=reasoning_content,
        )
        rejected_result = next((result for result in tool_results if result.status == "rejected"), None)
        if rejected_result:
            decision = self.decide_abort(
                "user rejected tool confirmation",
                tool_name=rejected_result.tool_name,
                tool_call_id=rejected_result.call_id,
            )
            return messages, round_tool_results, combined_content, feedback_count, decision
        decision = self.decide_continue_for_tools(
            round_index=self.state.current_turn().turn_index if self.state.current_turn() else 0,
            tool_call_count=len(tool_calls),
        )
        return messages, round_tool_results, combined_content, feedback_count, decision

    async def execute_tools(
        self,
        tool_calls: list[Any],
        *,
        state: dict[str, Any],
        context: Any,
        tool_exec_kwargs: dict[str, Any],
        batch_id: str,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> list[ToolResultEnvelope]:
        envelopes = await self.tool_executor.execute_batch(
            tool_calls,
            state=state,
            context=context,
            tool_exec_kwargs=tool_exec_kwargs,
            batch_id=batch_id,
            tool_schemas=tool_schemas,
        )
        self.state.tool_results.extend(envelopes)
        return envelopes
