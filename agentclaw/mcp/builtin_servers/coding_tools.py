"""Built-in MCP server: coding-tools."""

import asyncio
import ast
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from agentclaw.logger.config import get_logger
from agentclaw.mcp.file_lock import file_write_lock

logger = get_logger(__name__)

class CodingToolsServer:
    """
    Coding Tools MCP Server

    IDE-like coding tools with strict project directory sandbox:
    - search_code: Search text/regex in project files
    - syntax_check: Structured syntax validation for common code/config files
    - read_code: Read file content with optional line ranges
    - update_code: Unified multi-mode update (exact/regex/anchor/hunk) with guards
    - replace_in_file: Local text replacement in a single file
    - replace_in_files: Batch text replacement across multiple files
    - rename_path: Rename/move a file or directory

    Security boundary:
    - All path arguments are resolved and validated to stay inside project_dir.
    - Any path outside project_dir is rejected.

    Usage:
        python -m agentclaw.mcp.builtin_servers coding-tools --project-dir .
    """

    def __init__(self, project_dir: Optional[str] = None):
        if project_dir:
            self.project_dir = Path(project_dir).resolve()
        else:
            self.project_dir = Path.cwd().resolve()
        self._server = Server("coding-tools")
        self._setup_handlers()

    @staticmethod
    def _read_positive_int_env(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except Exception:
            return default
        return value if value > 0 else default

    def _default_replace_limit(self) -> int:
        return self._read_positive_int_env("CODING_TOOLS_DEFAULT_MAX_REPLACEMENTS", 40)

    def _default_batch_replace_limit(self) -> int:
        return self._read_positive_int_env("CODING_TOOLS_DEFAULT_MAX_TOTAL_REPLACEMENTS", 200)

    @staticmethod
    def _parse_positive_int_arg(value: Any, field_name: str) -> Optional[int]:
        if value is None:
            return None
        try:
            parsed = int(value)
        except Exception as e:
            raise ValueError(f"'{field_name}' must be a positive integer") from e
        if parsed <= 0:
            raise ValueError(f"'{field_name}' must be a positive integer")
        return parsed

    def _is_within_project(self, path: Path) -> bool:
        try:
            path.relative_to(self.project_dir)
            return True
        except ValueError:
            return False

    def _resolve_project_path(self, path_str: str, allow_missing: bool = False) -> Path:
        raw = Path(path_str)
        candidate = raw if raw.is_absolute() else self.project_dir / raw
        resolved = candidate.resolve(strict=False)
        if not self._is_within_project(resolved):
            raise PermissionError(
                f"Path '{path_str}' is outside project directory '{self.project_dir}'"
            )
        if not allow_missing and not resolved.exists():
            raise FileNotFoundError(f"Path not found: {path_str}")
        return resolved

    def _path_not_found_payload(self, path_str: str) -> dict[str, Any]:
        requested = Path(path_str)
        candidates: List[Path] = []
        base_candidate = requested if requested.is_absolute() else self.project_dir / requested
        candidates.append(base_candidate.resolve(strict=False))

        discovered: List[Path] = []
        if not requested.is_absolute():
            # Generic fallback: discover same relative suffix under project_dir.
            requested_suffix = requested.as_posix().strip("/")
            if requested_suffix:
                for item in self.project_dir.rglob(requested.name):
                    try:
                        rel = item.relative_to(self.project_dir).as_posix()
                    except Exception:
                        continue
                    if rel.endswith(requested_suffix):
                        discovered.append(item.resolve(strict=False))
                    if len(discovered) >= 8:
                        break
                for found in discovered:
                    if found not in candidates:
                        candidates.append(found)

        existing = [p for p in candidates if p.exists()]
        suggested_paths: List[str] = []
        for p in existing:
            try:
                suggested_paths.append(p.relative_to(self.project_dir).as_posix())
            except Exception:
                suggested_paths.append(str(p))

        first_candidate = str(candidates[0]) if candidates else ""
        return {
            "ok": False,
            "error_class": "path_not_found",
            "requested_path": path_str,
            "project_dir": str(self.project_dir),
            "resolved_candidate": first_candidate,
            "suggested_paths": suggested_paths,
            "root_cause_hint": (
                "path is resolved relative to coding-tools project_dir; "
                "it may differ from skill-tools working_dir"
            ),
            "suggested_fix": (
                "Use a path relative to coding-tools project_dir, or pass an absolute path under project_dir. "
                "If tools use different roots, run list/read to confirm the correct root before retrying."
            ),
        }

    def _iter_text_files(self, base: Path, file_glob: str):
        if base.is_file():
            yield base
            return

        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            if file_glob and not fnmatch.fnmatch(rel, file_glob):
                continue
            # Skip common heavy/binary directories
            if any(part in {".git", ".svn", ".hg", "node_modules", ".venv", "venv"} for part in p.parts):
                continue
            yield p

    async def _run_subprocess(
        self,
        cmd: List[str],
        *,
        timeout: Optional[float] = None,
        cwd: Optional[Path] = None,
    ) -> subprocess.CompletedProcess:
        loop = asyncio.get_event_loop()
        run_cwd = str(cwd or self.project_dir)
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=run_cwd,
            ),
        )

    def _normalize_guard_texts(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        raise ValueError("guard must be string or list[string]")

    def _ensure_contains(self, content: str, guard: Any, stage: str) -> None:
        required = self._normalize_guard_texts(guard)
        missing = [t for t in required if t not in content]
        if missing:
            preview = missing[0][:120]
            raise ValueError(f"{stage} guard failed, missing text: {preview}")

    def _detect_language(self, file_path: Path, override: Optional[str]) -> str:
        if override:
            return override.lower()
        ext = file_path.suffix.lower()
        mapping = {
            ".py": "py",
            ".js": "js",
            ".mjs": "js",
            ".cjs": "js",
            ".ts": "ts",
            ".tsx": "ts",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
        }
        return mapping.get(ext, "")

    def _syntax_ok(
        self,
        path: Path,
        language: str,
        *,
        risk_diagnostics: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        risk_items = risk_diagnostics or []
        status = "warning" if risk_items else "success"
        payload = {
            "ok": True,
            "status": status,
            "path": path.relative_to(self.project_dir).as_posix(),
            "language": language,
            "diagnostics": [],
            "risk_diagnostics": risk_items,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _truncate_line(text: str, max_chars: int = 240) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _build_source_context(
        self,
        source: str,
        line: Optional[int],
        *,
        context_lines: int = 3,
    ) -> list[dict[str, Any]]:
        if line is None or line <= 0:
            return []
        lines = source.splitlines()
        if not lines:
            return []
        start = max(1, int(line) - max(0, int(context_lines)))
        end = min(len(lines), int(line) + max(0, int(context_lines)))
        out: list[dict[str, Any]] = []
        for ln in range(start, end + 1):
            text = lines[ln - 1] if 0 <= (ln - 1) < len(lines) else ""
            out.append(
                {
                    "line": ln,
                    "text": self._truncate_line(text),
                    "is_error_line": ln == int(line),
                }
            )
        return out

    def _syntax_err(
        self,
        path: Path,
        language: str,
        message: str,
        line: Optional[int],
        col: Optional[int],
        *,
        code: str = "SYNTAX_ERROR",
        source: str = "",
        end_line: Optional[int] = None,
        end_col: Optional[int] = None,
        context_lines: int = 3,
        include_source_context: bool = True,
        error_class: str = "syntax_error",
    ) -> str:
        line_text = ""
        if line and line > 0:
            src_lines = source.splitlines()
            if 0 <= (line - 1) < len(src_lines):
                line_text = src_lines[line - 1]

        source_context: list[dict[str, Any]] = []
        if include_source_context:
            source_context = self._build_source_context(
                source=source,
                line=line,
                context_lines=context_lines,
            )

        # Build location string for clear error display
        location = ""
        if line:
            location = f":{line}"
            if col:
                location += f":{col}"

        rel_path = path.relative_to(self.project_dir).as_posix()

        # Render human-readable source context with > marker
        context_lines_rendered = []
        for ctx in source_context:
            marker = ">  " if ctx.get("is_error_line") else "   "
            ln = ctx["line"]
            text = ctx.get("text", "")
            context_lines_rendered.append(f"{marker}{ln:>4} | {text}")
        context_str = "\n".join(context_lines_rendered)

        # Smart hint based on error line content
        hint = ""
        if line_text:
            if "&quot;" in line_text or "&#x27;" in line_text or "&gt;" in line_text or "&amp;" in line_text:
                hint = (
                    "\nHINT: Line contains HTML entities (&quot; &gt; &#x27;). "
                    "Use write_code instead of write_file — it auto-sanitizes encoding."
                )
            elif "\\\\n" in line_text or "\\\\t" in line_text:
                hint = (
                    "\nHINT: Line contains double-escaped sequences (e.g. '\\\\n'). "
                    "Use literal multi-line content or single '\\n' for newlines."
                )

        readable = (
            f"✗ SyntaxError: {message}\n"
            f"  File: {rel_path}{location}\n"
        )
        if context_str:
            readable += f"\n{context_str}\n"
        if hint:
            readable += hint

        payload = {
            "ok": False,
            "status": "failed",
            "path": rel_path,
            "language": language,
            "error_class": error_class,
            "error": f"{message}{location}",
            "source_context": source_context,
            "diagnostics": [
                {
                    "code": code,
                    "message": message,
                    "line": line,
                    "col": col,
                    "end_line": end_line,
                    "end_col": end_col,
                }
            ],
        }
        return readable + "\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    def _syntax_tool_unavailable(
        self,
        *,
        path: Path,
        language: str,
        checker: str,
        message: str,
    ) -> str:
        payload = {
            "ok": False,
            "status": "failed",
            "path": path.relative_to(self.project_dir).as_posix(),
            "language": language,
            "error_class": "checker_unavailable",
            "error": f"{checker} checker unavailable for {language} syntax validation",
            "diagnostics": [
                {
                    "code": "CHECKER_UNAVAILABLE",
                    "message": message,
                    "line": None,
                    "col": None,
                    "end_line": None,
                    "end_col": None,
                }
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _detect_python_risk_patterns(
        self,
        source: str,
        *,
        context_lines: int,
        include_source_context: bool,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            tree = ast.parse(source)
        except Exception:
            return out

        for node in ast.walk(tree):
            if not isinstance(node, ast.Set):
                continue
            if not any(isinstance(elem, ast.Dict) for elem in node.elts):
                continue
            line = int(getattr(node, "lineno", 0) or 0) or None
            col = int(getattr(node, "col_offset", 0) or 0) + 1 if getattr(node, "col_offset", None) is not None else None
            diagnostic: dict[str, Any] = {
                "code": "PY_RISK_SET_CONTAINS_DICT",
                "message": (
                    "Set literal contains dict element; dict is unhashable and may raise "
                    "TypeError when evaluated (common double-brace literal mistake)."
                ),
                "line": line,
                "col": col,
            }
            if include_source_context:
                diagnostic["source_context"] = self._build_source_context(
                    source=source,
                    line=line,
                    context_lines=context_lines,
                )
            out.append(diagnostic)

        return out

    def _parse_line_col(self, text: str) -> tuple[Optional[int], Optional[int]]:
        patterns = [
            r":(\d+):(\d+)",
            r":(\d+)\b",
            r"\((\d+),\s*(\d+)\)",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                if len(m.groups()) >= 2:
                    return int(m.group(1)), int(m.group(2))
                return int(m.group(1)), None
        return None, None

    def _setup_handlers(self):
        @self._server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_code",
                    description=(
                        "Grep-style code search. Returns matching lines with line numbers, grouped by file. "
                        "Pattern is always treated as regex (plain text is auto-escaped). "
                        "Use read_code with line numbers from results to read surrounding context. "
                        "Only files under project_dir are searched."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Regex pattern to search (plain text is auto-escaped). Example: 'def\\s+my_func' or 'class MyClass'"},
                            "path": {
                                "type": "string",
                                "description": "Project-relative file or directory to search in",
                                "default": ".",
                            },
                            "glob": {
                                "type": "string",
                                "description": "File glob filter, e.g. '*.py', '**/*.vue'",
                                "default": "**/*",
                            },
                            "context_lines": {
                                "type": "integer",
                                "description": "Number of context lines before and after each match (like grep -C)",
                                "default": 0,
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Max matched lines to return (1-500)",
                                "default": 100,
                            },
                        },
                        "required": ["pattern"],
                    },
                ),
                Tool(
                    name="syntax_check",
                    description=(
                        "Run syntax checks and return structured diagnostics. "
                        "Supports: py, js, ts, json, yaml, toml. "
                        "May also return risk_diagnostics for high-confidence risky patterns even when syntax passes. "
                        "Path is resolved relative to coding-tools project_dir (not skill-tools working_dir). "
                        "If path not found, inspect suggested_paths from error payload."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Project-relative file path"},
                            "language": {
                                "type": "string",
                                "description": "Optional language override: py/js/ts/json/yaml/toml",
                            },
                            "context_lines": {
                                "type": "integer",
                                "description": "How many lines of context to include around the failing line (default 3, range 0-8)",
                                "default": 3,
                            },
                            "include_source_context": {
                                "type": "boolean",
                                "description": "Whether to include source_context in diagnostics (default true)",
                                "default": True,
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="read_code",
                    description=(
                        "Read a text file in project directory with optional line range. "
                        "For Python files, also supports reading a specific function/class by symbol name."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Project-relative file path"},
                            "start_line": {"type": "integer", "description": "1-based start line (optional)"},
                            "end_line": {"type": "integer", "description": "1-based end line (optional)"},
                            "symbol": {"type": "string", "description": "Optional symbol name (Python only)"},
                            "symbol_type": {
                                "type": "string",
                                "enum": ["auto", "function", "class"],
                                "description": "Optional symbol type hint (Python only)",
                                "default": "auto",
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="update_code",
                    description=(
                        "Update code with regex pattern matching. "
                        "Automatically validates syntax after update. "
                        "Use \\s+ for whitespace, .* for any text, capture groups for flexible matching."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "pattern": {"type": "string", "description": "Regex pattern to match"},
                            "replacement": {"type": "string", "description": "Replacement text"},
                            "dry_run": {"type": "boolean", "description": "Preview only", "default": False},
                        },
                        "required": ["path", "pattern", "replacement"],
                    },
                ),
                Tool(
                    name="replace_in_file",
                    description=(
                        "Replace text in a single project file. Supports single or batch replacements.\n"
                        "Single: pass path + old_text/new_text (text mode) or path + start_line/end_line/new_text (line mode).\n"
                        "Batch: pass path + replacements array. Each item is {old_text, new_text} or {start_line, end_line, new_text}. "
                        "Line-mode items are applied bottom-up (highest line first) to keep line numbers stable.\n"
                        "Text mode: old_text/new_text matched LITERALLY — no escape processing.\n"
                        "Line mode: replaces lines [start_line..end_line] (1-based inclusive). "
                        "PREFERRED when you already have line numbers from read_code/grep_code output.\n"
                        "Result contract: success returns concise text summary; failure returns [ERROR] plus structured payload."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Project-relative file path"},
                            "old_text": {"type": "string", "description": "Text to find (literal match). Not needed in line/batch mode."},
                            "new_text": {"type": "string", "description": "Replacement text (written literally)"},
                            "start_line": {
                                "type": "integer",
                                "description": "Line mode: start line number (1-based, inclusive)",
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "Line mode: end line number (1-based, inclusive)",
                            },
                            "replacements": {
                                "type": "array",
                                "description": (
                                    "Batch mode: array of replacements. Each item: "
                                    "{old_text, new_text} for text mode, or "
                                    "{start_line, end_line, new_text} for line mode."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "old_text": {"type": "string"},
                                        "new_text": {"type": "string"},
                                        "start_line": {"type": "integer"},
                                        "end_line": {"type": "integer"},
                                        "replace_all": {"type": "boolean"},
                                    },
                                    "required": ["new_text"],
                                },
                            },
                            "replace_all": {
                                "type": "boolean",
                                "description": "Text mode: replace all occurrences if true, only first if false",
                                "default": False,
                            },
                            "expected_replacements": {
                                "type": "integer",
                                "description": "Text mode: optional guard — fail if actual replacements != expected",
                            },
                            "occurrence_index": {
                                "type": "integer",
                                "description": "Text mode: 1-based occurrence to replace when replace_all=false and multiple matches",
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="list_code_definitions",
                    description=(
                        "List all code definitions (classes, functions, methods) in a file. "
                        "Currently supports Python files via AST parsing. "
                        "Use this to discover symbols before reading them with read_code."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Project-relative file path"},
                            "types": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["class", "function", "method"]},
                                "description": "Filter by definition types (optional)",
                            },
                            "include_private": {
                                "type": "boolean",
                                "description": "Include private definitions (names starting with _)",
                                "default": False,
                            },
                        },
                        "required": ["path"],
                    },
                ),
                Tool(
                    name="lookup_api",
                    description=(
                        "Look up the API of an installed Python package — imports, constructor signatures, "
                        "and key methods. Use this when you are unsure of the correct import path or "
                        "constructor arguments for a framework class. Faster and more reliable than "
                        "search_code for installed packages. "
                        "Example: lookup_api(module='agentclaw', symbol='LLMNode'). "
                        "Result contract: [OK] with import path + signature; [ERROR] if module not found."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "module": {
                                "type": "string",
                                "description": "Top-level package or submodule to inspect (e.g. 'agentclaw', 'agentclaw.node')",
                            },
                            "symbol": {
                                "type": "string",
                                "description": "Class or function name to look up (e.g. 'LLMNode', 'Workflow'). If omitted, lists exported names.",
                            },
                            "include_methods": {
                                "type": "boolean",
                                "description": "Include public methods of the class (default false)",
                                "default": False,
                            },
                        },
                        "required": ["module"],
                    },
                ),
                Tool(
                    name="install_package",
                    description=(
                        "Install Python packages into the current project environment. "
                        "Auto-detects the package manager (uv > pip in venv > conda). "
                        "Packages are installed into the project's virtual environment, not system-wide."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "packages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Package names to install, e.g. ['pandas', 'requests>=2.28']"
                            },
                            "requirements_file": {
                                "type": "string",
                                "description": "Path to requirements.txt file (alternative to packages list)"
                            },
                        },
                        "required": ["packages"]
                    }
                ),
            ]

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            handlers = {
                "search_code": self._search_code,
                "syntax_check": self._syntax_check,
                "read_code": self._read_code,
                "update_code": self._update_code,
                "replace_in_file": self._replace_in_file,
                "list_code_definitions": self._list_code_definitions,
                "lookup_api": self._lookup_api,
                "install_package": self._install_package,
            }
            handler = handlers.get(name)
            if not handler:
                return [TextContent(type="text", text=f"[ERROR] Unknown tool: {name}")]

            try:
                result = await handler(arguments or {})
            except Exception as e:
                result = f"[ERROR] {name} failed: {e}"
            return [TextContent(type="text", text=result)]

    async def _syntax_check(self, args: dict) -> str:
        path = str(args.get("path", "")).strip()
        if not path:
            return "[ERROR] 'path' is required"
        context_lines_raw = args.get("context_lines", 3)
        include_source_context = bool(args.get("include_source_context", True))
        try:
            context_lines = int(context_lines_raw)
        except Exception:
            context_lines = 3
        context_lines = max(0, min(context_lines, 8))

        try:
            file_path = self._resolve_project_path(path)
        except FileNotFoundError:
            payload = self._path_not_found_payload(path)
            return "[ERROR] Path not found\n" + json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"[ERROR] Failed to resolve path: {e}"
        if not file_path.is_file():
            payload = {
                "ok": False,
                "status": "failed",
                "error_class": "not_a_file",
                "error": f"'{path}' exists but is not a regular file (resolved: {file_path})",
                "requested_path": path,
                "project_dir": str(self.project_dir),
            }
            return "[ERROR] Not a file\n" + json.dumps(payload, ensure_ascii=False, indent=2)

        language = self._detect_language(file_path, args.get("language"))
        if not language:
            payload = {
                "ok": False,
                "status": "failed",
                "error_class": "unsupported_language",
                "error": f"Cannot detect language for '{file_path.suffix}'. Supported: py/js/ts/json/yaml/toml",
                "path": file_path.relative_to(self.project_dir).as_posix(),
            }
            return "[ERROR] Unsupported language\n" + json.dumps(payload, ensure_ascii=False, indent=2)

        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Failed to read file: {e}"

        if language == "py":
            try:
                compile(source, str(file_path), "exec")
                risk_diagnostics = self._detect_python_risk_patterns(
                    source,
                    context_lines=context_lines,
                    include_source_context=include_source_context,
                )
                return self._syntax_ok(
                    file_path,
                    language,
                    risk_diagnostics=risk_diagnostics,
                )
            except SyntaxError as e:
                return self._syntax_err(
                    file_path,
                    language,
                    e.msg or "invalid syntax",
                    e.lineno,
                    e.offset,
                    code="PY_SYNTAX_ERROR",
                    source=source,
                    end_line=getattr(e, "end_lineno", None),
                    end_col=getattr(e, "end_offset", None),
                    context_lines=context_lines,
                    include_source_context=include_source_context,
                )

        if language == "json":
            try:
                json.loads(source)
                return self._syntax_ok(file_path, language)
            except json.JSONDecodeError as e:
                return self._syntax_err(
                    file_path,
                    language,
                    e.msg,
                    e.lineno,
                    e.colno,
                    code="JSON_SYNTAX_ERROR",
                    source=source,
                    context_lines=context_lines,
                    include_source_context=include_source_context,
                )

        if language == "toml":
            try:
                import tomllib  # py3.11+
            except Exception:
                try:
                    import tomli as tomllib
                except Exception:
                    return self._syntax_tool_unavailable(
                        path=file_path,
                        language=language,
                        checker="tomllib/tomli",
                        message="TOML checker unavailable (tomllib/tomli not found)",
                    )
            try:
                tomllib.loads(source)
                return self._syntax_ok(file_path, language)
            except Exception as e:
                line, col = self._parse_line_col(str(e))
                return self._syntax_err(
                    file_path,
                    language,
                    str(e),
                    line,
                    col,
                    code="TOML_SYNTAX_ERROR",
                    source=source,
                    context_lines=context_lines,
                    include_source_context=include_source_context,
                )

        if language == "yaml":
            try:
                import yaml
            except Exception:
                return self._syntax_tool_unavailable(
                    path=file_path,
                    language=language,
                    checker="PyYAML",
                    message="YAML checker unavailable (PyYAML not installed)",
                )
            try:
                yaml.safe_load(source)
                return self._syntax_ok(file_path, language)
            except Exception as e:
                line = getattr(getattr(e, "problem_mark", None), "line", None)
                col = getattr(getattr(e, "problem_mark", None), "column", None)
                if line is not None:
                    line += 1
                if col is not None:
                    col += 1
                return self._syntax_err(
                    file_path,
                    language,
                    str(e),
                    line,
                    col,
                    code="YAML_SYNTAX_ERROR",
                    source=source,
                    context_lines=context_lines,
                    include_source_context=include_source_context,
                )

        if language == "js":
            node = shutil.which("node")
            if not node:
                return self._syntax_tool_unavailable(
                    path=file_path,
                    language=language,
                    checker="node",
                    message="JavaScript checker unavailable: 'node' not found",
                )
            proc = await self._run_subprocess([node, "--check", str(file_path)])
            if proc.returncode == 0:
                return self._syntax_ok(file_path, language)
            stderr = (proc.stderr or proc.stdout or "").strip()
            line, col = self._parse_line_col(stderr)
            return self._syntax_err(
                file_path,
                language,
                stderr.splitlines()[-1] if stderr else "JavaScript syntax error",
                line,
                col,
                code="JS_SYNTAX_ERROR",
                source=source,
                context_lines=context_lines,
                include_source_context=include_source_context,
            )

        if language == "ts":
            tsc = shutil.which("tsc")
            if not tsc:
                return self._syntax_tool_unavailable(
                    path=file_path,
                    language=language,
                    checker="tsc",
                    message="TypeScript checker unavailable: 'tsc' not found",
                )
            proc = await self._run_subprocess([tsc, "--noEmit", "--pretty", "false", str(file_path)])
            if proc.returncode == 0:
                return self._syntax_ok(file_path, language)
            out = (proc.stdout + "\n" + proc.stderr).strip()
            first = out.splitlines()[0] if out else "TypeScript syntax/type error"
            line, col = self._parse_line_col(first)
            return self._syntax_err(
                file_path,
                language,
                first,
                line,
                col,
                code="TS_ERROR",
                source=source,
                context_lines=context_lines,
                include_source_context=include_source_context,
            )

        return "[ERROR] Unsupported language"

    def _read_python_symbol(self, file_path: Path, source: str, symbol: str, symbol_type: str) -> str:
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            return f"[ERROR] Python parse failed: {e.msg} at {e.lineno}:{e.offset}"

        allow_func = symbol_type in ("auto", "function")
        allow_class = symbol_type in ("auto", "class")
        matches: List[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if allow_func and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                matches.append((start, end, "function"))
            if allow_class and isinstance(node, ast.ClassDef) and node.name == symbol:
                start = int(getattr(node, "lineno", 1))
                end = int(getattr(node, "end_lineno", start))
                matches.append((start, end, "class"))

        if not matches:
            return f"[ERROR] Symbol '{symbol}' not found in {file_path.name}"

        start, end, kind = sorted(matches, key=lambda x: (x[0], x[1]))[0]
        lines = source.splitlines()
        end = min(end, len(lines))
        chunk = lines[start - 1:end]
        rel = file_path.relative_to(self.project_dir).as_posix()
        body = "\n".join(f"{start + i:>6} | {line}" for i, line in enumerate(chunk))
        return f"File: {rel}\nSymbol: {symbol} ({kind})\nLines: {start}-{end}\n{body}"

    async def _search_code(self, args: dict) -> str:
        # 兼容旧参数名
        pattern = str(args.get("pattern") or args.get("query", "")).strip()
        if not pattern:
            return "[ERROR] 'pattern' is required"

        path = str(args.get("path", "."))
        file_glob = str(args.get("glob") or args.get("file_glob", "**/*"))
        context_lines = max(0, min(int(args.get("context_lines", 0)), 10))
        max_results = max(1, min(int(args.get("max_results", 100)), 500))

        base = self._resolve_project_path(path)
        if not base.exists():
            return f"[ERROR] Path not found: {path}"

        try:
            matcher = re.compile(pattern)
        except re.error:
            # 如果不是合法正则，当作纯文本
            matcher = re.compile(re.escape(pattern))

        # 按文件分组收集结果
        results_by_file: dict[str, list[tuple[int, str]]] = {}
        total_matches = 0
        scanned_files = 0

        for fp in self._iter_text_files(base, file_glob):
            scanned_files += 1
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            file_matches: list[tuple[int, str]] = []
            for line_no, line in enumerate(lines, 1):
                if matcher.search(line):
                    file_matches.append((line_no, line))
                    total_matches += 1
                    if total_matches >= max_results:
                        break
            if file_matches:
                rel = fp.relative_to(self.project_dir).as_posix()
                if context_lines > 0:
                    # 展开上下文行
                    expanded: list[tuple[int, str]] = []
                    seen: set[int] = set()
                    for match_ln, _ in file_matches:
                        start = max(1, match_ln - context_lines)
                        end = min(len(lines), match_ln + context_lines)
                        for ln in range(start, end + 1):
                            if ln not in seen:
                                seen.add(ln)
                                expanded.append((ln, lines[ln - 1]))
                    expanded.sort(key=lambda x: x[0])
                    results_by_file[rel] = expanded
                else:
                    results_by_file[rel] = file_matches
            if total_matches >= max_results:
                break

        if not results_by_file:
            return f"No matches for '{pattern}' (scanned {scanned_files} files)"

        output_parts: list[str] = []
        for rel_path, entries in results_by_file.items():
            file_lines = [f"{ln:>6}: {text}" for ln, text in entries]
            output_parts.append(f"── {rel_path}\n" + "\n".join(file_lines))

        return (
            f"Matches: {total_matches} in {len(results_by_file)} files\n\n"
            + "\n\n".join(output_parts)
        )

    async def _read_code(self, args: dict) -> str:
        path = str(args.get("path", "")).strip()
        if not path:
            return "[ERROR] 'path' is required"

        fp = self._resolve_project_path(path)
        if not fp.is_file():
            return f"[ERROR] Not a file: {path}"

        try:
            source = fp.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Failed to read file: {e}"

        symbol = str(args.get("symbol", "")).strip()
        if symbol:
            symbol_type = str(args.get("symbol_type", "auto")).strip().lower()
            if fp.suffix.lower() != ".py":
                return "[ERROR] symbol mode currently supports Python files only"
            if symbol_type not in {"auto", "function", "class"}:
                return "[ERROR] symbol_type must be one of: auto/function/class"
            return self._read_python_symbol(fp, source, symbol, symbol_type)

        lines = source.splitlines()

        start_line = args.get("start_line")
        end_line = args.get("end_line")
        start = 1 if start_line is None else max(1, int(start_line))
        end = len(lines) if end_line is None else max(start, int(end_line))
        end = min(end, len(lines))

        chunk = lines[start - 1:end]
        rel = fp.relative_to(self.project_dir).as_posix()
        body = "\n".join(f"{start + i:>6} | {line}" for i, line in enumerate(chunk))
        return f"File: {rel}\nLines: {start}-{end}\n{body}"

    async def _list_code_definitions(self, args: dict) -> str:
        path = str(args.get("path", "")).strip()
        if not path:
            return "[ERROR] 'path' is required"

        try:
            fp = self._resolve_project_path(path)
        except FileNotFoundError:
            return f"[ERROR] Path not found: {path}"
        except Exception as e:
            return f"[ERROR] Failed to resolve path: {e}"

        if not fp.is_file():
            return f"[ERROR] Not a file: {path}"

        if fp.suffix.lower() != ".py":
            return "[ERROR] Currently only Python files are supported"

        try:
            source = fp.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Failed to read file: {e}"

        try:
            tree = ast.parse(source, filename=str(fp))
        except SyntaxError as e:
            return f"[ERROR] Syntax error in file: {e}"

        types_filter = args.get("types", [])
        include_private = bool(args.get("include_private", False))

        definitions = []

        # Walk through module-level nodes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if not types_filter or "class" in types_filter:
                    if include_private or not node.name.startswith("_"):
                        methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
                        definitions.append({
                            "type": "class",
                            "name": node.name,
                            "line": node.lineno,
                            "end_line": node.end_lineno,
                            "methods": methods
                        })

                # Add methods if requested
                if not types_filter or "method" in types_filter:
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            if include_private or not item.name.startswith("_"):
                                definitions.append({
                                    "type": "method",
                                    "name": f"{node.name}.{item.name}",
                                    "line": item.lineno,
                                    "end_line": item.end_lineno
                                })

            elif isinstance(node, ast.FunctionDef):
                if not types_filter or "function" in types_filter:
                    if include_private or not node.name.startswith("_"):
                        definitions.append({
                            "type": "function",
                            "name": node.name,
                            "line": node.lineno,
                            "end_line": node.end_lineno
                        })

        payload = {
            "ok": True,
            "path": fp.relative_to(self.project_dir).as_posix(),
            "language": "python",
            "definitions": definitions,
            "total": len(definitions)
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def _lookup_api(self, args: dict) -> str:
        """Look up API of an installed Python package — imports, signatures, methods."""
        module_name = str(args.get("module", "")).strip()
        symbol_name = str(args.get("symbol", "")).strip()
        include_methods = bool(args.get("include_methods", False))

        if not module_name:
            return "[ERROR] 'module' is required (e.g. 'agentclaw', 'agentclaw.node')"

        # Security: only allow lookup of packages that are actually installed,
        # reject anything that looks like path traversal
        if ".." in module_name or "/" in module_name or "\\" in module_name:
            return "[ERROR] Invalid module name"

        import importlib
        import inspect

        # --- 1. import the module ---
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            return f"[ERROR] Module '{module_name}' not found: {e}"
        except Exception as e:
            return f"[ERROR] Failed to import '{module_name}': {e}"

        # --- 2. if no symbol, list exported names ---
        if not symbol_name:
            all_names = getattr(mod, "__all__", None)
            if all_names is None:
                all_names = [n for n in dir(mod) if not n.startswith("_")]
            else:
                all_names = list(all_names)

            categories = {"class": [], "function": [], "other": []}
            for name in sorted(all_names):
                obj = getattr(mod, name, None)
                if obj is None:
                    continue
                if inspect.isclass(obj):
                    categories["class"].append(name)
                elif inspect.isfunction(obj) or inspect.isbuiltin(obj):
                    categories["function"].append(name)
                else:
                    categories["other"].append(name)

            lines = [f"[OK] Module: {module_name}", ""]
            if categories["class"]:
                lines.append("Classes: " + ", ".join(categories["class"]))
            if categories["function"]:
                lines.append("Functions: " + ", ".join(categories["function"]))
            if categories["other"]:
                lines.append("Other: " + ", ".join(categories["other"]))
            lines.append(f"\nUse lookup_api(module='{module_name}', symbol='<name>') for details.")
            return "\n".join(lines)

        # --- 3. find the symbol ---
        obj = getattr(mod, symbol_name, None)

        # try submodule search if not found directly
        search_paths = []
        if obj is None:
            # BFS through submodules to find the symbol
            pkg_path = getattr(mod, "__path__", None)
            if pkg_path:
                try:
                    import pkgutil
                    for importer, submod_name, is_pkg in pkgutil.walk_packages(
                        pkg_path, prefix=module_name + ".", onerror=lambda _: None
                    ):
                        try:
                            submod = importlib.import_module(submod_name)
                            candidate = getattr(submod, symbol_name, None)
                            if candidate is not None:
                                obj = candidate
                                search_paths.append(submod_name)
                                break  # take first match
                        except Exception:
                            continue
                except Exception:
                    pass

        if obj is None:
            # list available names as hint
            all_names = getattr(mod, "__all__", None)
            if all_names is None:
                all_names = [n for n in dir(mod) if not n.startswith("_")]
            return (
                f"[ERROR] Symbol '{symbol_name}' not found in '{module_name}'\n"
                f"Available names: {', '.join(sorted(all_names)[:30])}"
            )

        # --- 4. build import recommendation ---
        source_module = getattr(obj, "__module__", None) or module_name
        import_lines = []
        # shortest import (via re-export)
        if hasattr(mod, symbol_name):
            import_lines.append(f"from {module_name} import {symbol_name}")
        # source import
        if source_module and source_module != module_name:
            import_lines.append(f"from {source_module} import {symbol_name}  # (source)")
        # submodule search result
        for sp in search_paths:
            if sp != module_name and sp != source_module:
                import_lines.append(f"from {sp} import {symbol_name}  # (found via search)")
        if not import_lines:
            import_lines.append(f"from {source_module} import {symbol_name}")

        # --- 5. build signature ---
        sig_str = ""
        try:
            sig = inspect.signature(obj)
            sig_str = f"{symbol_name}{sig}"
        except (ValueError, TypeError):
            if inspect.isclass(obj):
                # try __init__
                try:
                    init_sig = inspect.signature(obj.__init__)
                    # drop 'self'
                    params = list(init_sig.parameters.values())
                    if params and params[0].name == "self":
                        params = params[1:]
                    new_sig = init_sig.replace(parameters=params)
                    sig_str = f"{symbol_name}{new_sig}"
                except (ValueError, TypeError):
                    sig_str = f"{symbol_name}(...)"

        # --- 6. docstring ---
        doc = inspect.getdoc(obj) or ""
        if doc:
            doc_lines = doc.splitlines()
            if len(doc_lines) > 8:
                doc = "\n".join(doc_lines[:8]) + "\n..."

        # --- 7. methods (if class) ---
        methods_str = ""
        if include_methods and inspect.isclass(obj):
            methods = []
            for name in sorted(dir(obj)):
                if name.startswith("_"):
                    continue
                member = getattr(obj, name, None)
                if member is None or not callable(member):
                    continue
                try:
                    msig = inspect.signature(member)
                    methods.append(f"  .{name}{msig}")
                except (ValueError, TypeError):
                    methods.append(f"  .{name}(...)")
            if methods:
                methods_str = "\n\nPublic methods:\n" + "\n".join(methods[:20])
                if len(methods) > 20:
                    methods_str += f"\n  ... and {len(methods) - 20} more"

        # --- 8. assemble result ---
        result_parts = [f"[OK] {symbol_name}", ""]
        result_parts.append("# Import")
        for imp in import_lines:
            result_parts.append(imp)

        if sig_str:
            result_parts.append(f"\n# Constructor/Signature\n{sig_str}")

        if doc:
            result_parts.append(f"\n# Description\n{doc}")

        if methods_str:
            result_parts.append(methods_str)

        return "\n".join(result_parts)

    def _apply_exact_update(self, content: str, args: dict) -> tuple[str, int]:
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        replace_all = bool(args.get("replace_all", False))
        allow_ambiguous_first = bool(args.get("allow_ambiguous_first", False))
        occurrence_index = self._parse_positive_int_arg(args.get("occurrence_index"), "occurrence_index")
        max_replacements = self._parse_positive_int_arg(args.get("max_replacements"), "max_replacements")
        if not isinstance(old_text, str) or old_text == "":
            raise ValueError("'old_text' must be a non-empty string for exact mode")
        if not isinstance(new_text, str):
            raise ValueError("'new_text' must be a string for exact mode")
        if replace_all and occurrence_index is not None:
            raise ValueError("occurrence_index cannot be used with replace_all=true")
        occurrences = content.count(old_text)
        if occurrences == 0:
            return content, 0
        if replace_all:
            effective_max = max_replacements if max_replacements is not None else self._default_replace_limit()
            if occurrences > effective_max:
                raise ValueError(
                    f"replace_all would affect {occurrences} occurrences, exceeding max_replacements={effective_max}"
                )
            updated = content.replace(old_text, new_text, occurrences)
            return updated, occurrences

        if occurrence_index is not None:
            if occurrence_index > occurrences:
                raise ValueError(
                    f"occurrence_index out of range: {occurrence_index} (total matches: {occurrences})"
                )
            updated = self._replace_nth_occurrence(content, old_text, new_text, occurrence_index)
            return updated, 1

        if occurrences > 1 and not allow_ambiguous_first:
            lines = self._find_occurrence_lines(content, old_text, limit=5)
            hint = ", ".join(str(line) for line in lines) if lines else "unknown"
            raise ValueError(
                f"Ambiguous match: found {occurrences} occurrences. "
                f"Use occurrence_index (1..{occurrences}) or set allow_ambiguous_first=true. "
                f"First matched line numbers: {hint}"
            )

        updated = content.replace(old_text, new_text, 1)
        return updated, 1

    async def _install_package(self, args: dict) -> str:
        """Install Python packages using auto-detected package manager."""
        packages = args.get("packages")
        req_file = (args.get("requirements_file") or "").strip()

        if not packages and not req_file:
            return "[ERROR] Must provide 'packages' (array) or 'requirements_file' (string)"
        if packages and not isinstance(packages, list):
            return "[ERROR] 'packages' must be an array of strings"

        # 如果指定了 requirements_file，解析为绝对路径
        req_path = None
        if req_file:
            req_path = Path(req_file)
            if not req_path.is_absolute():
                req_path = (self.project_dir / req_file).resolve()
            if not req_path.is_file():
                return f"[ERROR] requirements file not found: {req_file}"

        # 检测包管理器（优先级：uv > pip in venv > conda）
        python_exe = sys.executable
        venv_root = Path(python_exe).parent.parent
        in_venv = (venv_root / "pyvenv.cfg").exists()

        # 镜像源：优先读环境变量，默认清华源
        index_url = os.environ.get("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")

        pkg_manager = None
        cmd: list[str] = []

        # 1. uv
        if shutil.which("uv"):
            pkg_manager = "uv"
            base = ["uv", "pip", "install", "--python", python_exe, "--index-url", index_url]
            if req_file:
                cmd = base + ["-r", str(req_path)]
            else:
                cmd = base + packages

        # 2. pip in venv
        elif in_venv:
            pkg_manager = "pip"
            base = [python_exe, "-m", "pip", "install", "-i", index_url]
            if req_file:
                cmd = base + ["-r", str(req_path)]
            else:
                cmd = base + packages

        # 3. conda
        elif os.environ.get("CONDA_DEFAULT_ENV"):
            pkg_manager = "conda"
            if req_file:
                cmd = ["conda", "install", "-y", "--file", str(req_path)]
            else:
                cmd = ["conda", "install", "-y"] + packages

        else:
            return (
                "[ERROR] No suitable package manager found.\n"
                f"python_executable: {python_exe}\n"
                "Not in a virtual environment and uv/conda not available.\n"
                "Please create a virtual environment first: python -m venv .venv"
            )

        target = req_file if req_file else " ".join(packages)
        try:
            proc = await self._run_subprocess(
                cmd,
                timeout=180,
                cwd=self.project_dir,
            )
        except asyncio.TimeoutError:
            return f"[ERROR] Installation timed out (180s) for: {target}"
        except Exception as e:
            return f"[ERROR] Failed to run {pkg_manager}: {e}"

        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""

        if proc.returncode != 0:
            parts = [f"[ERROR] {pkg_manager} install failed (exit code {proc.returncode})"]
            if stdout_text.strip():
                parts.append(f"[stdout]\n{stdout_text}")
            if stderr_text.strip():
                parts.append(f"[stderr]\n{stderr_text}")
            return "\n".join(parts)

        result = f"[OK] Installed via {pkg_manager}: {target}"
        if stdout_text.strip():
            lines = stdout_text.strip().splitlines()
            if len(lines) > 10:
                result += "\n" + "\n".join(lines[-10:])
            else:
                result += "\n" + stdout_text.strip()
        return result

    def _apply_regex_update(self, content: str, args: dict) -> tuple[str, int]:
        pattern = args.get("pattern")
        replacement = args.get("replacement")
        replace_all = bool(args.get("replace_all", False))
        if not isinstance(pattern, str) or pattern == "":
            raise ValueError("'pattern' must be a non-empty string for regex mode")
        if not isinstance(replacement, str):
            raise ValueError("'replacement' must be a string for regex mode")
        try:
            rx = re.compile(pattern, re.MULTILINE)
        except re.error as e:
            raise ValueError(f"invalid regex pattern: {e}") from e
        count = 0 if replace_all else 1
        updated, replaced = rx.subn(replacement, content, count=count)
        return updated, replaced

    @staticmethod
    def _normalize_update_code_args(args: dict) -> dict:
        """
        Best-effort arg normalization for update_code.

        Goal: tolerate common model/tool call param drifts while preserving explicit mode semantics.
        """
        normalized = dict(args)
        mode = str(normalized.get("mode", "regex")).strip().lower()

        # Backward compat: if mode is "exact", convert to regex with escaped pattern
        if mode == "exact":
            import re as _re
            old_text = normalized.get("old_text", "")
            if isinstance(old_text, str) and old_text:
                normalized["pattern"] = _re.escape(old_text)
                normalized["replacement"] = normalized.get("new_text", "")
                normalized["mode"] = "regex"
                mode = "regex"

        # Common alias: "replacement" used as replacement payload in anchor mode.
        if mode == "anchor" and not isinstance(normalized.get("new_text"), str):
            if isinstance(normalized.get("replacement"), str):
                normalized["new_text"] = normalized["replacement"]

        # Common aliases for anchor mode.
        if mode == "anchor":
            if not isinstance(normalized.get("anchor_before"), str):
                for key in ("before", "start_anchor"):
                    if isinstance(normalized.get(key), str) and normalized.get(key):
                        normalized["anchor_before"] = normalized[key]
                        break
            if not isinstance(normalized.get("anchor_after"), str):
                for key in ("after", "end_anchor"):
                    if isinstance(normalized.get(key), str) and normalized.get(key):
                        normalized["anchor_after"] = normalized[key]
                        break

        # Common alias for regex mode.
        if mode == "regex" and not isinstance(normalized.get("replacement"), str):
            if isinstance(normalized.get("new_text"), str):
                normalized["replacement"] = normalized["new_text"]

        return normalized

    def _apply_anchor_update(self, content: str, args: dict) -> tuple[str, int]:
        before = args.get("anchor_before")
        after = args.get("anchor_after")
        new_text = args.get("new_text")
        replace_all = bool(args.get("replace_all", False))
        allow_ambiguous_first = bool(args.get("allow_ambiguous_first", False))
        occurrence_index = self._parse_positive_int_arg(args.get("occurrence_index"), "occurrence_index")
        max_replacements = self._parse_positive_int_arg(args.get("max_replacements"), "max_replacements")
        if not isinstance(before, str) or before == "":
            raise ValueError("'anchor_before' must be a non-empty string for anchor mode")
        if not isinstance(new_text, str):
            raise ValueError("'new_text' must be a string for anchor mode")
        if replace_all and occurrence_index is not None:
            raise ValueError("occurrence_index cannot be used with replace_all=true")

        before_occurrences = content.count(before)
        if before_occurrences == 0:
            return content, 0

        # anchor_after omitted: insert new_text immediately after anchor_before
        if not isinstance(after, str) or after == "":
            if not replace_all:
                if occurrence_index is not None:
                    if occurrence_index > before_occurrences:
                        raise ValueError(
                            f"occurrence_index out of range: {occurrence_index} (total matches: {before_occurrences})"
                        )
                    pos = -1
                    cursor = 0
                    for _ in range(occurrence_index):
                        pos = content.find(before, cursor)
                        cursor = pos + len(before)
                    anchor_end = pos + len(before)
                    updated = content[:anchor_end] + new_text + content[anchor_end:]
                    return updated, 1
                if before_occurrences > 1 and not allow_ambiguous_first:
                    lines = self._find_occurrence_lines(content, before, limit=5)
                    hint = ", ".join(str(line) for line in lines) if lines else "unknown"
                    raise ValueError(
                        f"Ambiguous anchor_before: found {before_occurrences} occurrences. "
                        f"Use occurrence_index (1..{before_occurrences}) or set allow_ambiguous_first=true. "
                        f"First matched line numbers: {hint}"
                    )

            result = []
            cursor = 0
            replaced = 0
            effective_max = max_replacements if max_replacements is not None else self._default_replace_limit()
            while True:
                i = content.find(before, cursor)
                if i < 0:
                    break
                anchor_end = i + len(before)
                result.append(content[cursor:anchor_end])
                result.append(new_text)
                cursor = anchor_end
                replaced += 1
                if replace_all and replaced > effective_max:
                    raise ValueError(
                        f"replace_all would affect more than max_replacements={effective_max} blocks"
                    )
                if not replace_all:
                    break

            if replaced == 0:
                return content, 0
            result.append(content[cursor:])
            return "".join(result), replaced

        if not replace_all:
            if occurrence_index is not None:
                if occurrence_index > before_occurrences:
                    raise ValueError(
                        f"occurrence_index out of range: {occurrence_index} (total matches: {before_occurrences})"
                    )
                pos = -1
                cursor = 0
                for _ in range(occurrence_index):
                    pos = content.find(before, cursor)
                    cursor = pos + len(before)
                j = content.find(after, pos + len(before))
                if j < 0:
                    raise ValueError("'anchor_after' was not found after selected 'anchor_before'")
                updated = content[:pos + len(before)] + new_text + content[j:]
                return updated, 1
            if before_occurrences > 1 and not allow_ambiguous_first:
                lines = self._find_occurrence_lines(content, before, limit=5)
                hint = ", ".join(str(line) for line in lines) if lines else "unknown"
                raise ValueError(
                    f"Ambiguous anchor_before: found {before_occurrences} occurrences. "
                    f"Use occurrence_index (1..{before_occurrences}) or set allow_ambiguous_first=true. "
                    f"First matched line numbers: {hint}"
                )

        result = []
        cursor = 0
        replaced = 0
        found_before_without_after = False
        effective_max = max_replacements if max_replacements is not None else self._default_replace_limit()
        while True:
            i = content.find(before, cursor)
            if i < 0:
                break
            j = content.find(after, i + len(before))
            if j < 0:
                found_before_without_after = True
                break
            result.append(content[cursor:i + len(before)])
            result.append(new_text)
            cursor = j
            replaced += 1
            if replace_all and replaced > effective_max:
                raise ValueError(
                    f"replace_all would affect more than max_replacements={effective_max} blocks"
                )
            if not replace_all:
                break

        if found_before_without_after:
            raise ValueError("'anchor_after' was not found after a matched 'anchor_before'")
        if replaced == 0:
            return content, 0
        result.append(content[cursor:])
        return "".join(result), replaced

    def _apply_hunk_update(self, content: str, args: dict) -> tuple[str, int]:
        hunk = args.get("hunk")
        replace_all = bool(args.get("replace_all", False))
        if not isinstance(hunk, str) or hunk.strip() == "":
            raise ValueError("'hunk' must be a non-empty string for hunk mode")

        old_parts: List[str] = []
        new_parts: List[str] = []
        for raw in hunk.splitlines(keepends=True):
            if raw.startswith(("---", "+++", "@@")):
                continue
            if raw.startswith("\\ No newline at end of file"):
                continue
            if not raw:
                continue
            prefix = raw[0]
            body = raw[1:]
            if prefix == " ":
                old_parts.append(body)
                new_parts.append(body)
            elif prefix == "-":
                old_parts.append(body)
            elif prefix == "+":
                new_parts.append(body)
            else:
                raise ValueError("hunk contains unsupported line prefix")

        old_block = "".join(old_parts)
        new_block = "".join(new_parts)
        if old_block == "":
            raise ValueError("hunk old block is empty")
        occurrences = content.count(old_block)
        if occurrences == 0:
            return content, 0
        count = occurrences if replace_all else 1
        updated = content.replace(old_block, new_block, count)
        return updated, count

    @staticmethod
    def _update_code_mode_hint(mode: str) -> str:
        hints = {
            "exact": "exact mode requires: old_text, new_text",
            "regex": "regex mode requires: pattern, replacement",
            "anchor": "anchor mode requires: anchor_before, new_text (anchor_after optional for bounded replacement)",
            "hunk": "hunk mode requires: hunk",
        }
        return hints.get(mode, "mode must be one of: exact/regex/anchor/hunk")

    @staticmethod
    def _update_code_missing_fields(mode: str, args: dict) -> list[str]:
        missing: list[str] = []
        if mode == "exact":
            if not isinstance(args.get("old_text"), str) or args.get("old_text") == "":
                missing.append("old_text")
            if not isinstance(args.get("new_text"), str):
                missing.append("new_text")
            return missing
        if mode == "regex":
            if not isinstance(args.get("pattern"), str) or args.get("pattern") == "":
                missing.append("pattern")
            if not isinstance(args.get("replacement"), str):
                missing.append("replacement")
            return missing
        if mode == "anchor":
            if not isinstance(args.get("anchor_before"), str) or args.get("anchor_before") == "":
                missing.append("anchor_before")
            if not isinstance(args.get("new_text"), str):
                missing.append("new_text")
            return missing
        if mode == "hunk":
            if not isinstance(args.get("hunk"), str) or args.get("hunk", "").strip() == "":
                missing.append("hunk")
            return missing
        return missing

    @staticmethod
    def _update_code_actionable_hint(mode: str, args: dict) -> str:
        """
        Provide concise, copyable fixes for common call-shape errors.
        """
        if mode == "exact":
            missing = CodingToolsServer._update_code_missing_fields(mode, args)
            if missing:
                return (
                    "exact mode is missing required fields: "
                    + ", ".join(missing)
                    + ". Repair arguments before continuing. Example: "
                    + '{mode:"exact", path:"workflows/foo.py", old_text:"workflow.set_start(\\"agent\\")", '
                      'new_text:"workflow.add_edge(\\"__start__\\", \\"agent\\")", expected_count:1}'
                )
            return (
                "For exact mode precision: set expected_count=1 for single-edit intent; "
                "if multiple matches exist, set occurrence_index explicitly (or allow_ambiguous_first=true only when intentional)."
            )

        if mode != "anchor":
            if mode == "regex":
                missing = CodingToolsServer._update_code_missing_fields(mode, args)
                if missing:
                    return (
                        "regex mode is missing required fields: "
                        + ", ".join(missing)
                        + ". Example: "
                        + '{mode:"regex", path:"workflows/foo.py", pattern:"workflow\\\\.set_start\\\\(\\\\\\"agent\\\\\\"\\\\)", '
                          'replacement:"workflow.add_edge(\\"__start__\\", \\"agent\\")"}'
                    )
            if mode == "hunk":
                missing = CodingToolsServer._update_code_missing_fields(mode, args)
                if missing:
                    return (
                        "hunk mode is missing required field: hunk. "
                        "Example: {mode:\"hunk\", path:\"workflows/foo.py\", hunk:\"@@\\n- old\\n+ new\\n\"}"
                    )
            return CodingToolsServer._update_code_mode_hint(mode)

        missing = CodingToolsServer._update_code_missing_fields(mode, args)

        if not missing:
            return CodingToolsServer._update_code_mode_hint(mode)

        return (
            "anchor mode is missing required fields: "
            + ", ".join(missing)
            + ". Repair arguments before continuing. Example (add anchor_after when bounded replacement is needed): "
            + '{mode:"anchor", path:"server.py", anchor_before:"# 导入工作流定义", '
              'anchor_after:"import workflows.agent as agent", '
              'new_text:"import workflows.contract_recommender", expected_count:1}'
        )

    def _validate_syntax(self, file_path: Path, content: str) -> Optional[str]:
        """验证文件语法，返回错误信息或 None"""
        ext = file_path.suffix.lower()

        if ext == ".py":
            try:
                ast.parse(content)
                return None
            except SyntaxError as e:
                return f"Line {e.lineno}: {e.msg}\n{e.text or ''}"

        if ext in (".json", ".jsonc"):
            try:
                json.loads(content)
                return None
            except json.JSONDecodeError as e:
                return f"Line {e.lineno}: {e.msg}"

        return None

    async def _update_code(self, args: dict) -> str:
        path = str(args.get("path", "")).strip()
        pattern = args.get("pattern", "")
        replacement = args.get("replacement", "")
        dry_run = bool(args.get("dry_run", False))

        if not path:
            return "[ERROR] 'path' is required"
        if not pattern:
            return "[ERROR] 'pattern' is required"
        if replacement is None:
            return "[ERROR] 'replacement' is required"

        file_path = self._resolve_project_path(path)
        if not file_path.is_file():
            return f"[ERROR] Not a file: {path}"

        async with file_write_lock(file_path):
            try:
                original = file_path.read_text(encoding="utf-8")
            except Exception as e:
                return f"[ERROR] Failed to read file: {e}"

            try:
                import re
                updated = re.sub(pattern, replacement, original, flags=re.MULTILINE)
                replaced = len(re.findall(pattern, original, flags=re.MULTILINE))
            except Exception as e:
                return f"[ERROR] Regex failed: {e}"

            changed = updated != original

            syntax_warning = None
            if changed:
                syntax_warning = self._validate_syntax(file_path, updated)

            if changed and not dry_run:
                file_path.write_text(updated, encoding="utf-8")

        result = {
            "ok": True,
            "path": file_path.relative_to(self.project_dir).as_posix(),
            "dry_run": dry_run,
            "changed": changed,
            "replacements": replaced,
        }

        if syntax_warning:
            result["syntax_warning"] = syntax_warning

        if changed:
            updated_lines = updated.splitlines()
            original_lines = original.splitlines()
            first_diff = next((i for i, (a, b) in enumerate(zip(original_lines, updated_lines)) if a != b),
                            min(len(original_lines), len(updated_lines)))

            result["affected_lines"] = {"start": first_diff + 1}

            preview_start = max(0, first_diff - 2)
            preview_end = min(len(updated_lines), first_diff + 20)
            preview = "\n".join(f"{i+1:>6} | {updated_lines[i]}" for i in range(preview_start, preview_end))
            result["preview"] = preview

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _plan_replacement(
        self,
        content: str,
        old_text: str,
        new_text: str,
        replace_all: bool,
        expected_replacements: Optional[int] = None,
        occurrence_index: Optional[int] = None,
        allow_ambiguous_first: bool = False,
        max_replacements: Optional[int] = None,
    ) -> tuple[int, str]:
        occurrences = content.count(old_text)
        if occurrences == 0:
            return 0, content

        if replace_all and occurrence_index is not None:
            raise ValueError("occurrence_index cannot be used with replace_all=true")

        if max_replacements is not None and max_replacements <= 0:
            raise ValueError("max_replacements must be >= 1")

        if not replace_all and occurrence_index is not None and occurrence_index <= 0:
            raise ValueError("occurrence_index must be >= 1")

        if not replace_all and occurrences > 1 and occurrence_index is None and not allow_ambiguous_first:
            locations = self._find_occurrence_lines(content, old_text, limit=5)
            hint = ", ".join(str(line) for line in locations) if locations else "unknown"
            raise ValueError(
                f"Ambiguous match: found {occurrences} occurrences. "
                f"Use occurrence_index (1..{occurrences}) or set allow_ambiguous_first=true. "
                f"First matched line numbers: {hint}"
            )

        if replace_all:
            if max_replacements is not None and occurrences > max_replacements:
                raise ValueError(
                    f"replace_all would affect {occurrences} occurrences, exceeding max_replacements={max_replacements}"
                )
            replace_count = occurrences
            new_content = content.replace(old_text, new_text, replace_count)
        elif occurrence_index is not None:
            if occurrence_index > occurrences:
                raise ValueError(
                    f"occurrence_index out of range: {occurrence_index} (total matches: {occurrences})"
                )
            new_content = self._replace_nth_occurrence(content, old_text, new_text, occurrence_index)
            replace_count = 1
        else:
            replace_count = 1
            new_content = content.replace(old_text, new_text, 1)

        if expected_replacements is not None and replace_count != expected_replacements:
            raise ValueError(
                f"Expected {expected_replacements} replacements, but would replace {replace_count}"
            )

        return replace_count, new_content

    def _replace_file_text(
        self,
        fp: Path,
        old_text: str,
        new_text: str,
        replace_all: bool,
        expected_replacements: Optional[int] = None,
        occurrence_index: Optional[int] = None,
        allow_ambiguous_first: bool = False,
        max_replacements: Optional[int] = None,
    ) -> int:
        content = fp.read_text(encoding="utf-8")
        replace_count, new_content = self._plan_replacement(
            content=content,
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
            expected_replacements=expected_replacements,
            occurrence_index=occurrence_index,
            allow_ambiguous_first=allow_ambiguous_first,
            max_replacements=max_replacements,
        )
        if replace_count == 0:
            return 0
        fp.write_text(new_content, encoding="utf-8")
        return replace_count

    @staticmethod
    def _replace_nth_occurrence(content: str, old_text: str, new_text: str, index: int) -> str:
        """Replace the Nth (1-based) occurrence of old_text."""
        cursor = 0
        count = 0
        while True:
            pos = content.find(old_text, cursor)
            if pos < 0:
                return content
            count += 1
            if count == index:
                return content[:pos] + new_text + content[pos + len(old_text):]
            cursor = pos + len(old_text)

    @staticmethod
    def _find_occurrence_lines(content: str, old_text: str, limit: int = 5) -> List[int]:
        """Return line numbers for first few occurrences to help disambiguate replacements."""
        lines: List[int] = []
        cursor = 0
        while len(lines) < limit:
            pos = content.find(old_text, cursor)
            if pos < 0:
                break
            line_no = content.count("\n", 0, pos) + 1
            lines.append(line_no)
            cursor = pos + len(old_text)
        return lines

    async def _replace_in_file(self, args: dict) -> str:
        path = str(args.get("path", "")).strip()
        if not path:
            return "[ERROR] 'path' is required"

        fp = self._resolve_project_path(path)
        if not fp.is_file():
            return f"[ERROR] Not a file: {path}"

        rel = fp.relative_to(self.project_dir).as_posix()

        async with file_write_lock(fp):
            try:
                original = fp.read_text(encoding="utf-8")
            except Exception as e:
                return f"[ERROR] Failed to read file: {e}"

            # ── BATCH mode ──
            replacements = args.get("replacements")
            if isinstance(replacements, list) and replacements:
                result = self._replace_batch(fp, rel, original, replacements)
                return await self._append_replace_syntax_feedback(result, fp)

            # ── Single: LINE mode ──
            new_text = args.get("new_text")
            start_line = args.get("start_line")
            end_line = args.get("end_line")

            if start_line is not None and end_line is not None:
                if not isinstance(new_text, str):
                    return "[ERROR] 'new_text' must be a string"
                result = self._replace_by_lines(fp, rel, original, int(start_line), int(end_line), new_text)
                return await self._append_replace_syntax_feedback(result, fp)

            # ── Single: TEXT mode ──
            if not isinstance(new_text, str):
                return "[ERROR] 'new_text' must be a string"
            old_text = args.get("old_text")
            if not isinstance(old_text, str) or old_text == "":
                return "[ERROR] Text mode requires non-empty 'old_text'. For line-range mode, pass start_line + end_line."

            replace_all = bool(args.get("replace_all", False))
            expected = args.get("expected_replacements")
            occurrence_index = args.get("occurrence_index")
            allow_ambiguous_first = bool(args.get("allow_ambiguous_first", False))
            max_replacements_raw = args.get("max_replacements")

            try:
                max_replacements = self._parse_positive_int_arg(max_replacements_raw, "max_replacements")
            except Exception as e:
                return f"[ERROR] Replace failed: {e}"

            if replace_all and max_replacements is None and expected is None:
                max_replacements = self._default_replace_limit()

            try:
                replaced = self._replace_file_text(
                    fp=fp,
                    old_text=old_text,
                    new_text=new_text,
                    replace_all=replace_all,
                    expected_replacements=int(expected) if expected is not None else None,
                    occurrence_index=int(occurrence_index) if occurrence_index is not None else None,
                    allow_ambiguous_first=allow_ambiguous_first,
                    max_replacements=max_replacements,
                )
            except Exception as e:
                text = str(e)
                if "Expected" in text and "replacements" in text:
                    m = re.search(r"Expected\s+(\d+)\s+replacements,\s+but\s+would\s+replace\s+(\d+)", text)
                    expected_val = int(m.group(1)) if m else expected
                    actual_val = int(m.group(2)) if m else None
                    payload = {
                        "ok": False,
                        "error_class": "expected_replacements_mismatch",
                        "path": path,
                        "expected_replacements": expected_val,
                        "actual_replacements": actual_val,
                        "root_cause_hint": "expected_replacements guard is too strict for current match count",
                        "suggested_fix": (
                            "Either set expected_replacements to actual count, or omit expected_replacements "
                            "until the edit pattern is stable."
                        ),
                    }
                    return "[ERROR] Replace failed: expected_replacements mismatch\n" + json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                if "max_replacements" in text:
                    payload = {
                        "ok": False,
                        "error_class": "replacement_scope_too_large",
                        "path": path,
                        "root_cause_hint": "replace_all scope exceeds safe cap",
                        "suggested_fix": (
                            "Narrow old_text for a more specific match, or set max_replacements explicitly "
                            "after confirming match count with read_code/search_code."
                        ),
                        "error": text,
                    }
                    return "[ERROR] Replace failed: replacement scope too large\n" + json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                return f"[ERROR] Replace failed: {e}"

            if replaced == 0:
                old_norm = old_text.replace("\r\n", "\n").strip()
                file_norm = original.replace("\r\n", "\n")
                hint_lines = [f"No changes in {rel} (target text not found)"]
                if old_norm and old_norm in file_norm:
                    hint_lines.append(
                        "Hint: likely whitespace/indent/newline mismatch. "
                        "Try exact copy from read_code/read_file, or use update_code(anchor) with dry_run first."
                    )
                else:
                    hint_lines.append(
                        "Hint: old_text does not appear in file. "
                        "Use read_code to confirm exact snippet, or use line mode (start_line + end_line)."
                    )
                return "\n".join(hint_lines)

            summary = f"Updated {rel}: replaced {replaced} occurrence(s)"
            try:
                updated_content = fp.read_text(encoding="utf-8")
                updated_lines = updated_content.splitlines()
                original_lines = original.splitlines()
                first_diff = 0
                for i, (a, b) in enumerate(zip(original_lines, updated_lines)):
                    if a != b:
                        first_diff = i
                        break
                else:
                    first_diff = min(len(original_lines), len(updated_lines))
                last_diff = len(updated_lines) - 1
                last_orig = len(original_lines) - 1
                while last_diff > first_diff and last_orig > first_diff:
                    if updated_lines[last_diff] == original_lines[last_orig]:
                        last_diff -= 1
                        last_orig -= 1
                    else:
                        break
                preview_start = max(0, first_diff - 2)
                preview_end = min(len(updated_lines), last_diff + 3)
                if preview_end - preview_start > 50:
                    preview_end = preview_start + 50
                preview_parts = [f"{ln + 1:>6} | {updated_lines[ln]}" for ln in range(preview_start, preview_end)]
                if preview_end < len(updated_lines) and preview_end - preview_start >= 50:
                    preview_parts.append("       ... (use read_code for full content)")
                summary += f"\naffected_lines: {first_diff + 1}-{last_diff + 1}\n" + "\n".join(preview_parts)
            except Exception:
                pass
            return await self._append_replace_syntax_feedback(summary, fp)

    async def _append_replace_syntax_feedback(self, result: str, fp: Path) -> str:
        if not result.startswith("Updated "):
            return result

        language = self._detect_language(fp, None)
        if not language:
            return result

        rel = fp.relative_to(self.project_dir).as_posix()
        syntax_output = await self._syntax_check(
            {
                "path": rel,
                "language": language,
                "context_lines": 3,
                "include_source_context": True,
            }
        )

        if '"ok": true' in syntax_output:
            if '"risk_diagnostics": []' in syntax_output:
                return result + "\nsyntax_check: PASSED"
            return result + "\nsyntax_check: PASSED_WITH_WARNINGS\n" + syntax_output

        if '"error_class": "checker_unavailable"' in syntax_output:
            return result + "\nsyntax_check: UNAVAILABLE\n" + syntax_output

        if '"ok": false' in syntax_output or syntax_output.startswith("[ERROR]"):
            return result + "\nsyntax_check: FAILED\n" + syntax_output

        return result + "\nsyntax_check: UNKNOWN\n" + syntax_output

    def _replace_by_lines(
        self, fp: Path, rel: str, original: str,
        start_line: int, end_line: int, new_text: str,
    ) -> str:
        """Line mode: replace lines [start_line..end_line] (1-based inclusive) with new_text."""
        lines = original.splitlines(keepends=True)
        total = len(lines)

        if start_line < 1 or end_line < start_line:
            return f"[ERROR] Invalid line range: start_line={start_line}, end_line={end_line}"
        if start_line > total:
            return f"[ERROR] start_line={start_line} exceeds file length ({total} lines)"
        # clamp end_line to file length
        end_line = min(end_line, total)

        # Build new content
        before = lines[:start_line - 1]
        after = lines[end_line:]

        # Ensure new_text ends with newline if there's content after it
        replacement = new_text
        if after and replacement and not replacement.endswith("\n"):
            replacement += "\n"

        new_content = "".join(before) + replacement + "".join(after)

        # Write back
        fp.write_text(new_content, encoding="utf-8")

        replaced_count = end_line - start_line + 1
        new_line_count = new_text.count("\n") + (1 if new_text and not new_text.endswith("\n") else 0)

        # 生成代码预览
        new_lines = new_content.splitlines()
        preview_start = max(0, start_line - 3)  # 2 lines before (0-based)
        new_end_line = start_line - 1 + new_line_count
        preview_end = min(len(new_lines), new_end_line + 2)
        max_preview = 50
        if preview_end - preview_start > max_preview:
            preview_end = preview_start + max_preview
        preview_parts = []
        for ln in range(preview_start, preview_end):
            preview_parts.append(f"{ln + 1:>6} | {new_lines[ln]}")
        if preview_end < len(new_lines) and preview_end - preview_start >= max_preview:
            preview_parts.append(f"       ... (use read_code for full content)")
        preview = "\n".join(preview_parts)

        return (
            f"Updated {rel}: replaced lines {start_line}-{end_line} ({replaced_count} lines -> {new_line_count} lines)\n"
            f"affected_lines: {start_line}-{new_end_line}\n"
            f"{preview}"
        )

    def _replace_batch(self, fp: Path, rel: str, original: str, replacements: list) -> str:
        """
        Batch mode: apply multiple replacements in one pass.

        Line-mode items are sorted bottom-up (highest start_line first) and applied
        first so that earlier line numbers stay stable. Text-mode items are applied
        after on the resulting content sequentially.
        """
        line_ops = []   # (start_line, end_line, new_text)
        text_ops = []   # (old_text, new_text, replace_all)

        for i, item in enumerate(replacements):
            if not isinstance(item, dict):
                return f"[ERROR] replacements[{i}] must be an object"
            nt = item.get("new_text")
            if not isinstance(nt, str):
                return f"[ERROR] replacements[{i}].new_text must be a string"

            sl = item.get("start_line")
            el = item.get("end_line")
            if sl is not None and el is not None:
                line_ops.append((int(sl), int(el), nt))
            else:
                ot = item.get("old_text")
                if not isinstance(ot, str) or ot == "":
                    return f"[ERROR] replacements[{i}]: text mode requires non-empty old_text"
                ra = bool(item.get("replace_all", False))
                text_ops.append((ot, nt, ra))

        content = original
        results = []

        # ── Apply line-mode ops bottom-up ──
        if line_ops:
            # Validate no overlaps
            line_ops.sort(key=lambda x: x[0])
            for j in range(1, len(line_ops)):
                prev_end = line_ops[j - 1][1]
                cur_start = line_ops[j][0]
                if cur_start <= prev_end:
                    return (
                        f"[ERROR] Overlapping line ranges: "
                        f"[{line_ops[j-1][0]}-{line_ops[j-1][1]}] and [{cur_start}-{line_ops[j][1]}]"
                    )

            lines = content.splitlines(keepends=True)
            total = len(lines)

            # Apply from bottom to top
            for sl, el, nt in reversed(line_ops):
                if sl < 1 or el < sl:
                    return f"[ERROR] Invalid line range: {sl}-{el}"
                if sl > total:
                    return f"[ERROR] start_line={sl} exceeds file length ({total} lines)"
                el = min(el, total)

                before = lines[:sl - 1]
                after = lines[el:]
                replacement = nt
                if after and replacement and not replacement.endswith("\n"):
                    replacement += "\n"
                lines = before + replacement.splitlines(keepends=True) + after
                old_count = el - sl + 1
                new_count = nt.count("\n") + (1 if nt and not nt.endswith("\n") else 0)
                results.append(f"lines {sl}-{el} ({old_count} -> {new_count} lines)")

            content = "".join(lines)
            results.reverse()  # restore top-down order for output

        # ── Apply text-mode ops sequentially ──
        for ot, nt, ra in text_ops:
            if ra:
                count = content.count(ot)
                content = content.replace(ot, nt)
            else:
                count = 1 if ot in content else 0
                content = content.replace(ot, nt, 1)
            results.append(f"text '{ot[:30]}...' -> {count} occurrence(s)")

        fp.write_text(content, encoding="utf-8")
        summary = "; ".join(results)
        return f"Updated {rel}: {len(replacements)} replacements [{summary}]"

    async def run(self):
        logger.info(f"[coding-tools] Starting MCP server (stdio)")
        logger.info(f"[coding-tools] Project dir: {self.project_dir}")
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )
