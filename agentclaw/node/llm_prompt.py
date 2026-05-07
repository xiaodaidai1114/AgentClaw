"""
LLM Prompt 构建与图像处理工具函数

从 llm.py 中提取的辅助函数和常量，包括：
- 图像输入标准化 / 自动检测
- 运行时环境快照构建
- Agentic prompt 模板与提醒常量
- 项目目录树生成
"""

from __future__ import annotations
from typing import Any, List, Optional, TYPE_CHECKING
import os
import sys

from agentclaw.logger.config import get_logger
from agentclaw.model.vision import ImageInput
from agentclaw.runtime_paths import resolve_runtime_path_context

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


def _normalize_images(images: Any) -> Optional[List[ImageInput]]:
    """
    将各种格式的图像输入标准化为 ImageInput 列表

    支持格式：
    - None / 空字符串 / 空列表 -> None
    - ImageInput 对象 -> [ImageInput]
    - List[ImageInput] -> 原样返回
    - str (URL 或 base64) -> [ImageInput]
    - List[str] -> [ImageInput, ...]
    """
    if not images:
        return None

    # 单个 ImageInput
    if isinstance(images, ImageInput):
        return [images]

    # 列表
    if isinstance(images, list):
        if not images:
            return None
        result = []
        for img in images:
            if isinstance(img, ImageInput):
                result.append(img)
            elif isinstance(img, str) and img:
                result.append(_str_to_image_input(img))
        return result if result else None

    # 单个字符串
    if isinstance(images, str) and images:
        return [_str_to_image_input(images)]

    return None


def _str_to_image_input(s: str) -> ImageInput:
    """
    将字符串转换为 ImageInput

    支持格式：
    - URL (http:// 或 https://)
    - data URL (data:image/...)
    - 本地文件路径
    - 纯 base64 字符串
    """
    s = s.strip()
    if s.startswith(("http://", "https://")):
        return ImageInput.from_url(s)
    elif s.startswith("data:"):
        return ImageInput.from_base64(s)
    elif os.path.isfile(s):
        # 本地文件路径
        return ImageInput.from_file(s)
    else:
        # 假设是纯 base64
        return ImageInput.from_base64(s)


def _get_tool_result_max_length() -> int:
    """获取工具结果最大长度（从环境变量读取）"""
    return int(os.getenv("TOOL_RESULT_MAX_LENGTH", "20000"))


# 常见图片扩展名
_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.ico'}


def _auto_detect_images(state: dict) -> Optional[List[ImageInput]]:
    """
    自动检测 state 中的图像文件（用于未设置 images_key 时的自动发现）

    扫描 state 中的值，查找：
    - 图片文件路径（以常见图片扩展名结尾）
    - data URL（data:image/...）
    - http(s) URL 指向图片

    跳过内部字段（__xxx__）
    """
    found = []
    for key, value in state.items():
        if key.startswith("__"):
            continue
        if isinstance(value, str) and value:
            v = value.strip()
            # 检查是否是图片文件路径
            if any(v.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS):
                if os.path.isfile(v) or v.startswith(("http://", "https://", "data:")):
                    found.append(v)
            # 检查 data URL
            elif v.startswith("data:image/"):
                found.append(v)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    item = item.strip()
                    if any(item.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS):
                        if os.path.isfile(item) or item.startswith(("http://", "https://", "data:")):
                            found.append(item)
                    elif item.startswith("data:image/"):
                        found.append(item)

    return _normalize_images(found) if found else None


def _get_max_context_messages() -> int:
    """获取默认最大历史消息条数（从环境变量读取，0 表示不限制）"""
    return int(os.getenv("MAX_CONTEXT_MESSAGES", "0"))


def _get_max_tool_rounds() -> int:
    """获取最大工具调用轮数（从环境变量读取，0 表示不限制）"""
    return int(os.getenv("MAX_TOOL_ROUNDS", "0"))


def _get_agentclaw_url() -> str:
    """获取 AgentClaw 对自身 API 的可访问地址。"""
    for env_name in ("AGENTCLAW_URL", "AgentClaw_SERVER_BASE_URL"):
        server_base_url = os.getenv(env_name, "").strip()
        if server_base_url:
            return server_base_url.rstrip("/")

    port = os.getenv("PORT", "8000")
    return f"http://127.0.0.1:{port}"


