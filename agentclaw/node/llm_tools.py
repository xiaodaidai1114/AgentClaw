"""
LLMNode tool execution helpers.

Extracted from llm.py: tool execution, result classification,
batch conflict resolution, repeated-call detection, and related utilities.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from agentclaw.logger.config import get_logger
from agentclaw.node.llm_prompt import _get_tool_result_max_length

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool-name sets used by _analyze_tool_execution
# ---------------------------------------------------------------------------

_EDIT_TOOL_NAMES = {
    "write_file",
    "update_code",
    "replace_in_file",
    "replace_in_files",
    "rename_path",
    "apply_patch",
}

_VERIFICATION_TOOL_NAMES = {
    "read_file",
    "read_code",
    "syntax_check",
    "search_code",
    "python",
    "shell",
    "register_workflow_file",
    "validate_workflow_runtime",
}

_WORKFLOW_REGISTER_TOOL_NAME = "register_workflow_file"
_WORKFLOW_VALIDATE_TOOL_NAME = "validate_workflow_runtime"


# ---------------------------------------------------------------------------
# ToolExecutionOutcome
# ---------------------------------------------------------------------------

@dataclass
class ToolExecutionOutcome:
    """Structured tool execution outcome used across guard/streaming layers."""
    status: Literal["success", "failed", "unknown"]
    result: str


def _to_tool_execution_outcome(result: Any, explicit_status: Optional[str] = None) -> ToolExecutionOutcome:
    """Normalize arbitrary tool return payloads into a structured outcome."""
    result_str = str(result) if result is not None else ""
    status = _classify_tool_result_status(result_str, explicit_status=explicit_status)
    if status not in {"success", "failed", "unknown"}:
        status = "unknown"
    return ToolExecutionOutcome(
        status=status,  # type: ignore[arg-type]
        result=result_str,
    )


def _tool_event_status(outcome: ToolExecutionOutcome) -> str:
    """Map internal outcome status to SSE status enum used by frontend."""
    if outcome.status == "success":
        return "succeeded"
    if outcome.status == "failed":
        result_prefix = (outcome.result or "").lower()[:240]
        if "[timeout]" in result_prefix or "[tool_failed:timeout" in result_prefix:
            return "timeout"
        if "[rejected]" in result_prefix:
            return "cancelled"
        return "failed"
    return "unknown"


def _truncate_tool_result(result: str) -> str:
    """截断工具结果，避免超过模型上下文限制"""
    max_length = _get_tool_result_max_length()
    if max_length <= 0:
        return result
    if len(result) <= max_length:
        return result
    # 在行边界截断，避免截在行中间
    truncated = result[:max_length]
    last_newline = truncated.rfind('\n')
    if last_newline > max_length * 0.8:
        truncated = truncated[:last_newline]
    total_lines = result.count('\n') + 1
    shown_lines = truncated.count('\n') + 1
    return (
        f"{truncated}\n\n"
        f"... [truncated at line {shown_lines}/{total_lines}, "
        f"showing {len(truncated)}/{len(result)} chars. "
        f"Use read_file with offset/line_start to read remaining content.]"
    )


def _filter_preferred_tool_overlaps(
    tool_schemas: Optional[List[dict]],
    existing_tool_names: Optional[List[str]],
    preferred_tool_names: Optional[set[str]] = None,
) -> List[dict]:
    """过滤已由更优先来源提供的同名工具定义。"""
    if not tool_schemas:
        return []

    overlap_names = set(existing_tool_names or [])
    if preferred_tool_names is not None:
        overlap_names &= set(preferred_tool_names)

    if not overlap_names:
        return list(tool_schemas)

    return [
        schema
        for schema in tool_schemas
        if schema.get("function", {}).get("name") not in overlap_names
    ]


def _normalize_tool_arguments(tool_arguments: Any) -> dict[str, Any]:
    """Normalize tool arguments into a dict for signature/analysis."""
    if isinstance(tool_arguments, dict):
        return tool_arguments
    if isinstance(tool_arguments, str):
        stripped = tool_arguments.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


# ---------------------------------------------------------------------------
# Tool batch conflict resolution
# ---------------------------------------------------------------------------
_WRITE_TOOLS = frozenset({"write_code", "write_file"})
_WRITE_DEPENDENT_TOOLS = frozenset({"syntax_check"})


async def _execute_tool_batch_with_conflict_resolution(
    valid_tool_calls: list,
    *,
    state: dict,
    context: "WorkflowContext",
    tool_exec_kwargs: dict[str, Any],
) -> list:
    """Execute a batch of tool calls, auto-sequencing write→check conflicts.

    When ``write_code``/``write_file`` and ``syntax_check`` target the same
    path in one batch, the check will always fail because the file hasn't been
    written yet.  This helper splits the batch into two phases:

      Phase 1: writes + all non-conflicting tools  (parallel)
      Phase 2: conflicting checks                  (parallel, after phase 1)

    Results are returned in the **original** tool-call order so downstream
    processing (zip with valid_tool_calls) is unaffected.
    """
    from agentclaw.node.llm_skills import _execute_tool_with_skill_attestation

    if len(valid_tool_calls) <= 1:
        return list(await asyncio.gather(*(
            _execute_tool_with_skill_attestation(
                tc, state=state, context=context, tool_exec_kwargs=tool_exec_kwargs,
            ) for tc in valid_tool_calls
        ), return_exceptions=True))

    # Collect write target paths
    write_paths: set[str] = set()
    for tc in valid_tool_calls:
        if tc.name in _WRITE_TOOLS:
            p = _normalize_tool_arguments(getattr(tc, "arguments", {})).get("path", "")
            if p:
                write_paths.add(p)

    if not write_paths:
        # No writes → run everything in parallel (fast path)
        return list(await asyncio.gather(*(
            _execute_tool_with_skill_attestation(
                tc, state=state, context=context, tool_exec_kwargs=tool_exec_kwargs,
            ) for tc in valid_tool_calls
        ), return_exceptions=True))

    # Partition into phase-1 (writes + independent) and phase-2 (conflicting checks)
    phase1_indices: list[int] = []
    phase2_indices: list[int] = []
    for idx, tc in enumerate(valid_tool_calls):
        if tc.name in _WRITE_DEPENDENT_TOOLS:
            check_path = _normalize_tool_arguments(getattr(tc, "arguments", {})).get("path", "")
            if check_path and check_path in write_paths:
                phase2_indices.append(idx)
                continue
        phase1_indices.append(idx)

    if not phase2_indices:
        # No conflicts → parallel
        return list(await asyncio.gather(*(
            _execute_tool_with_skill_attestation(
                tc, state=state, context=context, tool_exec_kwargs=tool_exec_kwargs,
            ) for tc in valid_tool_calls
        ), return_exceptions=True))

    # Phase 1
    results: list[Any] = [None] * len(valid_tool_calls)
    phase1_results = await asyncio.gather(*(
        _execute_tool_with_skill_attestation(
            valid_tool_calls[i], state=state, context=context, tool_exec_kwargs=tool_exec_kwargs,
        ) for i in phase1_indices
    ), return_exceptions=True)
    for i, r in zip(phase1_indices, phase1_results):
        results[i] = r

    # Phase 2 (after writes have completed)
    phase2_results = await asyncio.gather(*(
        _execute_tool_with_skill_attestation(
            valid_tool_calls[i], state=state, context=context, tool_exec_kwargs=tool_exec_kwargs,
        ) for i in phase2_indices
    ), return_exceptions=True)
    for i, r in zip(phase2_indices, phase2_results):
        results[i] = r

    return results


def _extract_status_from_payload(payload: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Infer success/failed/unknown from structured payload.

    Returns:
      (status, failure_kind)
      - status: success | failed | unknown | None
      - failure_kind: timeout | cancelled | error | None
    """
    status_fields = ("status", "state", "result_status")
    status_map_success = {"success", "succeeded", "ok", "passed", "completed", "done", "approved"}
    status_map_timeout = {"timeout", "timed_out"}
    status_map_cancelled = {"cancelled", "canceled", "rejected", "denied", "interrupted"}
    status_map_failed = {"failed", "error", "tool_error"}

    for field in status_fields:
        if field in payload:
            raw = str(payload.get(field, "")).strip().lower()
            if raw in status_map_success:
                return "success", None
            if raw in status_map_timeout:
                return "failed", "timeout"
            if raw in status_map_cancelled:
                return "failed", "cancelled"
            if raw in status_map_failed:
                return "failed", "error"

    for bool_field in ("ok", "success", "passed"):
        if isinstance(payload.get(bool_field), bool):
            if payload[bool_field]:
                return "success", None
            return "failed", "error"

    http_status = payload.get("http_status")
    if isinstance(http_status, int) and http_status >= 400:
        return "failed", "error"

    if payload.get("error"):
        return "failed", "error"

    return None, None


