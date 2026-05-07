"""
Built-in Agent - 内置智能体

三节点管线架构：
  user_input ──┬── tool_filter  ──┬── agent
               └── skill_filter ──┘

- tool_filter 和 skill_filter 并行执行，各用一次快速 LLM 调用筛选相关工具/技能
- agent 节点只加载筛选后的工具和技能，避免上下文爆炸
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, TYPE_CHECKING

from agentclaw import Workflow
from agentclaw.node.llm import LLMNode
from agentclaw.node.custom import CustomNode
from agentclaw.logger.config import get_logger
from agentclaw.config import get_config
from agentclaw.version import get_version

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────
# 预过滤节点
# ──────────────────────────────────────────────────────────────

_TOOL_FILTER_PROMPT = """\
You are a tool relevance classifier. Given the user's task, select which tool categories are POSSIBLY needed.
Reply with ONLY a JSON array of integer ids, no explanation. Example: [1,3]

Task: {task}

Available tool categories:
{tool_categories}
Important ids: {important_ids}
Rules:
- Be INCLUSIVE: select ALL categories that MIGHT be relevant, even if only partially.
- When in doubt, INCLUDE the category rather than exclude it.
- Prefer the shortest sufficient id list.
- skill-tools should almost always be included.
- Include coding-tools when the task needs source-code inspection, edits, tests, or project-file changes.
- For open-ended, research-heavy, creative, role-based, or reference-driven tasks, include any tool categories that may help gather context or execute the task.
- If external information may help the task, include browser-related or search-related categories when available.
- When exploration is likely to help, prefer a broader relevant tool set.
- If the task involves creating/building/registering an agent or workflow, MUST include the ids for coding-tools + skill-tools.
- If the task only runs or queries an existing AgentClaw workflow or platform capability, skill-tools is usually sufficient; do not include coding-tools just to discover API usage.
"""

_SKILL_FILTER_PROMPT = """\
You are a skill relevance classifier. Given the user's task, select which skills are POSSIBLY relevant.
Reply with ONLY a JSON array of integer ids, no explanation. Empty array [] if none match.

Task: {task}

Available skills:
{skill_list}
Important ids: {important_ids}
Rules:
- Be INCLUSIVE: select ALL skills that MIGHT be relevant, even if only partially related.
- When in doubt, INCLUDE the skill rather than exclude it.
- Prefer the shortest sufficient id list.
- coding_skill should almost always be included for any coding/development task.
- Prefer agentclaw_api over coding_skill for running, querying, scheduling, or operating existing AgentClaw workflows and platform capabilities.
- For unfamiliar, research-heavy, platform-oriented, or creative tasks, include any skill that may provide execution guidance, references, workflows, or useful tooling.
- When a skill may help gather context or expand the solution path, include it.
- Prefer inclusive matching when a skill could help the task move forward.
"""


BUILTIN_AGENT_SYSTEM_PROMPT = """You are a proactive execution-oriented AI assistant.
Your goal is to satisfy the user's request as fully as possible by using the available skills, tools, files, APIs, knowledge bases, and runtime environment.