def _build_runtime_env_snapshot(context: Optional["WorkflowContext"] = None) -> str:
    runtime_paths = resolve_runtime_path_context(
        workflow_id=getattr(context, "workflow_id", None) if context else None,
        skill_manager=getattr(context, "skill_manager", None) if context else None,
    )

    server_base_url = _get_agentclaw_url()

    # 平台信息
    platform = sys.platform  # win32 / linux / darwin

    command_style_hint = "Use POSIX shell commands like python3, ls, cat, bash, and sh."
    if platform == "win32":
        command_style_hint = (
            "Use Windows-native commands like python, py -3, dir, type, powershell, start, and explorer.exe."
        )

    # GUI 可用性检测
    gui_available = False
    if platform == "win32":
        gui_available = True  # Windows 桌面通常有 GUI
    elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        gui_available = True  # Linux/Mac 有显示服务器

    def _display(path: Optional[str], fallback: str = "<not configured>") -> str:
        return path or fallback

    return (
        f"- python_executable: {sys.executable}\n"
        f"- python_package_install_command: {sys.executable} -m pip install <package>\n"
        "- python_environment_note: Use python_executable for Python commands and package installs. Do not assume a sibling pip executable exists.\n"
        f"- cwd: {runtime_paths.cwd}\n"
        f"- project_dir: {runtime_paths.project_dir}\n"
        f"- platform: {platform}\n"
        f"- command_style_hint: {command_style_hint}\n"
        f"- gui_available: {gui_available}\n"
        f"- server_base_url: {server_base_url}\n"
        f"- skill_tools_working_dir: {runtime_paths.skill_tools_working_dir}\n"
        f"- coding_tools_project_dir: {runtime_paths.coding_tools_project_dir}\n"
        f"- skills_dir: {_display(runtime_paths.skills_dir)}\n"
        f"- models_config: {_display(runtime_paths.models_config)}\n"
        f"- mcp_config: {_display(runtime_paths.mcp_config)}\n"
        f"- env_file: {_display(runtime_paths.env_file)}\n"
        f"- workflow_memory_path: {_display(runtime_paths.workflow_memory_path, '<unavailable>')}"
    )


# Agentic style system prompt template (inspired by Claude Code)
SKILL_FIRST_CONSTRUCTION_PROTOCOL = """Skill-first construction protocol:
- Pattern before implementation: for workflows, agents, tools, prompts, structured automations, or project artifacts, identify the task pattern before choosing code-level tactics.
- When a relevant skill applies, the skill defines the default architecture shape; extract its workflow shape, validation gates, evidence flow, and deterministic/LLM responsibility split before coding.
- Following a skill does not mean copying it blindly; use creativity inside the skill frame unless a concrete project fact justifies a deliberate deviation.
- Correct architecture is more important than the first runnable draft for agent/workflow creation tasks.
- Do not replace discovery with assumptions: use reasonable defaults for low-risk operational choices, but not for domain facts that should be discovered, validated, or grounded in real project state.
- Domain facts include schemas, table columns, API contracts, business rules, permissions, credentials, external service behavior, and current runtime state.
- Use LLM nodes where semantics matter: summarization, judgment, explanation, recommendations, risk interpretation, narrative reports, ambiguous mapping, and human-facing synthesis should usually be handled by an LLMNode.
- Before writing or modifying project artifacts, privately check whether node boundaries, validation gates, output contracts, and evidence flow visibly reflect the relevant skill.
"""


SKILL_USAGE_PROTOCOL = """# Available Skills

## Skill Usage Protocol

Treat the skills below as execution guides that can unlock tools, workflows, references, and task-specific constraints.
Following a skill means more than reading or mentioning it: your workflow shape, validation gates, node boundaries, and output contract should visibly reflect the relevant skill unless a concrete project fact justifies a deliberate deviation.
When a skill is clearly relevant to the current task, read it before relying on its workflow or related tooling.
When available skills may provide execution workflows, platform rules, validation steps, or tool usage guidance, read the most relevant ones before acting.
For requests to create, inspect, update, debug, or validate project artifacts such as agents, workflows, prompts, personas, nodes, tools, skills, configs, or code, read the closest relevant skill before making changes.
If a skill contains a routing table or points to references for the current task pattern, those references are design-time inputs, not last-resort repair manuals.
Use creativity inside the skill frame: adapt names, prompts, code details, and user experience, but do not skip the skill's evidence gates, validation gates, or LLM/deterministic responsibility split without a project-backed reason.
Use direct replies only for pure conversation or lightweight messages that do not require project actions, platform operations, or skill-governed workflows.
Prefer reading the smallest relevant set of skills first, then continue execution.

## Guidelines

- Skills contain execution patterns, validation gates, and tool usage requirements.
- Skill documents may reference additional files containing API contracts, design principles, and detailed specifications; when the skill says a reference matches the task pattern, read that reference before design or coding.
- Use skill-specified tools where applicable.
- Follow validation gates in order (syntax → compile → register → runtime).
- For workflow files, use verified APIs only (Workflow/LLMNode/add_edge/publish).
- For existing files, prefer local edit tools (`replace_in_file`/`update_code`) over full-file rewrites when possible.
"""


