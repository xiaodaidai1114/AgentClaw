from __future__ import annotations

from pathlib import Path
import re
from datetime import datetime, timezone

MEMORY_CHAR_LIMIT = 40000
MEMORY_COMPRESS_TARGET = 10000


def _safe_workflow_id(workflow_id: str) -> str:
    return str(workflow_id or "default").replace("/", "_").replace("\\", "_")


def get_workflow_memory_path(project_dir: Path, workflow_id: str) -> Path:
    return project_dir / ".agentclaw" / "workflows" / _safe_workflow_id(workflow_id) / "memory.md"


def read_workflow_memory(project_dir: Path, workflow_id: str) -> str:
    path = get_workflow_memory_path(project_dir, workflow_id)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_workflow_memory(project_dir: Path, workflow_id: str, content: str) -> dict[str, object]:
    path = get_workflow_memory_path(project_dir, workflow_id)
    text = str(content or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "path": str(path),
        "chars": len(text),
        "over_limit": len(text) > MEMORY_CHAR_LIMIT,
        "content": text,
    }


def append_context_summary_to_workflow_memory(
    project_dir: Path,
    workflow_id: str,
    summary: str,
) -> dict[str, object]:
    text = str(summary or "").strip()
    path = get_workflow_memory_path(project_dir, workflow_id)
    if not text:
        return {
            "path": str(path),
            "changed": False,
            "chars": len(read_workflow_memory(project_dir, workflow_id)),
            "over_limit": False,
            "content": read_workflow_memory(project_dir, workflow_id),
        }

    original_raw = read_workflow_memory(project_dir, workflow_id)
    original = original_raw.strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = "\n".join([
        "## Context Compression Memory",
        f"_Captured from context compression at {timestamp}._",
        "",
        text,
    ]).strip()
    if original:
        updated = f"{original}\n\n{entry}\n"
    else:
        updated = f"# Workflow Memory\n\n{entry}\n"

    result = write_workflow_memory(project_dir, workflow_id, updated)
    result["changed"] = updated != original_raw
    return result


def update_workflow_memory(
    project_dir: Path,
    workflow_id: str,
    pattern: str,
    replacement: str,
    *,
    dry_run: bool = False,
    replace_all: bool = False,
) -> dict[str, object]:
    original = read_workflow_memory(project_dir, workflow_id)
    matched_total = len(re.findall(pattern, original, flags=re.MULTILINE))
    replace_count = 0 if replace_all else 1
    updated, replaced = re.subn(
        pattern,
        replacement,
        original,
        count=replace_count,
        flags=re.MULTILINE,
    )
    if matched_total == 0 and not original.strip():
        updated = str(replacement or "")
    changed = updated != original
    result = {
        "path": str(get_workflow_memory_path(project_dir, workflow_id)),
        "dry_run": dry_run,
        "changed": changed,
        "replacements": replaced,
        "matched_total": matched_total,
        "replace_all": replace_all,
        "chars": len(updated),
        "over_limit": len(updated) > MEMORY_CHAR_LIMIT,
        "content": updated,
    }
    if changed and not dry_run:
        write_workflow_memory(project_dir, workflow_id, updated)
    return result


def build_memory_section(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    return "\n".join([
        "<workflow_memory>",
        "Workflow memory:",
        text,
        "</workflow_memory>",
    ])