Working style:
- Start from the parts of the request that are already actionable.
- When the task benefits from decomposition or visible progress, use TodoWrite to organize the work and keep momentum.
- When relevant skills are available, read and use them as execution guides.
- If an available AgentClaw workflow already satisfies the request, use agentclaw_api to run it through the internal relay instead of searching source code or README for API examples.
- For agent, workflow, tool, prompt, automation, or project-artifact creation, correct architecture is more important than the first runnable draft.
- When useful tools or capabilities are available, prefer taking a concrete next step and learn from the result.
- Treat tool outputs as feedback for the next move, and keep advancing toward the user's goal.
- For research, writing, role-based, reference-driven, or open-ended tasks, gather grounding information first and then produce the result.
- Keep communication concise: briefly state what you are going to do, then continue execution.
- When the user's intent is clear, use reasonable defaults for low-risk operational choices and keep making progress, but not for schemas, table columns, business rules, permissions, or external contracts.
- When progress depends on missing information, permissions, or decisions from the user, share the progress so far and ask for the missing input.
"""


def _no_thinking_kwargs(llm_manager) -> dict:
    """
    构建禁用思考/推理的 kwargs，传给 llm_manager.invoke()。

    原理：invoke() 内部先设置 config.extra_body，再 create_kwargs.update(kwargs)，
    所以我们在 kwargs 里传 extra_body 会覆盖 config 级的设置。
    为了不丢掉 config 里其他 extra_body 字段，先 copy 再 merge。
    """
    try:
        config = llm_manager.get_model()
        base = dict(config.extra_body) if config.extra_body else {}
    except Exception:
        base = {}
    # 通用关闭思考的字段（deepseek / qwen 等 OpenAI 兼容模型）
    base["enable_thinking"] = False
    return {"extra_body": base}


def _fast_filter_kwargs(llm_manager) -> dict:
    """Filter nodes only need a tiny deterministic JSON array."""
    kwargs = _no_thinking_kwargs(llm_manager)
    kwargs["temperature"] = 0
    kwargs["max_tokens"] = 64
    return kwargs


def _compact_text(text: Any, max_len: int = 72) -> str:
    """Normalize whitespace and trim noisy descriptions."""
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3].rstrip() + "..."


def _build_indexed_options(items: List[tuple[str, str]], *, max_desc_len: int = 72) -> tuple[str, Dict[str, str]]:
    """Build compact numbered options for fast classification."""
    lines: List[str] = []
    index_to_name: Dict[str, str] = {}
    for idx, (name, desc) in enumerate(items, 1):
        key = str(idx)
        index_to_name[key] = name
        short_desc = _compact_text(desc, max_desc_len)
        if short_desc:
            lines.append(f"[{key}] {name}: {short_desc}")
        else:
            lines.append(f"[{key}] {name}")
    return "\n".join(lines), index_to_name


def _format_important_ids(index_to_name: Dict[str, str], names: List[str]) -> str:
    pairs = [f"{name}=[{idx}]" for idx, name in index_to_name.items() if name in names]
    return ", ".join(pairs) if pairs else "none"


def _parse_json_array(text: str) -> List[Any]:
    """从 LLM 响应中提取 JSON 数组，容错处理。"""
    text = text.strip()
    # 找到第一个 [ 和最后一个 ]
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            arr = json.loads(text[start:end + 1])
            if isinstance(arr, list):
                return arr
        except json.JSONDecodeError:
            pass
    return []


def _resolve_selected_items(raw_items: List[Any], index_to_name: Dict[str, str]) -> List[str]:
    """Resolve compact numeric ids back to actual names, while keeping old name-array compatibility."""
    valid_names = set(index_to_name.values())
    selected: List[str] = []
    seen: set[str] = set()

    for item in raw_items:
        resolved = None
        if isinstance(item, int):
            resolved = index_to_name.get(str(item))
        else:
            value = str(item).strip()
            if not value:
                continue
            resolved = index_to_name.get(value)
            if resolved is None and value.isdigit():
                resolved = index_to_name.get(str(int(value)))
            if resolved is None and value in valid_names:
                resolved = value

        if resolved and resolved not in seen:
            seen.add(resolved)
            selected.append(resolved)

    return selected


class ToolFilterNode(CustomNode):
    """并行节点 1：筛选与任务相关的工具类别"""

    def __init__(self, **kwargs):
        super().__init__(id="tool_filter", output_to_user=False, description="正在筛选相关工具...", **kwargs)

    def process(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError  # 使用 async_execute

    async def async_execute(self, state: dict, context: "WorkflowContext") -> Dict[str, Any]:
        user_input = state.get("user_input", "")
        if not user_input or not context.llm_manager or state.get("__skip_filter__"):
            return {}

        # 动态收集全量工具类别（内置 + 用户 MCP）
        items: List[tuple[str, str]] = []

        # 1) 内置 MCP 服务器
        try:
            from agentclaw.mcp.builtin_servers.registry import BUILTIN_SERVERS
            for name, info in BUILTIN_SERVERS.items():
                items.append((name, info["description"]))
        except Exception:
            pass

        # 2) 用户自定义 MCP 服务器（从配置文件）
        try:
            cfg = get_config()
            if cfg.project.mcp_config:
                from pathlib import Path
                import json as json_mod
                mcp_path = Path(cfg.project.mcp_config)
                if mcp_path.exists():
                    mcp_data = json_mod.loads(mcp_path.read_text(encoding="utf-8"))
                    builtin_names = {name for name, _desc in items}
                    for name, srv_cfg in mcp_data.get("mcpServers", {}).items():
                        if name not in builtin_names:
                            desc = srv_cfg.get("description", name)
                            items.append((name, desc))
        except Exception:
            pass

        # 3) 框架内发布的 MCP 工具（函数 / ToolKit 直发）
        try:
            from agentclaw.mcp.token_manager import MCPServerRegistry

            builtin_names = {name for name, _desc in items}
            for server_name, tools in MCPServerRegistry.get_instance().get_published_tool_groups():
                if server_name in builtin_names:
                    continue
                tool_names = ", ".join(tool.name for tool in tools[:6])
                suffix = "..." if len(tools) > 6 else ""
                desc = f"Framework-published MCP tools: {tool_names}{suffix}"
                items.append((server_name, desc))
        except Exception:
            pass

        if not items:
            items = [
                ("skill-tools", "Python/shell execution"),
                ("coding-tools", "Code tools"),
                ("planning-tools", "Task planning"),
            ]

        tool_categories, index_to_name = _build_indexed_options(items, max_desc_len=64)
        important_ids = _format_important_ids(index_to_name, ["skill-tools", "coding-tools", "planning-tools"])

        prompt = _TOOL_FILTER_PROMPT.format(
            task=user_input,
            tool_categories=tool_categories,
            important_ids=important_ids,
        )
        try:
            response = await context.llm_manager.invoke(
                [{"role": "user", "content": prompt}],
                model_id="fast",
                **_fast_filter_kwargs(context.llm_manager),
            )
            text = str(response) if not isinstance(response, str) else response
            logger.info(f"tool_filter LLM 原始响应: {text!r}")
            raw_selected = _parse_json_array(text)
            selected = _resolve_selected_items(raw_selected, index_to_name)
            logger.info(f"tool_filter 解析结果: {selected!r}")
            # 确保 skill-tools 和 planning-tools 始终包含
            if "skill-tools" not in selected:
                selected.append("skill-tools")
            if "planning-tools" not in selected:
                selected.append("planning-tools")
            logger.info(f"tool_filter 最终选中: {selected}")
            result = {"__filtered_tools__": selected}
            logger.info(f"tool_filter 返回: {result}")
            return result
        except Exception as e:
            logger.warning(f"tool_filter LLM 调用失败，跳过过滤: {e}")
            return {}


class SkillFilterNode(CustomNode):
    """并行节点 2：筛选与任务相关的技能"""

    def __init__(self, **kwargs):
        super().__init__(id="skill_filter", output_to_user=False, description="正在筛选相关技能...", **kwargs)

    def process(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError  # 使用 async_execute

    async def async_execute(self, state: dict, context: "WorkflowContext") -> Dict[str, Any]:
        user_input = state.get("user_input", "")
        if not user_input or not context.llm_manager or state.get("__skip_filter__"):
            return {}

        # 收集所有可用技能（项目 + 内置）
        all_skills = []  # [(name, description)]

        if context.skill_manager:
            context.skill_manager.refresh()
            for skill in context.skill_manager.list():
                all_skills.append((skill.name, skill.description))

        try:
            from agentclaw.skills import get_builtin_skill_manager
            builtin_mgr = get_builtin_skill_manager(auto_init=True)
            if builtin_mgr:
                builtin_mgr.refresh()
                for skill in builtin_mgr.list():
                    if not any(s[0] == skill.name for s in all_skills):
                        all_skills.append((skill.name, skill.description))
        except Exception:
            pass

        if not all_skills:
            return {}

        # 构建技能列表供 LLM 筛选
        skill_list, index_to_name = _build_indexed_options(all_skills, max_desc_len=72)
        important_ids = _format_important_ids(index_to_name, ["coding_skill"])

        prompt = _SKILL_FILTER_PROMPT.format(
            task=user_input,
            skill_list=skill_list,
            important_ids=important_ids,
        )
        try:
            response = await context.llm_manager.invoke(
                [{"role": "user", "content": prompt}],
                model_id="fast",
                **_fast_filter_kwargs(context.llm_manager),
            )
            text = str(response) if not isinstance(response, str) else response
            raw_selected = _parse_json_array(text)
            selected_names = _resolve_selected_items(raw_selected, index_to_name)
            logger.info(f"skill_filter 选中: {selected_names}")
            return {"__filtered_skill_names__": selected_names}
        except Exception as e:
            logger.warning(f"skill_filter LLM 调用失败，跳过过滤: {e}")
            return {}


class BuiltinInitNode(CustomNode):
    """内置智能体入口节点，用于条件分流是否执行智能筛选。"""

    def __init__(self, **kwargs):
        super().__init__(id="builtin_init", output_to_user=False, description="初始化智能体", **kwargs)

    def process(self, **kwargs) -> Dict[str, Any]:
        return {}


class SmartPreFilterNode(CustomNode):
    """并行执行技能/工具筛选，并合并筛选结果。"""

    def __init__(self, **kwargs):
        super().__init__(id="smart_prefilter", output_to_user=False, description="正在智能筛选...", **kwargs)
        self._tool_filter = ToolFilterNode()
        self._skill_filter = SkillFilterNode()

    def process(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError  # 使用 async_execute

    async def async_execute(self, state: dict, context: "WorkflowContext") -> Dict[str, Any]:
        if state.get("__skip_filter__"):
            return {}

        results = await asyncio.gather(
            self._tool_filter.async_execute(state, context),
            self._skill_filter.async_execute(state, context),
            return_exceptions=True,
        )

        merged: Dict[str, Any] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"智能筛选节点执行失败，已跳过: {result}")
                continue
            if isinstance(result, dict):
                merged.update(result)
        return merged


# ──────────────────────────────────────────────────────────────
# 工作流组装
# ──────────────────────────────────────────────────────────────

def create_builtin_workflow() -> Workflow:
    """
    创建内置智能体工作流（三节点管线）

    Returns:
        配置好的 Workflow 实例
    """
    config = get_config()
    project = config.project

    workflow_config = {
        "id": "__builtin__",
        "name": "AgentClaw",
        "version": get_version(),
        "description": "你的全能 AI 助手，可以构建智能体、执行代码、读写文件、处理文档、调用 API",
        "timeout": 0,
        "welcome": "你好！我是你的全能 AI 助手，可以构建智能体、执行代码、读写文件、处理文档、调用 API，你说什么我就做什么",
        "user_input": "user_input",
        "inputs": {
            "user_input": {"type": "string", "required": True, "description": "发送给 AI 助手的消息"},
            "model": {"type": "string", "required": False, "description": "指定使用的模型 ID（留空使用默认模型）"},
        },
    }

    if project.skills_dir:
        workflow_config["skills_dir"] = str(project.skills_dir)
    if project.mcp_config:
        workflow_config["mcp_config"] = str(project.mcp_config)
    if project.models_config:
        workflow_config["models_config"] = str(project.models_config)

    logger.info(
        f"AgentClaw 配置: skills={project.skills_dir}, "
        f"mcp={project.mcp_config}, models={project.models_config}"
    )

    workflow = Workflow(**workflow_config)

    # ── 节点 1：初始化与分流 ──
    init_node = BuiltinInitNode()

    # ── 节点 2：智能预过滤（并行执行技能/工具筛选） ──
    prefilter_node = SmartPreFilterNode()

    # ── 节点 3：主智能体 ──
    agent_node = LLMNode(
        id="agent",
        description="智能体思考中...",
        system_prompt=BUILTIN_AGENT_SYSTEM_PROMPT,
        user_prompt="{user_input}",
        agent_style="agentic",
        skills="*",
        enable_builtin_skills=True,
        tools="*",
        enable_builtin_tools=True,
        enable_memory=True,
        stream=True,
        output_to_user=True,
        max_context_messages=30,
        output_key="answer",
        # 从上游 filter 节点读取预过滤结果
        tools_filter_key="__filtered_tools__",
        skills_filter_key="__filtered_skill_names__",
    )

    # 记录本次请求的实际模型选择，但不要写入 agent_node.model_id。
    # model_id 一旦被写入节点，会变成固定节点模型，导致右上角请求级模型切换失效。
    original_execute = agent_node._do_execute
    async def execute_with_model(state, context):
        if context.llm_manager:
            runtime_model_id = getattr(context, "runtime_model_id", None)
            current_model_id = getattr(context.llm_manager, "_current_model_id", None)
            logger.info(f"builtin agent 使用模型: {runtime_model_id or current_model_id}")
        return await original_execute(state, context)
    agent_node._do_execute = execute_with_model

    # ── 组装 DAG ──
    workflow.add_node(init_node)
    workflow.add_node(prefilter_node)
    workflow.add_node(agent_node)

    workflow.add_edge("__start__", "builtin_init")
    workflow.add_conditional_edge(
        "builtin_init",
        condition=lambda state: "agent" if state.get("__skip_filter__") else "smart_prefilter",
        targets={
            "agent": "agent",
            "smart_prefilter": "smart_prefilter",
        },
    )
    workflow.add_edge("smart_prefilter", "agent")

    return workflow


def register_builtin_workflow() -> None:
    """注册内置工作流到 WorkflowRegistry"""
    try:
        workflow = create_builtin_workflow()
        workflow.publish(stream=True, require_auth=False)
        logger.info("AgentClaw 已注册: __builtin__")
    except Exception as e:
        logger.error(f"AgentClaw 注册失败: {e}")
        import traceback
        traceback.print_exc()
