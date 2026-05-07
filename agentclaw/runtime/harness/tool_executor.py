"""Tool execution adapter for agentic harness runs."""

from __future__ import annotations

from typing import Any
import asyncio
import pathlib
import tempfile
import uuid

from agentclaw.node.llm_tools import (
    ToolExecutionOutcome,
    _execute_tool_batch_with_conflict_resolution,
    _to_tool_execution_outcome,
    _tool_event_status,
    _truncate_tool_result,
)
from agentclaw.runtime.harness.tool_call import ToolCallEnvelope, preprocess_tool_call
from agentclaw.runtime.harness.tool_result import ToolResultEnvelope
from agentclaw.runtime.streaming import get_output_channel


class HarnessToolExecutor:
    """Executes model tool calls and normalizes outputs for model + trace use."""

    def __init__(self, *, node_id: str):
        self.node_id = node_id

    async def execute_batch(
        self,
        tool_calls: list[Any],
        *,
        state: dict[str, Any],
        context: Any,
        tool_exec_kwargs: dict[str, Any],
        batch_id: str,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> list[ToolResultEnvelope]:
        channel = get_output_channel()
        schema_by_name = _schema_by_tool_name(tool_schemas)
        allowed_names = set(schema_by_name) if schema_by_name else None
        preprocessed = [
            preprocess_tool_call(
                tool_call,
                source_round=_round_from_batch_id(batch_id),
                allowed_tool_names=allowed_names,
                tool_schema=schema_by_name.get(str(getattr(tool_call, "name", "") or "").strip()) if schema_by_name else None,
            )
            for tool_call in tool_calls
        ]
        envelopes: list[ToolResultEnvelope | None] = [None] * len(preprocessed)
        executable_calls: list[Any] = []
        executable_indexes: list[int] = []

        for index, call in enumerate(preprocessed):
            if not call.valid:
                envelope = self._invalid_call_result(call)
                envelopes[index] = envelope
                if channel:
                    await self._push_tool_result(channel, call, envelope, batch_id)
                continue

            if _requires_user_confirmation(call, context):
                confirmation_result = await self._confirm_tool_call(call, state=state, context=context)
                if confirmation_result is not None:
                    envelopes[index] = confirmation_result
                    if channel:
                        await self._push_tool_result(channel, call, confirmation_result, batch_id)
                    continue

            runtime_call = _RuntimeToolCall(call)
            executable_calls.append(runtime_call)
            executable_indexes.append(index)
            if channel:
                await channel.push_tool_start(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_arguments=call.arguments_json,
                    batch_id=batch_id,
                    node=self.node_id,
                )

        if executable_calls:
            try:
                raw_results = await _execute_tool_batch_with_conflict_resolution(
                    executable_calls,
                    state=state,
                    context=context,
                    tool_exec_kwargs=tool_exec_kwargs,
                )
            except Exception as exc:
                raw_results = [exc for _ in executable_calls]
            if len(raw_results) < len(executable_calls):
                raw_results = list(raw_results) + [RuntimeError("Tool execution did not return a result") for _ in range(len(executable_calls) - len(raw_results))]
            for index, runtime_call, raw in zip(executable_indexes, executable_calls, raw_results):
                envelope = self._normalize_result(runtime_call, raw, preprocessed[index])
                envelopes[index] = envelope
                if channel:
                    await self._push_tool_result(channel, preprocessed[index], envelope, batch_id)

        return [envelope or self._missing_result(preprocessed[index]) for index, envelope in enumerate(envelopes)]


    async def _confirm_tool_call(self, call: ToolCallEnvelope, *, state: dict[str, Any], context: Any) -> ToolResultEnvelope | None:
        if getattr(context, "disable_confirm_tool", False):
            return None

        channel = get_output_channel()
        if not channel:
            return self._confirmation_result(
                call,
                status="rejected",
                message=f"[REJECTED] No output channel available. Tool '{call.name}' was not executed.",
            )

        confirm_id = str(uuid.uuid4())
        action = f"Execute tool: {call.name}"
        description = self._confirmation_description(call)
        require_sudo = self._requires_sudo(call)

        from agentclaw.api.services.confirm_service import get_confirmation_manager
        manager = get_confirmation_manager()
        confirmation = manager.create(confirm_id, action, description, require_sudo)
        await channel.push_confirm_request(
            confirm_id=confirm_id,
            action=action,
            description=description,
            require_sudo=require_sudo,
            node=self.node_id,
        )

        if not getattr(channel, "stream_mode", False):
            return self._confirmation_result(
                call,
                status="confirmation_required",
                message=f"[CONFIRMATION_REQUIRED] Tool '{call.name}' requires confirmation before execution. Confirm with POST /api/confirm/{confirm_id}.",
                retryable=True,
            )

        try:
            await asyncio.wait_for(confirmation.event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            manager.cleanup(confirm_id)
            return self._confirmation_result(
                call,
                status="timeout",
                message=f"[TIMEOUT] User did not respond within 5 minutes. Tool '{call.name}' was not executed.",
            )

        approved = confirmation.result
        sudo_password = confirmation.sudo_password
        manager.cleanup(confirm_id)
        if not approved:
            return self._confirmation_result(
                call,
                status="rejected",
                message=f"[REJECTED] User rejected tool '{call.name}'. Do not retry the same action without changes.",
            )
        if require_sudo:
            if not sudo_password:
                return self._confirmation_result(
                    call,
                    status="failed",
                    message=f"[ERROR] User approved tool '{call.name}' but sudo password was not provided.",
                )
            credential_error = self._store_sudo_password(sudo_password)
            if credential_error:
                return self._confirmation_result(
                    call,
                    status="failed",
                    message=f"[ERROR] Failed to store sudo credential for tool '{call.name}': {credential_error}",
                )
            state["__sudo_password__"] = sudo_password
        return None


    def _confirmation_result(self, call: ToolCallEnvelope, *, status: str, message: str, retryable: bool | None = None) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            call_id=call.id,
            tool_name=call.name,
            success=False,
            summary=message,
            model_content=message,
            status=status,
            raw_input=call.raw_arguments if isinstance(call.raw_arguments, str) else call.arguments_json,
            model_arguments=call.arguments_json,
            raw_output=message,
            error=message,
            diagnostic="The harness blocked this tool before execution because user confirmation is required or was not approved.",
            retryable=(status == "timeout") if retryable is None else retryable,
            risk_level=call.risk_level,
            tool_risk_level=call.tool_risk_level,
            model_risk_level=call.model_risk_level,
            requires_confirmation=call.requires_confirmation,
        )

    def _missing_result(self, call: ToolCallEnvelope) -> ToolResultEnvelope:
        message = f"[ERROR] Tool '{call.name}' did not produce a result."
        return ToolResultEnvelope(
            call_id=call.id,
            tool_name=call.name or "<empty>",
            success=False,
            summary=message,
            model_content=message,
            status="failed",
            raw_input=call.raw_arguments if isinstance(call.raw_arguments, str) else call.arguments_json,
            model_arguments=call.arguments_json,
            raw_output=message,
            error=message,
            diagnostic="Harness inserted a missing tool_result compensation message to keep the conversation valid.",
            retryable=True,
            risk_level=call.risk_level,
            tool_risk_level=call.tool_risk_level,
            model_risk_level=call.model_risk_level,
            requires_confirmation=call.requires_confirmation,
        )

    @staticmethod
    def _store_sudo_password(sudo_password: str) -> str | None:
        sudo_file = pathlib.Path(tempfile.gettempdir()) / ".agentclaw_sudo"
        try:
            sudo_file.write_text(sudo_password, encoding="utf-8")
            sudo_file.chmod(0o600)
        except Exception as exc:
            return str(exc)
        return None

    @staticmethod
    def _confirmation_description(call: ToolCallEnvelope) -> str:
        args_preview = call.arguments_json
        if len(args_preview) > 1000:
            args_preview = args_preview[:1000] + "..."
        return (
            f"Tool '{call.name}' is marked {call.risk_level} risk "
            f"(tool={call.tool_risk_level}, model={call.model_risk_level}) "
            f"and requires confirmation before execution. Arguments: {args_preview}"
        )

    @staticmethod
    def _requires_sudo(call: ToolCallEnvelope) -> bool:
        if call.name == "execute_sudo_command":
            return True
        text = " ".join(str(value).lower() for value in call.arguments.values() if isinstance(value, str))
        return "sudo" in text

    async def _push_tool_result(self, channel: Any, call: ToolCallEnvelope, envelope: ToolResultEnvelope, batch_id: str) -> None:
        outcome = ToolExecutionOutcome(
            result=envelope.raw_output if isinstance(envelope.raw_output, str) else envelope.model_content,
            status=envelope.status,
        )
        await channel.push_tool(
            tool_call_id=call.id,
            tool_name=call.name,
            tool_arguments=call.arguments_json,
            tool_result=envelope.raw_output if envelope.raw_output is not None else envelope.model_content,
            tool_status=_tool_event_status(outcome),
            batch_id=batch_id,
            node=self.node_id,
        )

    def _invalid_call_result(self, call: ToolCallEnvelope) -> ToolResultEnvelope:
        message = "; ".join(call.validation_errors) or "Invalid tool call"
        model_content = f"[Error] Invalid tool call for {call.name or '<empty>'}: {message}"
        return ToolResultEnvelope(
            call_id=call.id,
            tool_name=call.name or "<empty>",
            success=False,
            summary=model_content,
            model_content=model_content,
            status="failed",
            raw_input=call.raw_arguments if isinstance(call.raw_arguments, str) else call.arguments_json,
            model_arguments=call.arguments_json,
            raw_output=model_content,
            error=model_content,
            diagnostic="The model produced an invalid tool call. Correct the tool name or arguments before retrying.",
            retryable=True,
            risk_level=call.risk_level,
            tool_risk_level=call.tool_risk_level,
            model_risk_level=call.model_risk_level,
            requires_confirmation=call.requires_confirmation,
        )

    def _normalize_result(self, tool_call: Any, raw: Any, call: ToolCallEnvelope | None = None) -> ToolResultEnvelope:
        if isinstance(raw, Exception):
            outcome = _to_tool_execution_outcome(f"[ERROR] {raw}", explicit_status="failed")
        elif isinstance(raw, ToolExecutionOutcome):
            outcome = raw
        else:
            outcome = _to_tool_execution_outcome(raw)

        tool_result_str = outcome.result
        if outcome.status == "failed" and tool_call.arguments:
            args_preview = tool_call.arguments[:500] if len(tool_call.arguments) > 500 else tool_call.arguments
            tool_result_str = f"{tool_result_str}\n\n[Your call arguments: {args_preview}]"

        model_content = _truncate_tool_result(tool_result_str)
        success = outcome.status not in {"failed", "error"}
        summary = self._build_summary(tool_call.name, tool_result_str, success)
        return ToolResultEnvelope(
            call_id=tool_call.id,
            tool_name=tool_call.name,
            success=success,
            summary=summary,
            model_content=model_content,
            status=outcome.status,
            raw_input=call.raw_arguments if call else tool_call.arguments,
            model_arguments=call.arguments_json if call else tool_call.arguments,
            raw_output=tool_result_str,
            error=None if success else tool_result_str,
            diagnostic=None if success else "Tool execution failed; inspect the error and call arguments before retrying.",
            retryable=not success,
            risk_level=call.risk_level if call else "low",
            tool_risk_level=call.tool_risk_level if call else "low",
            model_risk_level=call.model_risk_level if call else "low",
            requires_confirmation=call.requires_confirmation if call else False,
        )

    @staticmethod
    def _build_summary(tool_name: str, result: str, success: bool) -> str:
        compact = " ".join(str(result or "").split())[:160]
        prefix = "succeeded" if success else "failed"
        return f"{tool_name} {prefix}: {compact}"


class _RuntimeToolCall:
    """Adapter exposing normalized arguments to legacy tool execution helpers."""

    def __init__(self, envelope: ToolCallEnvelope):
        self.id = envelope.id
        self.name = envelope.name
        self.arguments = envelope.arguments_json


_RISK_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _requires_user_confirmation(call: ToolCallEnvelope, context: Any) -> bool:
    level = str(getattr(context, "tool_confirmation_level", "") or "").strip().lower()
    if not level:
        level = "high" if getattr(context, "tool_confirmation_required", False) else "off"
    if level in {"off", "none", "false", "disabled"}:
        return False
    threshold = _RISK_RANK.get(level)
    if threshold is None:
        threshold = _RISK_RANK["high"] if getattr(context, "tool_confirmation_required", False) else 999
    return _RISK_RANK.get(call.risk_level, 0) >= threshold


def _round_from_batch_id(batch_id: str) -> int:
    try:
        if batch_id.startswith("round-"):
            return int(batch_id.split("-", 1)[1])
    except Exception:
        pass
    return 0


def _schema_by_tool_name(tool_schemas: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for schema in tool_schemas or []:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function", {})
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", "") or "").strip()
        if name:
            result[name] = schema
    return result
