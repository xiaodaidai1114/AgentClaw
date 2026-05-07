"""
LLM Skill attestation utilities.

Functions for building skill trees, tracking skill-read attestations per session,
and gating MCP tool execution behind required skill reads.
"""

from __future__ import annotations

import os
import time
import json
from collections import OrderedDict
from typing import Any, Optional, Literal, TYPE_CHECKING

from agentclaw.logger.config import get_logger
from agentclaw.node.llm_tools import (
    ToolExecutionOutcome,
    _execute_tool,
    _normalize_tool_arguments,
    _to_tool_execution_outcome,
)

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


def _build_skills_tree(matched_skills: list) -> str:
    """生成已加载 skills 的路径、脚本和参考文档列表"""
    from pathlib import Path
    if not matched_skills:
        return ""
    parts: list[str] = []
    for skill in matched_skills:
        if not skill.path or not skill.path.exists():
            continue
        entry = f"- {skill.name}: {skill.path}"
        scripts_dir = skill.path / "scripts"
        if scripts_dir.is_dir():
            scripts = sorted(f.name for f in scripts_dir.iterdir() if f.is_file())
            if scripts:
                entry += f"\n  scripts: {', '.join(scripts)}"
        refs_dir = skill.path / "references"
        if refs_dir.is_dir():
            refs = sorted(f.name for f in refs_dir.iterdir() if f.is_file() and f.suffix == ".md")
            if refs:
                entry += f"\n  references: {', '.join(refs)}"
        parts.append(entry)
    return "\n".join(parts) if parts else ""


_SKILL_ATTESTATION_MAX_SESSIONS = int(os.getenv("SKILL_ATTESTATION_MAX_SESSIONS", "512"))
_SKILL_ATTESTATION_TTL_SECONDS = int(os.getenv("SKILL_ATTESTATION_TTL_SECONDS", "43200"))
_SKILL_ATTESTATION_BY_SESSION: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

_SKILL_REFERENCE_DIAGNOSTICS_KEY = "__skill_reference_diagnostics__"
_AGENT_CREATOR_NL2SQL_REFERENCE = "agent_creator/references/nl2sql.md"
_REFERENCE_SENSITIVE_WRITE_TOOLS = {"write_code", "write_file", "update_code", "replace_in_file"}
_SQL_REPORT_TASK_TERMS = (
    "sql",
    "mysql",
    "postgres",
    "sqlite",
    "database",
    "schema",
    "table",
    "column",
    "analytics",
    "dashboard",
    "report",
    "audit",
    "log",
    "数据库",
    "表",
    "字段",
    "报表",
    "报告",
    "审计",
    "日志",
)