def _classify_failure_kind_from_result(result: str) -> str:
    """Classify failure kind for guard severity decisions."""
    region = (result or "").lower()[:320]
    if "[tool_failed:timeout" in region or region.startswith("[timeout]"):
        return "timeout"
    if (
        "[tool_failed:rejected" in region
        or region.startswith("[rejected]")
        or "user rejected" in region
        or "已拒绝" in region
        or "取消" in region
    ):
        return "cancelled"
    return "error"


def _is_workflow_related_edit_result(result: str, tool_arguments: Optional[dict[str, Any]] = None) -> bool:
    """
    Best-effort detection for workflow-related edits.

    Prefer structured arguments (path/files) first; only fallback to output text.
    """
    args = tool_arguments or {}
    candidate_paths: list[str] = []
    for key in ("path", "file_path", "target", "source", "destination", "from", "to"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            candidate_paths.append(value.strip().lower())
    files_value = args.get("files")
    if isinstance(files_value, list):
        for value in files_value:
            if isinstance(value, str) and value.strip():
                candidate_paths.append(value.strip().lower())

    for path in candidate_paths:
        if "/workflows/" in path or path.startswith("workflows/"):
            return True
        if path.endswith("/server.py") or path == "server.py":
            return True
        if path.endswith("/workflows/__init__.py") or path == "workflows/__init__.py":
            return True

    # Structured argument payload can still signal workflow wiring.
    if args:
        try:
            args_region = json.dumps(args, ensure_ascii=False).lower()[:1200]
        except Exception:
            args_region = str(args).lower()[:1200]
        if "import workflows." in args_region or "workflow.publish(" in args_region:
            return True

    # Fallback: legacy outputs without structured args.
    region = (result or "").lower()[:2000]
    hints = (
        "written: workflows/",
        "updated: workflows/",
        "server.py",
        "import workflows.",
    )
    return any(hint in region for hint in hints)


def _classify_tool_result_status(result: str, explicit_status: Optional[str] = None) -> str:
    """
    Classify tool result status: success / failed / unknown.

    Priority:
    1) explicit structured status from execution chain
    2) structured result prefixes
    3) conservative fallback
    """
    normalized_explicit = str(explicit_status or "").strip().lower()
    if normalized_explicit in {"success", "failed", "unknown"}:
        return normalized_explicit

    normalized = (result or "")
    # 去掉首行环境信息前缀，暴露真正的状态标记
    if normalized.startswith("[Working Directory:"):
        parts = normalized.split("\n", 1)
        if len(parts) == 2:
            normalized = parts[1]
    normalized_lower = normalized.lower()

    # Structured JSON payload (for tools returning JSON with status field).
    stripped = normalized.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                payload_status, _ = _extract_status_from_payload(parsed)
                if payload_status in {"success", "failed", "unknown"}:
                    return payload_status
        except Exception:
            pass

    # Conservative fallback: only check leading region to avoid false positives.
    check_region = normalized_lower[:220]
    if "traceback (most recent call last):" in check_region:
        return "failed"
    if check_region.startswith("[error]") or check_region.startswith("error:"):
        return "failed"
    if check_region.startswith("[timeout]") or check_region.startswith("[rejected]"):
        return "failed"
    if check_region.startswith("[ok]") or check_region.startswith("[approved]"):
        return "success"
    # 没有明显错误标记就算成功 (SSE 状态用，不影响发给 LLM 的工具结果原文)
    return "success"


def _normalize_tool_history_entries(tool_results: list[Any]) -> list[dict[str, Any]]:
    """Normalize historical tool records to a common dict schema."""
    normalized_entries: list[dict[str, Any]] = []
    for idx, item in enumerate(tool_results):
        tool_name = ""
        result = ""
        explicit_status: Optional[str] = None
        tool_call_id = ""
        tool_arguments: dict[str, Any] = {}

        if isinstance(item, dict):
            tool_name = str(item.get("tool_name", "")).strip()
            result = str(item.get("result", ""))
            explicit_status = str(item.get("status", "")).strip().lower() or None
            tool_call_id = str(item.get("tool_call_id", "")).strip()
            tool_arguments = _normalize_tool_arguments(item.get("tool_arguments"))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            tool_name = str(item[0] or "").strip()
            result = str(item[1] or "")
            if len(item) >= 3:
                explicit_status = str(item[2] or "").strip().lower() or None
        else:
            tool_name = ""
            result = str(item)

        status = _classify_tool_result_status(result, explicit_status=explicit_status)
        call_signature = f"{tool_name.lower()}|__noargs__"
        if tool_call_id:
            call_signature = f"id:{tool_call_id}"
        elif tool_arguments:
            try:
                call_signature = f"{tool_name.lower()}|{json.dumps(tool_arguments, ensure_ascii=False, sort_keys=True)}"
            except Exception:
                call_signature = f"{tool_name.lower()}|{str(tool_arguments)}"

        normalized_entries.append({
            "index": idx,
            "tool_name": tool_name,
            "tool_name_lower": tool_name.lower(),
            "result": result,
            "status": status,
            "failure_kind": _classify_failure_kind_from_result(result) if status == "failed" else "none",
            "tool_call_id": tool_call_id,
            "tool_arguments": tool_arguments,
            "call_signature": call_signature,
        })
    return normalized_entries


def _analyze_tool_execution(tool_results: list[Any]) -> dict[str, Any]:
    """Analyze tool execution outcomes for guard/summary decisions."""
    outcomes = _normalize_tool_history_entries(tool_results)
    for o in outcomes:
        name_lower = o["tool_name_lower"]
        o["is_edit_action"] = name_lower in _EDIT_TOOL_NAMES
        o["is_verification"] = name_lower in _VERIFICATION_TOOL_NAMES

    def _unique_keep_order(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    failed_outcomes = [o for o in outcomes if o["status"] == "failed"]
    failed_tools = [o["tool_name"] for o in failed_outcomes]
    blocking_failed_outcomes = [o for o in failed_outcomes if o.get("failure_kind") != "cancelled"]
    edit_actions = [o for o in outcomes if o["is_edit_action"]]
    workflow_edit_actions = [
        o for o in edit_actions if _is_workflow_related_edit_result(
            o.get("result", ""),
            o.get("tool_arguments"),
        )
    ]
    failed_edit_tools = [o["tool_name"] for o in edit_actions if o["status"] == "failed"]
    success_edit_tools = [o["tool_name"] for o in edit_actions if o["status"] == "success"]
    last_edit = max(edit_actions, key=lambda x: x["index"]) if edit_actions else None

    register_calls = [o for o in outcomes if o["tool_name_lower"] == _WORKFLOW_REGISTER_TOOL_NAME]
    validate_calls = [o for o in outcomes if o["tool_name_lower"] == _WORKFLOW_VALIDATE_TOOL_NAME]
    register_success = any(o["status"] == "success" for o in register_calls)
    validate_success = any(o["status"] == "success" for o in validate_calls)
    workflow_runtime_checks_required = bool(workflow_edit_actions)
    workflow_runtime_checks_passed = (not workflow_runtime_checks_required) or (register_success and validate_success)
    unresolved_failed_outcomes: list[dict[str, Any]] = []
    for failed in blocking_failed_outcomes:
        resolved_by_retry = any(
            later["index"] > failed["index"]
            and later["status"] == "success"
            and later.get("call_signature") == failed.get("call_signature")
            for later in outcomes
        )
        if not resolved_by_retry:
            unresolved_failed_outcomes.append(failed)
    unresolved_failed_tool_names = [o["tool_name"] for o in unresolved_failed_outcomes]

    last_edit_index = max((o["index"] for o in edit_actions), default=-1)
    verification_after_last_edit = [
        o["tool_name"]
        for o in outcomes
        if o["index"] > last_edit_index and o["is_verification"] and o["status"] == "success"
    ]
    post_edit_verified = (not edit_actions) or bool(verification_after_last_edit)

    return {
        "total": len(outcomes),
        "success_count": sum(1 for o in outcomes if o["status"] == "success"),
        "failed_count": sum(1 for o in outcomes if o["status"] == "failed"),
        "blocking_failed_count": len(blocking_failed_outcomes),
        "failed_tool_names": _unique_keep_order(failed_tools),
        "unresolved_failed_tool_names": _unique_keep_order(unresolved_failed_tool_names),
        "unresolved_failed_count": len(_unique_keep_order(unresolved_failed_tool_names)),
        "has_edit_actions": bool(edit_actions),
        "edit_actions_count": len(edit_actions),
        "workflow_edit_actions_count": len(workflow_edit_actions),
        "edit_success_count": len(success_edit_tools),
        "edit_failed_count": len(failed_edit_tools),
        "failed_edit_tool_names": _unique_keep_order(failed_edit_tools),
        "last_edit_tool_name": last_edit["tool_name"] if last_edit else "",
        "last_edit_status": last_edit["status"] if last_edit else "",
        "post_edit_verification_steps": _unique_keep_order(verification_after_last_edit),
        "verification_steps_detected": len(verification_after_last_edit),
        "post_edit_verified": post_edit_verified,
        "workflow_register_called": bool(register_calls),
        "workflow_validate_called": bool(validate_calls),
        "workflow_register_success": register_success,
        "workflow_validate_success": validate_success,
        "workflow_runtime_checks_required": workflow_runtime_checks_required,
        "workflow_runtime_checks_passed": workflow_runtime_checks_passed,
    }


def _build_tool_failure_summary(tool_results: list[Any]) -> str | None:
    """
    构建工具调用失败汇总消息

    Args:
        tool_results: [(tool_name, result_str), ...] 工具调用结果列表

    Returns:
        失败汇总消息，如果没有失败则返回 None
    """
    if not tool_results:
        return None

    analysis = _analyze_tool_execution(tool_results)
    has_failures = analysis["blocking_failed_count"] > 0
    has_unresolved_failures = analysis["unresolved_failed_count"] > 0
    has_edit_actions = analysis["has_edit_actions"]
    if (
        not has_failures
        and not has_unresolved_failures
        and (not has_edit_actions or analysis["post_edit_verified"])
        and (not analysis["workflow_runtime_checks_required"] or analysis["workflow_runtime_checks_passed"])
    ):
        return None

    # 构建内部执行汇总（用于后续推理，不应原样输出给用户）
    summary_lines = [
        "<TOOL_EXECUTION_SUMMARY>",
        (
        "total={total} success={success} failed={failed} unresolved_failed={unresolved_failed} "
        "edit_attempts={edit_attempts} edit_failed={edit_failed} "
        "verification_steps_detected={verify_count} post_edit_verified={verified} "
        "workflow_edits={workflow_edits} workflow_register_success={register_ok} workflow_validate_success={validate_ok}"
    ).format(
        total=analysis["total"],
        success=analysis["success_count"],
        failed=analysis["failed_count"],
        unresolved_failed=analysis["unresolved_failed_count"],
        edit_attempts=analysis["edit_actions_count"],
        edit_failed=analysis["edit_failed_count"],
        verify_count=analysis["verification_steps_detected"],
        verified=str(analysis["post_edit_verified"]).lower(),
        workflow_edits=analysis["workflow_edit_actions_count"],
        register_ok=str(analysis["workflow_register_success"]).lower(),
        validate_ok=str(analysis["workflow_validate_success"]).lower(),
    ),
    f"last_edit_status={analysis['last_edit_status']} last_edit_tool={analysis['last_edit_tool_name']}",
]

    for tool_name in analysis["failed_tool_names"]:
        summary_lines.append(f"failed_tool: {tool_name}")
    for tool_name in analysis["unresolved_failed_tool_names"]:
        summary_lines.append(f"unresolved_failed_tool: {tool_name}")

    for tool_name in analysis["failed_edit_tool_names"]:
        summary_lines.append(f"failed_edit_tool: {tool_name}")

    if analysis["has_edit_actions"] and not analysis["post_edit_verified"]:
        summary_lines.append(
            "post_edit_guard: missing successful verification after last edit; do not claim task completed"
        )
        summary_lines.append(
            "repair_hint: run syntax_check + py_compile now; if failing, patch offending region first via replace_in_file/update_code before full rewrite"
        )
    if analysis["workflow_runtime_checks_required"] and not analysis["workflow_runtime_checks_passed"]:
        summary_lines.append(
            "workflow_runtime_guard: workflow edits detected; registration/runtime evidence is incomplete. Prefer reporting partial with missing checks and next validation steps."
        )

    summary_lines.extend([
        "INTERNAL_ONLY: Do not quote this block verbatim to user.",
        "User response should be concise: what succeeded, what failed, next action.",
        "</TOOL_EXECUTION_SUMMARY>",
    ])

    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# Repeated tool-call detection
# ---------------------------------------------------------------------------

def _build_call_signature(tool_name: str, tool_arguments: Any) -> str:
    """Build a deterministic signature for a tool call (name + sorted args)."""
    name = (tool_name or "").strip().lower()
    if not tool_arguments:
        return f"{name}|__noargs__"
    if isinstance(tool_arguments, str):
        try:
            tool_arguments = json.loads(tool_arguments)
        except Exception:
            return f"{name}|{tool_arguments}"
    try:
        return f"{name}|{json.dumps(tool_arguments, ensure_ascii=False, sort_keys=True)}"
    except Exception:
        return f"{name}|{str(tool_arguments)}"


def _detect_repeated_calls(
    round_tool_results: list[dict[str, Any]],
    previous_signatures: list[str],
) -> Optional[str]:
    """
    Detect if the current round's calls are identical to the previous round.

    Returns an injection message if repetition is detected, else None.
    Updates *previous_signatures* in-place for the next round.
    """
    current_sigs = []
    for r in round_tool_results:
        sig = _build_call_signature(r.get("tool_name", ""), r.get("tool_arguments"))
        current_sigs.append(sig)

    if not current_sigs:
        previous_signatures.clear()
        return None

    current_key = "\n".join(sorted(current_sigs))
    prev_key = "\n".join(sorted(previous_signatures)) if previous_signatures else ""

    # Update for next comparison
    previous_signatures.clear()
    previous_signatures.extend(current_sigs)

    if current_key == prev_key:
        tool_names = list(dict.fromkeys(r.get("tool_name", "") for r in round_tool_results))
        return (
            "<REPEATED_CALL_WARNING>\n"
            f"You called the same tool(s) ({', '.join(tool_names)}) with identical arguments as the previous round. "
            "Repeating the exact same call will produce the exact same result.\n"
            "STOP repeating. Instead:\n"
            "1. If the user's request is missing required information, ASK the user for clarification.\n"
            "2. If you need to try a different approach, change the parameters or use a different tool.\n"
            "3. If you cannot proceed, explain the blocker to the user and stop calling tools.\n"
            "</REPEATED_CALL_WARNING>"
        )
    return None


def _dedupe_tool_schemas(tool_schemas: Optional[List[dict]], node_id: str) -> Optional[List[dict]]:
    """
    按 function.name 去重工具定义，避免模型侧报 Duplicate function definition。

    保留最后一个同名定义（通常是内置工具注入后的定义），
    以便内置安全工具 schema 覆盖外部同名定义。
    """
    if not tool_schemas:
        return tool_schemas

    seen_names: set[str] = set()
    deduped_reversed: List[dict] = []
    duplicate_names: List[str] = []

    for schema in reversed(tool_schemas):
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = function.get("name")
        if not name:
            deduped_reversed.append(schema)
            continue

        if name in seen_names:
            duplicate_names.append(name)
            continue

        seen_names.add(name)
        deduped_reversed.append(schema)

    deduped = list(reversed(deduped_reversed))
    deduped.sort(key=_tool_schema_sort_key)
    if duplicate_names:
        # 日志里输出去重后的唯一重名列表，便于排查来源
        dup_unique = sorted(set(duplicate_names))
        logger.warning(f"节点 {node_id} 检测到重复工具定义，已自动去重: {dup_unique}")

    return deduped


def _tool_schema_sort_key(schema: dict) -> tuple[int, str]:
    if not isinstance(schema, dict):
        return (1, "")
    function = schema.get("function", {})
    name = function.get("name", "") if isinstance(function, dict) else ""
    return (0 if name else 1, str(name))


async def _execute_tool(
    tool_name: str,
    tool_arguments: dict,
    state: dict,
    workflow_id: Optional[str] = None,
    toolkit: Optional[Any] = None,
    mcp_manager: Optional[Any] = None,
    mcp_tool_names: Optional[List[str]] = None,
    planning_mcp_manager: Optional[Any] = None,
    planning_mcp_tool_names: Optional[List[str]] = None,
    download_mcp_manager: Optional[Any] = None,
    download_mcp_tool_names: Optional[List[str]] = None,
    browser_mcp_manager: Optional[Any] = None,
    browser_mcp_tool_names: Optional[List[str]] = None,
    search_mcp_manager: Optional[Any] = None,
    search_mcp_tool_names: Optional[List[str]] = None,
    computer_mcp_manager: Optional[Any] = None,
    computer_mcp_tool_names: Optional[List[str]] = None,
    coding_mcp_manager: Optional[Any] = None,
    coding_mcp_tool_names: Optional[List[str]] = None,
    published_mcp_tools: Optional[Dict[str, Any]] = None,
    published_mcp_tool_names: Optional[List[str]] = None,
) -> ToolExecutionOutcome:
    """
    执行工具调用，自动选择 MCP 或 toolkit
    """
    def _wrap_outcome(raw_result: Any, explicit_status: Optional[str] = None) -> ToolExecutionOutcome:
        return _to_tool_execution_outcome(raw_result, explicit_status=explicit_status)

    # 检查工具名称是否有效
    if not tool_name or not tool_name.strip():
        return _wrap_outcome("[Error] Empty tool name", explicit_status="failed")

    # 确保 arguments 是 dict
    if isinstance(tool_arguments, str):
        tool_arguments = tool_arguments.strip()
        if not tool_arguments:
            tool_arguments = {}
        else:
            try:
                tool_arguments = json.loads(tool_arguments)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON arguments for tool '{tool_name}': {tool_arguments[:100]}")
                return _wrap_outcome(
                    f"[Error] Invalid JSON arguments: {tool_arguments[:50]}...",
                    explicit_status="failed",
                )

    if not isinstance(tool_arguments, dict):
        tool_arguments = {}

    if tool_name in {"update_memory", "compress_memory"} and workflow_id and not tool_arguments.get("workflow_id"):
        tool_arguments = dict(tool_arguments)
        tool_arguments["workflow_id"] = workflow_id

    # confirm_action 已废弃：由 Harness 工具确认流程统一接管。
    if tool_name == "confirm_action":
        return _wrap_outcome("[DEPRECATED] confirm_action is deprecated. Tool confirmation is handled automatically by the Harness risk confirmation flow.", explicit_status="failed")

    # 检查是否是 Planning 工具
    if planning_mcp_manager and planning_mcp_tool_names and tool_name in planning_mcp_tool_names:
        try:
            result = await planning_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Planning tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 Download 工具
    if download_mcp_manager and download_mcp_tool_names and tool_name in download_mcp_tool_names:
        try:
            result = await download_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Download tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 Browser 工具
    if browser_mcp_manager and browser_mcp_tool_names and tool_name in browser_mcp_tool_names:
        try:
            result = await browser_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Browser tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 Search 工具
    if search_mcp_manager and search_mcp_tool_names and tool_name in search_mcp_tool_names:
        try:
            result = await search_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Search tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 Computer 工具
    if computer_mcp_manager and computer_mcp_tool_names and tool_name in computer_mcp_tool_names:
        try:
            result = await computer_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Computer tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 Coding 工具
    if coding_mcp_manager and coding_mcp_tool_names and tool_name in coding_mcp_tool_names:
        try:
            result = await coding_mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"Coding tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是 MCP 工具
    if mcp_manager and mcp_tool_names and tool_name in mcp_tool_names:
        try:
            result = await mcp_manager.call_tool(tool_name, tool_arguments)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(f"MCP tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 检查是否是框架内发布的 MCP 工具（函数 / ToolKit 直发）
    if published_mcp_tools and published_mcp_tool_names and tool_name in published_mcp_tool_names:
        try:
            published_tool = published_mcp_tools.get(tool_name)
            if not published_tool:
                return _wrap_outcome(f"[ERROR] Published MCP tool '{tool_name}' is not registered", explicit_status="failed")
            result = await published_tool.call(tool_arguments)
            if isinstance(result, str):
                return _wrap_outcome(result)
            return _wrap_outcome(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            logger.error(f"Published MCP tool '{tool_name}' execution failed: {e}")
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    # 使用普通 toolkit
    if toolkit:
        try:
            result = await toolkit.execute(tool_name, tool_arguments, state)
            return _wrap_outcome(result)
        except Exception as e:
            logger.error(
                "Toolkit tool '%s' execution failed: %s: %r",
                tool_name,
                type(e).__name__,
                e,
            )
            return _wrap_outcome(f"[ERROR] Tool '{tool_name}' failed: {e}", explicit_status="failed")

    return _wrap_outcome(f"[ERROR] Tool '{tool_name}' not found in any toolkit", explicit_status="failed")


async def _execute_confirm_action(arguments: dict, state: dict) -> str:
    """
    执行 confirm_action 内置工具

    1. 创建 PendingConfirmation
    2. 通过 OutputChannel 推送 confirm_request 事件
    3. 等待用户确认（最多 5 分钟）
    4. 返回结果给模型（如果需要 sudo，将密码存储到 state）
    """
    import uuid

    action = arguments.get("action", "Unknown action")
    description = arguments.get("description", "")
    require_sudo = arguments.get("require_sudo", False)
    confirm_id = str(uuid.uuid4())

    # 获取 OutputChannel
    from agentclaw.runtime.streaming.context import get_output_channel
    channel = get_output_channel()

    # 创建确认请求
    from agentclaw.api.services.confirm_service import get_confirmation_manager
    manager = get_confirmation_manager()
    confirmation = manager.create(confirm_id, action, description, require_sudo)

    # 推送确认事件到前端
    if channel:
        await channel.push_confirm_request(
            confirm_id=confirm_id,
            action=action,
            description=description,
            require_sudo=require_sudo,
        )
        logger.info(f"confirm_action: 已推送确认请求 {confirm_id}: {action} (sudo={require_sudo})")
    else:
        logger.warning(f"confirm_action: 无 OutputChannel，自动拒绝: {action}")
        manager.cleanup(confirm_id)
        return f"[REJECTED] No output channel available. Action '{action}' was not executed."

    # 等待用户确认（最多 5 分钟）
    try:
        await asyncio.wait_for(confirmation.event.wait(), timeout=300.0)
    except asyncio.TimeoutError:
        manager.cleanup(confirm_id)
        return f"[TIMEOUT] User did not respond within 5 minutes. Action '{action}' was not executed."

    # 获取结果
    approved = confirmation.result
    sudo_password = confirmation.sudo_password
    manager.cleanup(confirm_id)

    if approved:
        if require_sudo:
            if sudo_password:
                # 将密码写入安全临时文件，供 skill-tools 的 execute_sudo_command 使用
                import pathlib
                import tempfile
                sudo_file = pathlib.Path(tempfile.gettempdir()) / ".agentclaw_sudo"
                try:
                    sudo_file.write_text(sudo_password, encoding="utf-8")
                    sudo_file.chmod(0o600)
                except Exception as e:
                    logger.error(f"confirm_action: 写入 sudo 临时文件失败: {e}")
                    return f"[ERROR] Failed to store sudo credential: {e}"
                return f"[APPROVED] User approved: {action}. Sudo password received. You can now use execute_sudo_command tool."
            else:
                # 需要 sudo 但没有收到密码
                return f"[ERROR] User approved but sudo password was not provided. Frontend may not support sudo password input yet."
        else:
            return f"[APPROVED] User approved: {action}. You may now proceed with the action."
    else:
        return f"[REJECTED] User rejected: {action}. Do NOT execute this action. Inform the user and ask for alternatives."