AGENTIC_PROMPT_TEMPLATE = """{original_prompt}

You are an intelligent agent.

Current time: {{__current_time__}}
Runtime path context:
{{__runtime_env_snapshot__}}

Execution protocol:
1. UNDERSTAND: Read the user's request carefully and identify the parts that can already be acted on.
2. CHOOSE A STRONG NEXT STEP: Use the available tools, skills, files, and runtime context to decide the most promising next action.
3. ORGANIZE WHEN USEFUL: If the task is multi-step, open-ended, or benefits from visible tracking, use TodoWrite to structure the work.
4. EXPLORE THROUGH ACTION: Gather the missing context by reading skills, checking files, calling tools, querying APIs, searching, browsing, or retrieving knowledge as needed.
5. EXECUTE AND LEARN: Perform concrete steps, read the outputs carefully, and use the results to decide what to do next.
6. COMBINE CAPABILITIES: Coordinate planning, skill reading, coding, browsing, searching, file operations, APIs, and knowledge retrieval when that helps solve the task.
7. DELIVER PROGRESS: Move the task forward as far as possible and provide the most useful result you can reach.

Decision-making:
- Make informed decisions based on context and common practices when details are unspecified.
- Use reasonable defaults when the user's intent is clear and the choice is low risk.
- When progress depends on missing information, permissions, or decisions from the user, explain what you discovered, what you tried, and ask for the next input.
- Keep communication concise: briefly state the next step, then continue execution.

Core principles:
- When the environment already exposes relevant tools, skills, files, or APIs, begin from the most actionable path.
- Prefer concrete progress over abstract hesitation.
- Use available skills as operating guides whenever they can help execute the task.
- Treat each successful or failed tool call as information that improves the next attempt.
- For creative, role-based, or research-heavy tasks, build the result from gathered context, references, and explicit user intent.
- Match command syntax and path conventions to the reported `platform` and `command_style_hint` in runtime context.
- For Python package installation, use the exact `python_package_install_command` pattern from runtime context (`python_executable -m pip install ...`); do not call a guessed `pip` path.
- Do not assume the environment is Linux-only or Windows-only unless a tool explicitly returns that limitation.
- When `gui_available` is true, browser and desktop automation may be available; verify with tools before concluding they cannot be used.
- Treat `project_dir` as the authoritative project root. For file tools, prefer the exact paths from runtime context; `skill_tools_working_dir` is the base for skill-tools file operations.
- For code edits: use targeted changes and validate with `syntax_check` + `py_compile`.
- Use environment variables for secrets and relative paths for files.
- When an image is useful in the final answer, display it with standard Markdown image syntax (`![alt text](URL-or-path)`). The admin chat UI can render Markdown images, including HTTP(S), data URLs, and served file/download URLs.
- Prefer tool-provided `image_markdown`, `markdown_images`, `public_urls`, `download_url`, or signed `/api/files/...?token=...` URLs for image display; do not embed local absolute filesystem paths such as `/home/...` because the browser UI cannot load them.
- Report status accurately: `completed` / `partial` / `blocked`.
""" + "\n\n" + SKILL_FIRST_CONSTRUCTION_PROTOCOL


PLANNING_REMINDER = """<planning_protocol>
Planning Guide:
1. Use TodoWrite when the task has multiple moving parts, benefits from visible progress, or requires sustained exploration.
2. Keep the plan short, practical, and execution-oriented.
3. Update the plan as you learn so it stays aligned with the current state of the task.
4. Use the plan to coordinate reading skills, gathering references, calling tools, verifying results, and delivering the final outcome.
</planning_protocol>
"""

DELIVERY_HINT_REMINDER = """<delivery_hint>
Workflow quality checklist:
1) Verify registration and bootstrap
2) Perform minimal runtime smoke check
Report `partial` when any item fails or is incomplete.
</delivery_hint>"""

_CODE_EXTENSIONS = {
    ".py", ".vue", ".js", ".ts", ".jsx", ".tsx", ".md",
    ".json", ".yaml", ".yml", ".toml", ".css", ".html",
}
_IGNORE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    "dist", "build", ".next", ".nuxt", "backup", ".claude",
}
_MAX_TREE_ENTRIES = 300


def _build_project_tree(project_dir: str, max_depth: int = 4) -> str:
    """生成项目代码文件的目录树（轻量级，只包含常见代码文件）"""
    from pathlib import Path
    root = Path(project_dir)
    if not root.is_dir():
        return ""
    lines: list[str] = []
    count = 0

    def _walk(current: Path, depth: int, prefix: str):
        nonlocal count
        if depth > max_depth or count >= _MAX_TREE_ENTRIES:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in _IGNORE_DIRS and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file() and e.suffix in _CODE_EXTENSIONS]
        items = dirs + files
        for i, item in enumerate(items):
            if count >= _MAX_TREE_ENTRIES:
                return
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                count += 1
                extension = "    " if is_last else "│   "
                _walk(item, depth + 1, prefix + extension)
            else:
                lines.append(f"{prefix}{connector}{item.name}")
                count += 1

    _walk(root, 0, "")
    if not lines:
        return ""
    return "\n".join(lines)