def _ensure_skill_reference_diagnostics(state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = state.get(_SKILL_REFERENCE_DIAGNOSTICS_KEY)
    if not isinstance(diagnostics, dict):
        diagnostics = {
            "read_skills": [],
            "read_references": [],
            "write_before_pattern_reference_warned": False,
        }
        state[_SKILL_REFERENCE_DIAGNOSTICS_KEY] = diagnostics
    diagnostics.setdefault("read_skills", [])
    diagnostics.setdefault("read_references", [])
    diagnostics.setdefault("write_before_pattern_reference_warned", False)
    if not isinstance(diagnostics["read_skills"], list):
        diagnostics["read_skills"] = []
    if not isinstance(diagnostics["read_references"], list):
        diagnostics["read_references"] = []
    return diagnostics


def _append_unique(items: list[Any], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _parse_tool_arguments_for_diagnostics(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_call_arguments_for_diagnostics(tool_call: Any, result: dict[str, Any]) -> dict[str, Any]:
    result_args = _parse_tool_arguments_for_diagnostics(result.get("tool_arguments"))
    if result_args:
        return result_args
    raw_args = getattr(tool_call, "arguments", None)
    return _parse_tool_arguments_for_diagnostics(raw_args)


def _is_successful_tool_result(result: dict[str, Any]) -> bool:
    if result.get("success") is True:
        return True
    return str(result.get("status", "")).strip().lower() == "success"


def _is_sql_report_like_task(state: dict[str, Any]) -> bool:
    parts = [
        state.get("__user__"),
        state.get("user_input"),
        state.get("input"),
        state.get("query"),
    ]
    text = " ".join(str(part or "") for part in parts).lower()
    return any(term in text for term in _SQL_REPORT_TASK_TERMS)


def _is_agent_creator_nl2sql_reference(skill_name: str, file_name: str) -> bool:
    skill = skill_name.strip().lower()
    file_path = file_name.strip().replace("\\", "/").lower()
    return skill == "agent_creator" and file_path in {"references/nl2sql.md", "nl2sql.md"}


def update_skill_reference_diagnostics(
    state: dict[str, Any],
    *,
    tool_calls: list[Any],
    round_tool_results: list[dict[str, Any]],
    node_id: str,
) -> list[str]:
    """Track skill/reference usage and warn about likely pattern-reference skips.

    This is intentionally diagnostic-only. It does not block tool execution or
    force a specific architecture; it records evidence that helps explain why an
    agent/workflow build may drift away from a matched skill pattern.
    """
    diagnostics = _ensure_skill_reference_diagnostics(state)
    warnings: list[str] = []
    calls_by_index = list(tool_calls or [])

    for index, result in enumerate(round_tool_results or []):
        if not isinstance(result, dict):
            continue
        tool_call = calls_by_index[index] if index < len(calls_by_index) else None
        tool_name = str(result.get("tool_name") or getattr(tool_call, "name", "") or "").strip()
        tool_name_lower = tool_name.lower()
        arguments = _tool_call_arguments_for_diagnostics(tool_call, result)

        if tool_name_lower == "read_skill_file" and _is_successful_tool_result(result):
            skill_name = str(arguments.get("skill_name") or "").strip()
            file_name = str(arguments.get("file_name") or "").strip()
            if skill_name:
                _append_unique(diagnostics["read_skills"], skill_name)
            if _is_agent_creator_nl2sql_reference(skill_name, file_name):
                _append_unique(diagnostics["read_references"], _AGENT_CREATOR_NL2SQL_REFERENCE)

        if tool_name_lower in _REFERENCE_SENSITIVE_WRITE_TOOLS and _is_successful_tool_result(result):
            already_warned = bool(diagnostics.get("write_before_pattern_reference_warned"))
            has_reference = _AGENT_CREATOR_NL2SQL_REFERENCE in diagnostics["read_references"]
            if not already_warned and not has_reference and _is_sql_report_like_task(state):
                diagnostics["write_before_pattern_reference_warned"] = True
                warnings.append(
                    f"节点 {node_id} 可能跳过了 agent_creator pattern reference: "
                    f"{tool_name} succeeded for a SQL/data/report-like task before reading "
                    f"`references/nl2sql.md`."
                )

    return warnings

def _normalize_path_for_compare(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def _skill_session_key(thread_id: str, workflow_id: str) -> str:
    return f"{thread_id}::{workflow_id}"


def _get_or_create_skill_attestation_session(thread_id: str, workflow_id: str) -> dict[str, Any]:
    now = time.time()
    expired_keys = []
    for key, payload in _SKILL_ATTESTATION_BY_SESSION.items():
        last_seen = float(payload.get("last_seen", 0.0) or 0.0)
        if (now - last_seen) > _SKILL_ATTESTATION_TTL_SECONDS:
            expired_keys.append(key)
    for key in expired_keys:
        _SKILL_ATTESTATION_BY_SESSION.pop(key, None)

    key = _skill_session_key(thread_id, workflow_id)
    payload = _SKILL_ATTESTATION_BY_SESSION.get(key)
    if payload is None:
        payload = {
            "attested_skill_names": set(),
            "attested_skill_paths": set(),
            "reminded_skill_names": set(),
            "last_seen": now,
        }
        _SKILL_ATTESTATION_BY_SESSION[key] = payload
    else:
        payload["last_seen"] = now
        _SKILL_ATTESTATION_BY_SESSION.move_to_end(key)

    while len(_SKILL_ATTESTATION_BY_SESSION) > _SKILL_ATTESTATION_MAX_SESSIONS:
        _SKILL_ATTESTATION_BY_SESSION.popitem(last=False)

    return payload


def _extract_required_skill_candidates(state: dict) -> list[dict[str, str]]:
    raw = state.get("__required_skill_reads__")
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        path = str(item.get("path", "")).strip()
        if not name or not path:
            continue
        key = f"{name.lower()}|{_normalize_path_for_compare(path)}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"name": name, "path": path})
    return normalized


def _build_required_skill_reads(matched_skills: list[Any], configured_skills: Any) -> list[dict[str, str]]:
    """
    Build session-required skill attestations from explicitly configured skills.

    Only explicit non-wildcard skills are enforced. When skills="*", the LLM
    decides which skills to read based on the task — the system prompt lists
    all available skills with summaries for this purpose.
    """
    if not matched_skills or not configured_skills:
        return []
    if configured_skills == "*":
        return []

    if isinstance(configured_skills, str):
        raw_names = [configured_skills]
    elif isinstance(configured_skills, list):
        raw_names = [name for name in configured_skills if isinstance(name, str)]
    else:
        return []

    expected_names = {name.strip().lower() for name in raw_names if name and name.strip()}
    if not expected_names:
        return []

    required: list[dict[str, str]] = []
    seen: set[str] = set()
    for skill in matched_skills:
        skill_name = str(getattr(skill, "name", "")).strip()
        if not skill_name or skill_name.lower() not in expected_names:
            continue
        skill_path = str(getattr(skill, "path", "")).strip()
        if not skill_path:
            continue
        skill_md_path = f"{skill_path}/SKILL.md"
        dedup_key = f"{skill_name.lower()}|{_normalize_path_for_compare(skill_md_path)}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        required.append({"name": skill_name, "path": skill_md_path})
    return required


def _is_skill_md_read_call(tool_name: str, tool_arguments: dict) -> bool:
    lower_name = str(tool_name).strip().lower()
    # read_skill_file is the primary way to read skills
    if lower_name == "read_skill_file":
        return True
    # read_file with a SKILL.md path also counts
    if lower_name == "read_file":
        path = str(tool_arguments.get("path", "")).strip()
        norm = _normalize_path_for_compare(path)
        return norm.endswith("/skill.md") or norm == "skill.md"
    return False


def _is_mcp_tool_call(tool_name: str, tool_exec_kwargs: dict[str, Any]) -> bool:
    lower = str(tool_name or "").strip().lower()
    if not lower:
        return False
    for key in (
        "mcp_tool_names",
        "planning_mcp_tool_names",
        "download_mcp_tool_names",
        "browser_mcp_tool_names",
        "search_mcp_tool_names",
        "computer_mcp_tool_names",
        "coding_mcp_tool_names",
        "published_mcp_tool_names",
    ):
        names = tool_exec_kwargs.get(key)
        if isinstance(names, list):
            if any(str(n).strip().lower() == lower for n in names):
                return True
    return False


def _find_unread_required_skill(
    session_payload: dict[str, Any],
    required_skills: list[dict[str, str]],
) -> Optional[dict[str, str]]:
    attested_names = session_payload.get("attested_skill_names", set())
    attested_paths = session_payload.get("attested_skill_paths", set())
    if not isinstance(attested_names, set):
        attested_names = set()
    if not isinstance(attested_paths, set):
        attested_paths = set()

    for item in required_skills:
        skill_name = str(item.get("name", "")).strip()
        skill_path = str(item.get("path", "")).strip()
        path_norm = _normalize_path_for_compare(skill_path)
        if skill_name.lower() in attested_names:
            continue
        if path_norm in attested_paths:
            continue
        return item
    return None


def _build_skill_attestation_block_message(
    *,
    thread_id: str,
    workflow_id: str,
    missing_skill: dict[str, str],
    session_payload: dict[str, Any],
) -> str:
    skill_name = str(missing_skill.get("name", "")).strip()
    skill_path = str(missing_skill.get("path", "")).strip()
    reminded = session_payload.get("reminded_skill_names", set())
    if not isinstance(reminded, set):
        reminded = set()
        session_payload["reminded_skill_names"] = reminded

    if skill_name.lower() in reminded:
        return (
            "[ERROR] skill_read_required: unresolved skill attestation. "
            f"Read `{skill_path}` via read_file before MCP execution. "
            f"(session={thread_id}, workflow={workflow_id})"
        )

    reminded.add(skill_name.lower())
    return (
        "[ERROR] skill_read_required: MCP execution is blocked until related skill documentation is read.\n"
        f"- required_skill: {skill_name}\n"
        f"- required_path: {skill_path}\n"
        f"- action: call read_file(path=\"{skill_path}\") first, then retry\n"
        f"- session: {thread_id}\n"
        f"- workflow: {workflow_id}"
    )


def _record_skill_read_attestation(
    *,
    thread_id: str,
    workflow_id: str,
    tool_name: str,
    tool_arguments: dict,
    outcome: "ToolExecutionOutcome",
    required_skills: list[dict[str, str]],
) -> None:
    if outcome.status != "success":
        return
    if not _is_skill_md_read_call(tool_name, tool_arguments):
        return

    session_payload = _get_or_create_skill_attestation_session(thread_id, workflow_id)
    path_arg = str(tool_arguments.get("path", "")).strip()
    skill_name_arg = str(tool_arguments.get("skill_name", "")).strip().lower()
    path_norm = _normalize_path_for_compare(path_arg)
    attested_names = session_payload.get("attested_skill_names", set())
    attested_paths = session_payload.get("attested_skill_paths", set())
    if not isinstance(attested_names, set):
        attested_names = set()
        session_payload["attested_skill_names"] = attested_names
    if not isinstance(attested_paths, set):
        attested_paths = set()
        session_payload["attested_skill_paths"] = attested_paths

    if path_norm:
        attested_paths.add(path_norm)
    # Direct skill_name match from read_skill_file calls
    if skill_name_arg:
        attested_names.add(skill_name_arg)
    for item in required_skills:
        skill_name = str(item.get("name", "")).strip()
        skill_path_norm = _normalize_path_for_compare(str(item.get("path", "")))
        if not skill_name:
            continue
        if path_norm == skill_path_norm:
            attested_names.add(skill_name.lower())
            attested_paths.add(skill_path_norm)
            continue
        # tolerate relative/absolute path variants by suffix match
        if skill_path_norm and (path_norm.endswith(skill_path_norm) or skill_path_norm.endswith(path_norm)):
            attested_names.add(skill_name.lower())
            attested_paths.add(skill_path_norm)
            continue
        # fallback by folder name convention: <skill_name>/SKILL.md
        if f"/{skill_name.lower()}/skill.md" in path_norm:
            attested_names.add(skill_name.lower())


async def _execute_tool_with_skill_attestation(
    tool_call: Any,
    *,
    state: dict,
    context: "WorkflowContext",
    tool_exec_kwargs: dict[str, Any],
) -> ToolExecutionOutcome:
    tool_name = str(getattr(tool_call, "name", "") or "")
    tool_arguments = _normalize_tool_arguments(getattr(tool_call, "arguments", {}))

    # 渠道禁用 confirm_action 时自动批准
    if tool_name == "confirm_action" and getattr(context, "disable_confirm_tool", False):
        action = tool_arguments.get("action", "unknown")
        return _to_tool_execution_outcome(
            f"[APPROVED] Action '{action}' auto-approved (channel mode, confirm tool disabled)."
        )

    required_skills = _extract_required_skill_candidates(state)

    thread_id = str(getattr(context, "thread_id", "") or state.get("thread_id") or "default")
    workflow_id = str(getattr(context, "workflow_id", "") or state.get("__workflow_id__") or "default")
    is_mcp_call = _is_mcp_tool_call(tool_name, tool_exec_kwargs)

    if required_skills and is_mcp_call and not _is_skill_md_read_call(tool_name, tool_arguments):
        session_payload = _get_or_create_skill_attestation_session(thread_id, workflow_id)
        missing_skill = _find_unread_required_skill(session_payload, required_skills)
        if missing_skill is not None:
            block_msg = _build_skill_attestation_block_message(
                thread_id=thread_id,
                workflow_id=workflow_id,
                missing_skill=missing_skill,
                session_payload=session_payload,
            )
            return _to_tool_execution_outcome(block_msg, explicit_status="failed")

    outcome = await _execute_tool(
        tool_name,
        tool_arguments,
        state=state,
        workflow_id=workflow_id,
        toolkit=tool_exec_kwargs.get("toolkit"),
        mcp_manager=tool_exec_kwargs.get("mcp_manager"),
        mcp_tool_names=tool_exec_kwargs.get("mcp_tool_names"),
        planning_mcp_manager=tool_exec_kwargs.get("planning_mcp_manager"),
        planning_mcp_tool_names=tool_exec_kwargs.get("planning_mcp_tool_names"),
        download_mcp_manager=tool_exec_kwargs.get("download_mcp_manager"),
        download_mcp_tool_names=tool_exec_kwargs.get("download_mcp_tool_names"),
        browser_mcp_manager=tool_exec_kwargs.get("browser_mcp_manager"),
        browser_mcp_tool_names=tool_exec_kwargs.get("browser_mcp_tool_names"),
        search_mcp_manager=tool_exec_kwargs.get("search_mcp_manager"),
        search_mcp_tool_names=tool_exec_kwargs.get("search_mcp_tool_names"),
        computer_mcp_manager=tool_exec_kwargs.get("computer_mcp_manager"),
        computer_mcp_tool_names=tool_exec_kwargs.get("computer_mcp_tool_names"),
        coding_mcp_manager=tool_exec_kwargs.get("coding_mcp_manager"),
        coding_mcp_tool_names=tool_exec_kwargs.get("coding_mcp_tool_names"),
        published_mcp_tools=tool_exec_kwargs.get("published_mcp_tools"),
        published_mcp_tool_names=tool_exec_kwargs.get("published_mcp_tool_names"),
    )

    if required_skills:
        _record_skill_read_attestation(
            thread_id=thread_id,
            workflow_id=workflow_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            outcome=outcome,
            required_skills=required_skills,
        )

    return outcome
