"""
LLMNode - LLM 调用节点
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union, TYPE_CHECKING
import re
import json
import os
import asyncio
import sys
import time
import string
from collections import OrderedDict

from agentclaw.node.base import BaseNode
from agentclaw.exceptions import NodeExecutionError, WorkflowCancelledError
from agentclaw.logger.config import get_logger
from agentclaw.model.vision import ImageInput
from agentclaw.runtime_paths import resolve_runtime_path_context
from agentclaw.runtime.context_compressor import ContextCompressor

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)

# harness_final 退化检测（见 LLMNode._is_final_response_degraded）：harness_final 是无工具路径，
# 若模型在该路径仍输出工具调用（DSML）被拦截，最终回复会为空/极短，用户会感知“卡住”。
# 检测到退化时回退 continue，让 agent 用工具真正完成，而非丢弃后给空回复。
_HARNESS_FINAL_DEGRADED_MAX_LEN = 20
_HARNESS_FINAL_FALLBACK_MAX = 2  # 最多回退次数，防死循环


def _csv_env_set(name: str) -> set[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def apply_public_tool_policy(
    tool_schemas: list[dict] | None,
    *,
    public_mode: bool,
    builtin_tool_names: set[str],
) -> list[dict] | None:
    if not public_mode or not tool_schemas:
        return tool_schemas

    policy = os.getenv("AGENTCLAW_PUBLIC_TOOL_POLICY", "allow").strip().lower() or "allow"
    if policy == "allow":
        return tool_schemas
    if policy == "block_all":
        return []
    if policy != "block_builtin":
        return tool_schemas

    allowed_builtin_tools = _csv_env_set("AGENTCLAW_PUBLIC_ALLOWED_BUILTIN_TOOLS")
    return [
        schema
        for schema in tool_schemas
        if (
            schema.get("function", {}).get("name", "") not in builtin_tool_names
            or schema.get("function", {}).get("name", "") in allowed_builtin_tools
        )
    ]


class _SafePromptFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _safe_format_prompt(template: str, values: dict) -> str:
    formatter = string.Formatter()
    return formatter.vformat(template, (), _SafePromptFormatDict(values))


def _compact_capability_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_capability_value(value: Any, limit: int = 80) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        text = str(value)
    return _compact_capability_text(text, limit)


def _summarize_inputs_config(inputs_config: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(inputs_config, dict):
        return []

    raw_inputs = inputs_config.get("inputs")
    if not isinstance(raw_inputs, list):
        return []

    lines: list[str] = []
    for raw_input in raw_inputs[:limit]:
        if not isinstance(raw_input, dict):
            continue
        name = _compact_capability_text(raw_input.get("name"), 80)
        if not name:
            continue

        input_type = _compact_capability_text(raw_input.get("type") or "any", 40)
        required = "required" if raw_input.get("required") else "optional"
        parts = [f"{name}: {input_type}", required]

        description = _compact_capability_text(raw_input.get("description"), 160)
        if description:
            parts.append(f"description={description}")

        if raw_input.get("default") is not None:
            parts.append(f"default={_format_capability_value(raw_input.get('default'))}")

        constraints = raw_input.get("constraints")
        if isinstance(constraints, dict):
            for key in ("choices", "min", "max", "minLength", "maxLength", "pattern", "accept", "maxSize"):
                if constraints.get(key) is not None:
                    parts.append(f"{key}={_format_capability_value(constraints[key])}")

        lines.append("    - " + ", ".join(parts))

    if len(raw_inputs) > limit:
        lines.append(f"    - ... {len(raw_inputs) - limit} more inputs")

    return lines


def _summarize_json_input_schema(input_schema: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(input_schema, dict):
        return []

    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return []

    required_fields = set(input_schema.get("required") or [])
    lines: list[str] = []
    items = list(properties.items())
    for name, schema in items[:limit]:
        if not isinstance(schema, dict):
            continue
        field_name = _compact_capability_text(name, 80)
        input_type = _compact_capability_text(schema.get("type") or "any", 40)
        required = "required" if name in required_fields else "optional"
        parts = [f"{field_name}: {input_type}", required]

        description = _compact_capability_text(schema.get("description"), 160)
        if description:
            parts.append(f"description={description}")

        if schema.get("default") is not None:
            parts.append(f"default={_format_capability_value(schema.get('default'))}")

        if schema.get("enum") is not None:
            parts.append(f"choices={_format_capability_value(schema.get('enum'))}")

        lines.append("    - " + ", ".join(parts))

    if len(items) > limit:
        lines.append(f"    - ... {len(items) - limit} more inputs")

    return lines


def _build_workflow_input_capability_lines(workflow: Any) -> list[str]:
    input_lines: list[str] = []
    try:
        get_inputs_config = getattr(workflow, "get_inputs_config", None)
        if callable(get_inputs_config):
            input_lines = _summarize_inputs_config(get_inputs_config())
    except Exception as e:
        logger.debug(f"读取工作流 inputs_config 失败: {e}")

    if not input_lines:
        try:
            get_input_schema = getattr(workflow, "get_input_schema", None)
            if callable(get_input_schema):
                input_lines = _summarize_json_input_schema(get_input_schema())
        except Exception as e:
            logger.debug(f"读取工作流 input_schema 失败: {e}")

    if not input_lines:
        return []

    lines = ["  inputs:"]
    user_input_field = _compact_capability_text(getattr(workflow, "_user_input_field", None), 80)
    if user_input_field:
        lines.append(f"    user_input_field: {user_input_field}")
    lines.extend(input_lines)
    return lines

# 全局 builtin MCP manager 缓存（所有 LLMNode 实例共享）
# 避免 openclaw 和 __builtin__ 各自启动一套 skill-tools/coding-tools 等子进程
_shared_builtin_mcp_cache: Dict[str, Any] = {}
_shared_builtin_mcp_cache_sig: Dict[str, str] = {}
_shared_builtin_mcp_cache_lock = asyncio.Lock()



# --- 从拆分模块导入 ---
from agentclaw.node.llm_prompt import (
    _normalize_images,
    _auto_detect_images,
    _get_max_context_messages,
    _get_max_tool_rounds,
    _get_tool_result_max_length,
    _build_runtime_env_snapshot,
    _build_project_tree,
    AGENTIC_PROMPT_TEMPLATE,
    SKILL_USAGE_PROTOCOL,
    PLANNING_REMINDER,
    DELIVERY_HINT_REMINDER,
)
from agentclaw.node.llm_skills import (
    _build_skills_tree,
    _build_required_skill_reads,
    update_skill_reference_diagnostics,
)
from agentclaw.node.llm_tools import (
    ToolExecutionOutcome,
    _to_tool_execution_outcome,
    _tool_event_status,
    _truncate_tool_result,
    _filter_preferred_tool_overlaps,
    _execute_tool_batch_with_conflict_resolution,
    _dedupe_tool_schemas,
)
from agentclaw.runtime.harness import AgentRunHarness, ToolExecutionEnvironment, augment_tool_schemas_with_harness_risk
from agentclaw.runtime.harness.model_output import postprocess_model_output
from agentclaw.memory import build_memory_section, read_workflow_memory


def _repair_openai_tool_message_sequence(messages: list[dict[str, Any]], *, node_id: str = "") -> list[dict[str, Any]]:
    """Drop orphan tool-result messages that no longer have a prior assistant tool_call."""
    repaired: list[dict[str, Any]] = []
    available_tool_call_ids: set[str] = set()
    dropped_orphan_tools = 0

    for message in messages:
        if not isinstance(message, dict):
            repaired.append(message)
            continue

        role = message.get("role")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if not tool_call_id or tool_call_id not in available_tool_call_ids:
                dropped_orphan_tools += 1
                continue
            repaired.append(message)
            continue

        repaired.append(message)
        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict):
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        available_tool_call_ids.add(str(tool_call_id))

    if dropped_orphan_tools:
        logger.warning(
            "节点 %s 修复 OpenAI tool 消息序列: 丢弃孤立 tool 消息 %s 条",
            node_id or "unknown",
            dropped_orphan_tools,
        )
    return repaired


def _build_agentic_workflow_capabilities_section(current_workflow_id: Optional[str] = None) -> str:
    """Build a compact catalog of registered workflows for agentic routing."""
    try:
        from agentclaw.api.registry import WorkflowRegistry

        workflows = WorkflowRegistry.list_all()
    except Exception as e:
        logger.debug(f"构建工作流能力提示失败: {e}")
        return ""

    lines: list[str] = []
    seen: set[str] = set()
    for workflow in workflows:
        workflow_id = str(getattr(workflow, "id", "") or "").strip()
        if not workflow_id or workflow_id in seen:
            continue
        if workflow_id == "__builtin__" or workflow_id == current_workflow_id:
            continue
        if getattr(workflow, "inject_as_agentic_capability", True) is False:
            continue

        name = " ".join(str(getattr(workflow, "name", "") or "").split())
        description = " ".join(str(getattr(workflow, "description", "") or "").split())
        if not name and not description:
            continue

        seen.add(workflow_id)
        lines.append(f"- id: {workflow_id}")
        if name:
            lines.append(f"  name: {name[:120]}")
        if description:
            lines.append(f"  description: {description[:500]}")
        lines.extend(_build_workflow_input_capability_lines(workflow))

    if not lines:
        return ""

    return (
        "<agentclaw_workflow_capabilities>\n"
        "Available AgentClaw workflows are existing platform capabilities. "
        "If the user's request can be satisfied by one of them, use `agentclaw_api` "
        "to run that workflow through the internal relay. Internal calls must use "
        "`/_internal/*` and must not include Authorization headers or API keys. "
        "Do not search source code or README only to learn how to call an existing workflow.\n"
        + "\n".join(lines)
        + "\n</agentclaw_workflow_capabilities>"
    )

@dataclass
class LLMNode(BaseNode):
    """
    LLM 调用节点
    
    声明式调用 LLM，无需编写调用代码。
    
    Prompt 语法：
    - {variable}: 从 state 中取值
    - {@prompt_key}: 从 PromptManager 中引用提示词
    
    Example:
        LLMNode(
            name="analyze",
            system_prompt="分析用户输入的情感",
            output_format="json"
        )
    
    Note:
        - name 在工作流中必须唯一，用于日志追踪和状态存储
        - 使用 {@key} 可引用 PromptManager 中的提示词模板
    """
    
    # === Prompt 配置 ===
    system_prompt: Optional[str] = None     # 系统提示词（支持 {变量} 和 {@prompt_key} 引用）
    user_prompt: Optional[str] = None      # 用户消息模板
    
    # === Skills 配置 ===
    skills: Optional[Union[List[str], str]] = None  # 技能列表或 "*" 自动匹配
    enable_builtin_skills: bool = False      # 启用内置 skills（如 agent_creator）
    
    # === Agent 增强配置 ===
    enable_builtin_tools: bool = False      # 启用所有内置工具（skill-tools, coding-tools, browser-tools, computer-tools, download-tools 等），用户可在前端配置面板控制具体启用哪些
    agent_style: Literal["default", "agentic"] = "default"  # Agent 风格（agentic 模式注入增强提示词）
    
    # === 输出配置 ===
    output_format: Literal["text", "json"] = "text"
    output_to_user: bool = False            # LLM 节点默认不输出给用户（覆盖基类默认值）
    
    # === 模型配置 ===
    model_id: Optional[str] = None          # 指定模型，默认使用 LLMManager.default
    use_fast_model: bool = False            # 使用快速模型（小任务优化）
    stream: bool = False                    # 是否流式输出（默认关闭，调试模式下更稳定）
    model_params: Optional[Dict[str, Any]] = None  # 模型参数（temperature, top_p, max_tokens 等）
    
    # === 节点级降级配置 ===
    fallback_model_id: Optional[str] = None  # 节点级降级模型（覆盖全局配置）
    auto_fallback: Optional[bool] = None     # 节点级自动降级开关（None 表示使用全局配置）
    fallback_threshold: Optional[int] = None # 节点级失败阈值（None 表示使用全局配置）
    
    # === 工具调用 ===
    tools: Optional[Union[List[str], str]] = None  # 工具名称列表，或 "*" 使用所有工具
    tool_choice: Literal["auto", "required", "none"] = "auto"
    max_tool_rounds: Optional[int] = None   # 最大工具调用轮数（None 使用环境变量 MAX_TOOL_ROUNDS）
    
    # === 预过滤（由上游 filter 节点填充 state） ===
    tools_filter_key: Optional[str] = None      # state key → list of MCP server names to enable
    skills_filter_key: Optional[str] = None     # state key → list of skill names (摘要注入，LLM 自行 read_skill_file)

    # === 上下文控制 ===
    use_context: bool = True                # 是否加载历史消息
    save_to_context: bool = True            # 是否将对话写入历史（用于判断/分类节点可设为 False）
    max_context_messages: Optional[int] = None  # 最大历史条数（None 使用环境变量 MAX_CONTEXT_MESSAGES）

    # === 上下文压缩 ===
    enable_compression: bool = True         # 是否启用上下文压缩
    compression_threshold: int = 100000     # 压缩阈值（token 数）
    compression_model: Optional[str] = None  # 用于压缩的模型（None 使用默认模型）

    # === 图像支持 ===
    images_key: str = ""  # 图片在 state 中的 key，传入则尝试使用图片

    # === 文件注入 ===
    inject_files: Optional[bool] = None  # 注入 __files__ 到提示词（None=agent自动开启, True=强制, False=关闭）
    enable_memory: bool = False          # 启用工作流级 memory.md 动态注入

    # === 内部状态（运行时） ===
    _node_failure_count: int = field(default=0, init=False, repr=False)
    _node_is_fallback: bool = field(default=False, init=False, repr=False)

    @staticmethod
    def _builtin_mcp_signature(server_name: str, server_config: dict) -> str:
        payload = {"server": server_name, "config": server_config}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    async def _get_or_create_builtin_mcp_manager(
        self,
        cache_key: str,
        server_name: str,
        server_config: dict,
    ):
        """获取或创建可复用的内置 MCP Manager，避免每轮请求重复拉起子进程。

        使用模块级全局缓存，所有 LLMNode 实例共享同一套 builtin servers。
        """
        from agentclaw.mcp import MCPManager, MCPServerConfig

        signature = self._builtin_mcp_signature(server_name, server_config)

        async with _shared_builtin_mcp_cache_lock:
            manager = _shared_builtin_mcp_cache.get(cache_key)
            if manager and _shared_builtin_mcp_cache_sig.get(cache_key) == signature:
                try:
                    if server_name not in manager.list_servers():
                        await manager.connect(server_name)
                    return manager
                except Exception:
                    # 连接异常时回收旧 manager，随后重建
                    try:
                        await manager.disconnect_all()
                    except Exception:
                        pass

            manager = MCPManager()
            manager.add_server(MCPServerConfig.from_dict(server_name, server_config))
            await manager.connect(server_name)

            old_manager = _shared_builtin_mcp_cache.get(cache_key)
            if old_manager and old_manager is not manager:
                try:
                    await old_manager.disconnect_all()
                except Exception:
                    pass

            _shared_builtin_mcp_cache[cache_key] = manager
            _shared_builtin_mcp_cache_sig[cache_key] = signature
            return manager

    async def _push_buffered_stream_response(
        self,
        channel: Any,
        chunks: Optional[List[str]],
        response: Optional[str],
    ) -> None:
        """
        将工具模式下缓冲的文本重新按 chunk 推送到 OutputChannel。

        工具轮中我们不能提前把 chunk 直接暴露给用户，因为需要先判断该轮
        是否会产出 tool_calls。等轮次结束后，如果最终确定这些文本可见，
        就尽量按原始 chunk 逐条回放，而不是一次性 push 整段文本。
        """
        if not channel:
            return

        visible_chunks = [chunk for chunk in (chunks or []) if chunk]
        if visible_chunks:
            for chunk in visible_chunks:
                await channel.push_message(chunk, self.id)
                await asyncio.sleep(0)  # 让出控制权，使 SSE 消费 task 有机会逐 chunk 推送
            return

        if response:
            await channel.push_output(response, self.id)

    async def _push_model_error(self, error: Exception | str, model_id: str | None = None) -> None:
        from agentclaw.runtime.streaming import get_output_channel

        channel = get_output_channel()
        if channel and hasattr(channel, "push_model_error"):
            await channel.push_model_error(str(error), node=self.id, model_id=model_id)
            await asyncio.sleep(0)

    async def _push_harness_user_feedback(self, feedback: str, batch_id: str | None = None) -> None:
        if not self.output_to_user:
            return
        from agentclaw.runtime.streaming import get_output_channel

        channel = get_output_channel()
        if channel:
            if hasattr(channel, "push_harness_feedback"):
                await channel.push_harness_feedback(feedback, batch_id=batch_id, node=self.id)
            else:
                await channel.push_output(feedback, self.id)
            await asyncio.sleep(0)

    def _record_skill_reference_diagnostics(
        self,
        state: dict,
        *,
        tool_calls: list[Any],
        round_tool_results: list[dict[str, Any]],
    ) -> None:
        for diagnostic_warning in update_skill_reference_diagnostics(
            state,
            tool_calls=tool_calls,
            round_tool_results=round_tool_results,
            node_id=self.id,
        ):
            logger.warning(diagnostic_warning)
        diagnostics = state.get("__skill_reference_diagnostics__")
        if isinstance(diagnostics, dict):
            logger.info(
                "节点 %s skill/reference diagnostics: read_skills=%s read_references=%s "
                "write_before_pattern_reference_warned=%s",
                self.id,
                diagnostics.get("read_skills", []),
                diagnostics.get("read_references", []),
                bool(diagnostics.get("write_before_pattern_reference_warned")),
            )
    
    async def _do_execute(self, state: dict, context: WorkflowContext) -> dict:
        """执行 LLM 调用"""
        if not context.llm_manager:
            raise NodeExecutionError(self.id, "LLMManager 未配置，请检查 models.json 是否存在")

        # 注入系统状态变量
        from datetime import datetime
        state["__current_time__"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        if self.agent_style == "agentic":
            state["__runtime_env_snapshot__"] = _build_runtime_env_snapshot(context)

        # 获取工具定义
        tool_schemas = None
        effective_toolkit = context.toolkit
        skill_mcp_manager = None
        skill_mcp_tool_names = []
        planning_mcp_manager = None
        planning_mcp_tool_names = []
        download_mcp_manager = None
        download_mcp_tool_names = []
        browser_mcp_tool_names = []
        coding_mcp_manager = None
        coding_mcp_tool_names = []
        builtin_tools_enabled = self.enable_builtin_tools or self._is_tools_wildcard()

        # 预过滤
        _tool_server_filter: Optional[set] = None
        if self.tools_filter_key:
            _raw = state.get(self.tools_filter_key)
            logger.info(f"节点 {self.id} tools_filter_key={self.tools_filter_key}, state中值={_raw!r}")
            if _raw is not None and isinstance(_raw, (list, set)):
                _tool_server_filter = {str(s).strip().lower() for s in _raw}
                logger.info(f"节点 {self.id} 工具预过滤: {_tool_server_filter}")

        def _server_allowed(name: str) -> bool:
            return _tool_server_filter is None or name in _tool_server_filter

        # 获取 project_dir
        from agentclaw.config import get_config
        _cfg = get_config()
        project_dir = str(_cfg.project.project_dir) if _cfg.project.project_dir else None

        # 解析 prompt
        system_prompt = await self._resolve_prompt(state, context)

        # 构建 messages
        messages = self._build_messages(state, system_prompt, context)

        if not messages:
            err = (
                f"节点 {self.id}: 消息列表为空。"
                "请至少配置 system_prompt、user_prompt，或确保历史消息可用。"
            )
            logger.error(err)
            raise NodeExecutionError(self.id, err)
        if not any(m.get("role") == "user" for m in messages):
            logger.debug(
                f"节点 {self.id}: 消息列表中没有 user 消息，将仅使用 system/context 继续执行。"
            )
        
        # 获取工具定义
        tool_schemas = None
        effective_toolkit = context.toolkit
        skill_mcp_manager = None  # MCP manager for skill tools
        skill_mcp_tool_names = []  # MCP 工具名称列表
        planning_mcp_manager = None  # MCP manager for planning tools
        planning_mcp_tool_names = []  # Planning 工具名称列表
        download_mcp_manager = None  # MCP manager for download tools
        download_mcp_tool_names = []  # Download 工具名称列表
        browser_mcp_tool_names = []  # Browser 工具名称列表
        coding_mcp_manager = None  # MCP manager for coding tools
        coding_mcp_tool_names = []  # Coding 工具名称列表
        published_mcp_tools: dict[str, Any] = {}
        published_mcp_tool_names: list[str] = []
        # tools="*" 视为显式请求全量工具，自动纳入内置工具能力
        builtin_tools_enabled = self.enable_builtin_tools or self._is_tools_wildcard()

        # 预过滤：如果上游 filter 节点提供了工具服务器列表，只启用对应的 MCP 服务器
        _tool_server_filter: Optional[set] = None
        if self.tools_filter_key:
            _raw = state.get(self.tools_filter_key)
            logger.info(f"节点 {self.id} tools_filter_key={self.tools_filter_key}, "
                        f"state中值={_raw!r}, type={type(_raw).__name__}")
            if _raw is not None and isinstance(_raw, (list, set)):
                _tool_server_filter = {str(s).strip().lower() for s in _raw}
                logger.info(f"节点 {self.id} 工具预过滤: {_tool_server_filter}")
            elif _raw is not None:
                logger.warning(f"节点 {self.id} __filtered_tools__ 类型异常: {type(_raw).__name__}={_raw!r}")

        def _server_allowed(name: str) -> bool:
            """检查 MCP 服务器是否通过预过滤"""
            return _tool_server_filter is None or name in _tool_server_filter

        # planning-tools 随内置工具能力自动启用
        if builtin_tools_enabled:
            from agentclaw.mcp.builtin_servers import get_builtin_server_config
            
            # 创建 planning-tools MCP server 配置
            planning_tools_config = get_builtin_server_config("planning-tools")
            planning_tools_config["disabled"] = False  # 启用

            # 复用内置 MCP 连接，避免每次请求都拉起子进程
            planning_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                cache_key="planning-tools",
                server_name="planning-tools",
                server_config=planning_tools_config,
            )

            # 获取 MCP 工具 schema
            planning_tool_schemas = planning_mcp_manager.get_tools_schema()
            planning_mcp_tool_names = [t['function']['name'] for t in planning_tool_schemas]

            logger.info(f"节点 {self.id} 启用 planning-tools（随内置工具能力），工具: {planning_mcp_tool_names}")

        # 如果配置了 SEARXNG_BASE_URL 且启用了 builtin_tools，自动启用 search-tools MCP
        # 避免普通无工具工作流也触发外部 MCP 连接
        search_mcp_manager = None
        search_mcp_tool_names = None
        import os
        if os.getenv("SEARXNG_BASE_URL") and builtin_tools_enabled:
            from agentclaw.mcp.builtin_servers import get_builtin_server_config

            search_tools_config = get_builtin_server_config("search-tools")
            if search_tools_config:  # 配置有效时才启用
                search_tools_config["disabled"] = False

                search_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                    cache_key="search-tools",
                    server_name="search-tools",
                    server_config=search_tools_config,
                )

                search_tool_schemas = search_mcp_manager.get_tools_schema()
                search_mcp_tool_names = [t['function']['name'] for t in search_tool_schemas]

                logger.info(f"节点 {self.id} 启用 search tools (SearXNG)，工具: {search_mcp_tool_names}")

        # 如果启用 builtin_tools，通过 MCP 协议调用所有内置工具
        # 包括: skill-tools, browser-tools, computer-tools, download-tools 等
        # 用户可在前端配置面板控制具体启用哪些工具
        browser_mcp_manager = None
        computer_mcp_manager = None
        computer_mcp_tool_names = []
        download_mcp_manager = None
        download_tool_schemas = []
        download_mcp_tool_names = []
        coding_mcp_manager = None
        coding_mcp_tool_names = []

        if builtin_tools_enabled:
            from agentclaw.mcp.builtin_servers import get_builtin_server_config

            runtime_paths = resolve_runtime_path_context(
                workflow_id=getattr(context, "workflow_id", None),
                skill_manager=getattr(context, "skill_manager", None),
            )
            skills_dir = runtime_paths.skills_dir
            working_dir = runtime_paths.skill_tools_working_dir
            models_config = runtime_paths.models_config
            project_dir = runtime_paths.coding_tools_project_dir

            # 1. 启用 skill-tools（代码执行工具）
            skill_tools_config = get_builtin_server_config(
                "skill-tools",
                skills_dir=skills_dir,
                working_dir=working_dir,
                models_config=models_config,
                project_dir=project_dir,
            )
            skill_tools_config["disabled"] = False

            try:
                skill_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                    cache_key="skill-tools",
                    server_name="skill-tools",
                    server_config=skill_tools_config,
                )

                skill_tool_schemas = skill_mcp_manager.get_tools_schema()
                skill_mcp_tool_names = [t['function']['name'] for t in skill_tool_schemas]
                logger.info(f"节点 {self.id} 启用 skill-tools，工具: {skill_mcp_tool_names}")

                # 合并 skill-tools 到工具列表
                if self._is_tools_wildcard() and effective_toolkit:
                    user_tool_schemas = effective_toolkit.get_tools_schema()
                    tool_schemas = user_tool_schemas + skill_tool_schemas
                elif self.tools and effective_toolkit:
                    user_tool_schemas = effective_toolkit.get_schemas(self.tools if isinstance(self.tools, list) else [self.tools])
                    tool_schemas = user_tool_schemas + skill_tool_schemas
                else:
                    tool_schemas = skill_tool_schemas
                    # 自动注入 @workflow.tool 本地工具
                    if not self.tools and effective_toolkit:
                        from agentclaw.node.toolkit import ToolKit as _LTK
                        if isinstance(effective_toolkit, _LTK) and effective_toolkit.list_tools():
                            tool_schemas = effective_toolkit.get_tools_schema() + tool_schemas
            except asyncio.CancelledError:
                # CancelledError 必须重新抛出，不能吞掉
                logger.warning(f"节点 {self.id} 启用 skill-tools 被取消")
                raise
            except Exception as e:
                logger.error(f"节点 {self.id} 启用 skill-tools 失败: {e}")
                import traceback
                traceback.print_exc()

            # 2. 启用 coding-tools（项目目录沙箱编程工具）
            try:
                coding_tools_config = get_builtin_server_config("coding-tools", project_dir=project_dir)
                if coding_tools_config:
                    coding_tools_config["disabled"] = False
                    coding_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                        cache_key="coding-tools",
                        server_name="coding-tools",
                        server_config=coding_tools_config,
                    )

                    coding_tool_schemas = coding_mcp_manager.get_tools_schema()
                    coding_mcp_tool_names = [t['function']['name'] for t in coding_tool_schemas]
                    logger.info(f"节点 {self.id} 启用 coding-tools，工具: {coding_mcp_tool_names}")
            except asyncio.CancelledError:
                logger.warning(f"节点 {self.id} 启用 coding-tools 被取消")
                raise
            except Exception as e:
                logger.info(f"节点 {self.id} 启用 coding-tools 失败: {e}")

            # 3. 启用 browser-tools（浏览器自动化）
            # 检查用户 MCP 配置中是否已有 playwright/browser 相关 server
            has_external_browser = False
            if effective_toolkit:
                try:
                    from agentclaw.mcp.toolkit import MCPToolKit
                    if isinstance(effective_toolkit, MCPToolKit) and effective_toolkit._manager:
                        tool_names = [t.name for t in effective_toolkit._manager.list_tools()]
                        browser_indicators = ['browser_navigate', 'browser_click', 'browser_snapshot']
                        if any(ind in tool_names for ind in browser_indicators):
                            has_external_browser = True
                            logger.info(
                                f"节点 {self.id} 检测到 MCP 配置中已有浏览器工具（playwright 等），"
                                f"跳过内置 browser-tools 注入"
                            )
                except Exception:
                    pass

            if not has_external_browser:
                # 检查 playwright 是否已安装
                try:
                    import importlib
                    importlib.import_module("playwright")

                    browser_tools_config = get_builtin_server_config("browser-tools")
                    browser_tools_config["disabled"] = False

                    browser_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                        cache_key="browser-tools",
                        server_name="browser-tools",
                        server_config=browser_tools_config,
                    )

                    browser_tool_schemas = browser_mcp_manager.get_tools_schema()
                    browser_mcp_tool_names = [t['function']['name'] for t in browser_tool_schemas]
                    logger.info(f"节点 {self.id} 启用 browser-tools，工具: {browser_mcp_tool_names}")
                except asyncio.CancelledError:
                    logger.warning(f"节点 {self.id} 启用 browser-tools 被取消")
                    raise
                except ImportError:
                    logger.info(
                        f"节点 {self.id} playwright 未安装，跳过 browser-tools。"
                        f"安装方式: pip install agentclaw-ai && playwright install chromium"
                    )
                except Exception as e:
                    logger.warning(f"节点 {self.id} 启用 browser-tools 失败: {e}")

            # 4. 启用 computer-tools（截图与系统模拟）
            # 先检测 GUI 可用性，无 GUI 环境不注册（避免模型反复调用失败）
            _gui_available = (
                sys.platform == "win32"
                or bool(os.environ.get("DISPLAY"))
                or bool(os.environ.get("WAYLAND_DISPLAY"))
            )
            if not _gui_available:
                logger.info(f"节点 {self.id} 跳过 computer-tools（无 GUI 环境）")
            else:
                try:
                    computer_tools_config = get_builtin_server_config(
                        "computer-tools",
                        working_dir=working_dir,
                        models_config=models_config,
                    )
                    if computer_tools_config:
                        computer_tools_config["disabled"] = False
                        computer_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                            cache_key="computer-tools",
                            server_name="computer-tools",
                            server_config=computer_tools_config,
                        )

                        computer_tool_schemas = computer_mcp_manager.get_tools_schema()
                        computer_mcp_tool_names = [t['function']['name'] for t in computer_tool_schemas]
                        logger.info(f"节点 {self.id} 启用 computer-tools，工具: {computer_mcp_tool_names}")
                except asyncio.CancelledError:
                    logger.warning(f"节点 {self.id} 启用 computer-tools 被取消")
                    raise
                except Exception as e:
                    logger.info(f"节点 {self.id} 启用 computer-tools 失败（可能缺少平台桌面能力或系统权限）: {e}")

            # 5. 启用 download-tools（文件下载链接生成）
            try:
                download_tools_config = get_builtin_server_config("download-tools", working_dir=working_dir)
                if download_tools_config:
                    download_tools_config["disabled"] = False
                    download_mcp_manager = await self._get_or_create_builtin_mcp_manager(
                        cache_key="download-tools",
                        server_name="download-tools",
                        server_config=download_tools_config,
                    )

                    download_tool_schemas = download_mcp_manager.get_tools_schema()
                    download_tool_schemas = _filter_preferred_tool_overlaps(
                        download_tool_schemas,
                        skill_mcp_tool_names,
                        {"create_download_url"},
                    )
                    download_mcp_tool_names = [t['function']['name'] for t in download_tool_schemas]
                    logger.info(f"节点 {self.id} 启用 download-tools，工具: {download_mcp_tool_names}")
            except asyncio.CancelledError:
                logger.warning(f"节点 {self.id} 启用 download-tools 被取消")
                raise
            except Exception as e:
                logger.info(f"节点 {self.id} 启用 download-tools 失败（可能缺少 Redis）: {e}")


        # 如果使用 skills 但未启用 builtin_tools，给出警告
        if self.skills and not builtin_tools_enabled:
            logger.warning(f"节点 {self.id} 指定了 skills={self.skills}，但未启用 enable_builtin_tools。"
                          f"如果需要执行 skill 脚本/命令，建议设置 enable_builtin_tools=True")
        if self.skills and not context.skill_manager and not (self.enable_builtin_skills or self.skills == "*"):
            logger.warning(f"节点 {self.id} 指定了 skills={self.skills}，但 SkillManager 未加载。"
                          f"请检查 skills_dir 配置或 skills/ 目录是否存在。")

        # 如果没有启用内置工具能力，但有 tools 配置，使用 effective_toolkit
        if not builtin_tools_enabled and self.tools and effective_toolkit:
            if self._is_tools_wildcard():
                tool_schemas = effective_toolkit.get_tools_schema()
            else:
                tool_schemas = effective_toolkit.get_schemas(self.tools if isinstance(self.tools, list) else [self.tools])
            logger.info(f"节点 {self.id} 工具定义: {[t['function']['name'] for t in tool_schemas]}")
        elif self.tools and not effective_toolkit:
            logger.warning(f"节点 {self.id} 指定了 tools={self.tools}，但未找到 ToolKit/MCPToolKit。请检查 mcp_config 路径或 workflow.use() 配置。")

        # 自动注入 @workflow.tool 注册的本地工具（即使 self.tools 未设置）
        if effective_toolkit and not self.tools:
            from agentclaw.node.toolkit import ToolKit as _LocalToolKit
            if isinstance(effective_toolkit, _LocalToolKit) and effective_toolkit.list_tools():
                local_schemas = effective_toolkit.get_tools_schema()
                if local_schemas:
                    tool_schemas = (tool_schemas or []) + local_schemas
                    logger.info(f"节点 {self.id} 自动注入 workflow.tool 工具: "
                                f"{[t['function']['name'] for t in local_schemas]}")
        
        # 预过滤：根据上游 filter 节点的结果，清空不需要的 MCP server
        # skill-tools 和 planning-tools 始终保留（基础能力，不受 filter 影响）
        if _tool_server_filter is not None:
            if not _server_allowed("coding-tools"):
                coding_mcp_manager = None
                coding_mcp_tool_names = []
            if not _server_allowed("browser-tools"):
                browser_mcp_manager = None
                browser_mcp_tool_names = []
            if not _server_allowed("computer-tools"):
                computer_mcp_manager = None
                computer_mcp_tool_names = []
            if not _server_allowed("download-tools"):
                download_mcp_manager = None
                download_tool_schemas = []
                download_mcp_tool_names = []
            if not _server_allowed("search-tools"):
                search_mcp_manager = None
                search_mcp_tool_names = []
            logger.info(f"节点 {self.id} 工具预过滤完成，保留: {_tool_server_filter}")

        # 合并 planning tools（随 enable_builtin_tools）
        if planning_mcp_manager:
            planning_tool_schemas = planning_mcp_manager.get_tools_schema()
            if tool_schemas:
                tool_schemas = tool_schemas + planning_tool_schemas
            else:
                tool_schemas = planning_tool_schemas
            logger.info(f"节点 {self.id} 合并 planning 工具: {[t['function']['name'] for t in planning_tool_schemas]}")

        # 合并 download tools（如果启用 builtin tools）
        if download_mcp_manager:
            if tool_schemas:
                tool_schemas = tool_schemas + download_tool_schemas
            else:
                tool_schemas = download_tool_schemas
            logger.info(f"节点 {self.id} 合并 download 工具: {[t['function']['name'] for t in download_tool_schemas]}")

        # 合并 browser tools
        if browser_mcp_manager:
            browser_tool_schemas = browser_mcp_manager.get_tools_schema()
            if tool_schemas:
                tool_schemas = tool_schemas + browser_tool_schemas
            else:
                tool_schemas = browser_tool_schemas
            logger.info(f"节点 {self.id} 合并 browser 工具: {[t['function']['name'] for t in browser_tool_schemas]}")

        # 合并 computer tools
        if computer_mcp_manager:
            computer_tool_schemas = computer_mcp_manager.get_tools_schema()
            if tool_schemas:
                tool_schemas = tool_schemas + computer_tool_schemas
            else:
                tool_schemas = computer_tool_schemas
            logger.info(f"节点 {self.id} 合并 computer 工具: {[t['function']['name'] for t in computer_tool_schemas]}")

        # 合并 coding tools（项目目录沙箱）
        if coding_mcp_manager:
            coding_tool_schemas = coding_mcp_manager.get_tools_schema()
            if tool_schemas:
                tool_schemas = tool_schemas + coding_tool_schemas
            else:
                tool_schemas = coding_tool_schemas
            logger.info(f"节点 {self.id} 合并 coding 工具: {[t['function']['name'] for t in coding_tool_schemas]}")

        # 合并 search tools（如果配置了 SEARXNG_BASE_URL）
        if search_mcp_manager:
            search_tool_schemas = search_mcp_manager.get_tools_schema()
            if tool_schemas:
                tool_schemas = tool_schemas + search_tool_schemas
            else:
                tool_schemas = search_tool_schemas
            logger.info(f"节点 {self.id} 合并 search 工具: {[t['function']['name'] for t in search_tool_schemas]}")

        # 合并框架内发布的 MCP 工具（函数 / ToolKit 直发）
        if builtin_tools_enabled or self.tools:
            try:
                from agentclaw.mcp.token_manager import MCPServerRegistry

                requested_tool_names: Optional[set[str]] = None
                if self.tools and not self._is_tools_wildcard():
                    if isinstance(self.tools, list):
                        requested_tool_names = {str(name) for name in self.tools}
                    else:
                        requested_tool_names = {str(self.tools)}

                published_tool_schemas = []
                for server_name, tools in MCPServerRegistry.get_instance().get_published_tool_groups():
                    if not _server_allowed(server_name.strip().lower()):
                        continue
                    for published_tool in tools:
                        if requested_tool_names is not None and published_tool.name not in requested_tool_names:
                            continue
                        published_mcp_tools[published_tool.name] = published_tool
                        published_mcp_tool_names.append(published_tool.name)
                        published_tool_schemas.append(published_tool.to_openai_schema())

                if published_tool_schemas:
                    tool_schemas = (tool_schemas or []) + published_tool_schemas
                    logger.info(
                        f"节点 {self.id} 合并框架发布 MCP 工具: {published_mcp_tool_names}"
                    )
            except Exception as e:
                logger.warning(f"节点 {self.id} 合并框架发布 MCP 工具失败: {e}")

        # 过滤掉被禁用的工具
        if tool_schemas and context.disabled_tools:
            before_count = len(tool_schemas)
            tool_schemas = [
                t for t in tool_schemas
                if t.get("function", {}).get("name", "") not in context.disabled_tools
            ]
            filtered = before_count - len(tool_schemas)
            if filtered > 0:
                logger.info(f"节点 {self.id} 过滤了 {filtered} 个被禁用的工具")

        builtin_tool_names = set().union(
            set(skill_mcp_tool_names or []),
            set(planning_mcp_tool_names or []),
            set(download_mcp_tool_names or []),
            set(browser_mcp_tool_names or []),
            set(search_mcp_tool_names or []),
            set(computer_mcp_tool_names or []),
            set(coding_mcp_tool_names or []),
            set(published_mcp_tool_names or []),
        )
        tool_schemas = apply_public_tool_policy(
            tool_schemas,
            public_mode=bool(getattr(context, "public_mode", False)),
            builtin_tool_names=builtin_tool_names,
        )
        
        # confirm_action 工具已废弃：工具确认统一由 Harness 工具风险确认流程处理。
        # /api/confirm/{confirm_id} 仍作为 Harness 确认回调接口保留。

        # 最终兜底去重，避免不同来源的同名工具导致 provider 400
        tool_schemas = _dedupe_tool_schemas(tool_schemas, self.id)

        # 获取图像（images_key 非空时尝试获取并标准化）
        images = None
        if self.images_key:
            raw_images = state.get(self.images_key)
            images = _normalize_images(raw_images)
        
        # 如果没有通过 images_key 获取到图像，自动扫描 state 中的图像文件
        # （支持 Image 类型输入字段自动检测）
        if not images and context.workflow_id:
            images = _auto_detect_images(state)
        
        # 模型参数
        params = self.model_params or {}
        
        # 确定使用的模型 ID（考虑节点级降级）
        effective_model_id = self._get_effective_model_id(context)
        
        # 自动切换到视觉模型（当检测到图像时）
        if images and context.llm_manager:
            vision_model_id = context.llm_manager.get_vision_model_id()
            if vision_model_id:
                logger.info(f"节点 {self.id} 检测到图像输入，自动切换到视觉模型: {vision_model_id}")
                effective_model_id = vision_model_id
            else:
                logger.warning(f"节点 {self.id} 检测到图像输入，但未配置视觉模型（在 models.json 中设置 \"vision\" 字段，或为 chat 模型设置 supports_vision=true）")
        
        # 获取最大工具调用轮数（0 表示不限制）
        max_rounds = self.max_tool_rounds if self.max_tool_rounds is not None else _get_max_tool_rounds()
        if max_rounds <= 0:
            max_rounds = 999999  # 不限制
        logger.info(f"节点 {self.id} 最大工具调用轮数: {'无限制' if max_rounds >= 999999 else max_rounds}")
        
        use_harness = self.agent_style == "agentic"
        if use_harness and tool_schemas:
            tool_schemas = augment_tool_schemas_with_harness_risk(tool_schemas)

        # 工具调用循环（agentic 运行时由 Harness 状态跟踪决策）
        response = None
        harness = None
        harness_state = None
        if use_harness:
            harness = AgentRunHarness(
                node_id=self.id,
                workflow_id=context.workflow_id if context else None,
                thread_id=context.thread_id if context else None,
                model_id=effective_model_id,
                messages=messages,
            )
            harness.set_tool_environment(ToolExecutionEnvironment(
                toolkit=effective_toolkit,
                skill_mcp_manager=skill_mcp_manager,
                skill_mcp_tool_names=skill_mcp_tool_names,
                planning_mcp_manager=planning_mcp_manager,
                planning_mcp_tool_names=planning_mcp_tool_names,
                download_mcp_manager=download_mcp_manager,
                download_mcp_tool_names=download_mcp_tool_names,
                browser_mcp_manager=browser_mcp_manager,
                browser_mcp_tool_names=browser_mcp_tool_names,
                search_mcp_manager=search_mcp_manager,
                search_mcp_tool_names=search_mcp_tool_names,
                computer_mcp_manager=computer_mcp_manager,
                computer_mcp_tool_names=computer_mcp_tool_names,
                coding_mcp_manager=coding_mcp_manager,
                coding_mcp_tool_names=coding_mcp_tool_names,
                published_mcp_tools=published_mcp_tools,
                published_mcp_tool_names=published_mcp_tool_names,
            ))
            harness_state = harness.state
        _max_empty_retries = 3  # 连续空响应最大重试次数
        _consecutive_empty_responses = 0
        final_fallback_used = 0  # harness_final 退化回退计数（DSML 拦截致空回复时回退 continue）
        for round_idx in range(max_rounds):
            if harness:
                harness.begin_turn(round_idx + 1)
            logger.debug(f"节点 {self.id} 工具调用轮次: {round_idx + 1}/{max_rounds}")
            if context:
                context.check_cancelled()
            try:
                if self.stream and not tool_schemas:
                    # 纯流式输出（无工具定义的节点）
                    chunks = []
                    try:
                        async for chunk in context.llm_manager.stream(
                            messages,
                            model_id=effective_model_id,
                            images=images,
                            push_to_context=self.output_to_user,
                            **params
                        ):
                            chunks.append(chunk)
                    except (asyncio.CancelledError, WorkflowCancelledError):
                        # 中断时保存已生成的部分内容到上下文
                        partial = "".join(chunks)
                        if partial and self.save_to_context:
                            ctx_msgs = state.get("__messages__") or []
                            ctx_msgs.append({"role": "assistant", "content": partial + "\n\n[已停止]"})
                            state["__messages__"] = ctx_msgs
                            logger.info(f"节点 {self.id} 中断，已保存 {len(partial)} 字符的部分回复到上下文")
                        raise
                    response = "".join(chunks)
                    if harness:
                        harness.on_finish(response, "plain streaming response completed", round_index=round_idx + 1)
                    self._handle_node_success()
                    break
                elif self.stream and tool_schemas:
                    # 流式输出 + 工具调用
                    from agentclaw.model.manager import LLMResponse
                    from agentclaw.runtime.streaming import get_output_channel

                    chunks = []
                    llm_response = None

                    try:
                        force_tool_continue = bool(harness and harness.requires_tool_continuation())
                        if harness:
                            harness.before_model_call(message_count=len(messages), tool_count=len(tool_schemas or []), stream=True)
                        # 常规轮次实时推送；强制续跑轮次先抑制过程文本，避免无工具说明污染前端。
                        tool_params = dict(params)
                        tool_params["_call_type"] = "agent_tool_required" if force_tool_continue else "agent_tool"
                        async for item in context.llm_manager.stream_with_tools(
                            messages,
                            tools=tool_schemas,
                            tool_choice="required" if force_tool_continue else (self.tool_choice if self.tool_choice != "auto" else None),
                            model_id=effective_model_id,
                            images=images,
                            push_to_context=self.output_to_user and not force_tool_continue,
                            **tool_params
                        ):
                            if isinstance(item, str):
                                chunks.append(item)
                            elif isinstance(item, LLMResponse):
                                llm_response = item
                    except (asyncio.CancelledError, WorkflowCancelledError):
                        # 中断时保存已生成的部分内容到上下文
                        partial = "".join(chunks)
                        if partial and self.save_to_context:
                            ctx_msgs = state.get("__messages__") or []
                            ctx_msgs.append({"role": "assistant", "content": partial + "\n\n[已停止]"})
                            state["__messages__"] = ctx_msgs
                            logger.info(f"节点 {self.id} 中断，已保存 {len(partial)} 字符的部分回复到上下文")
                        raise

                    if harness:
                        model_turn = harness.process_model_response(
                            llm_response,
                            chunks=chunks,
                            round_index=round_idx + 1,
                            max_empty_retries=_max_empty_retries,
                        )
                        if model_turn.is_empty:
                            if model_turn.should_abort:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 模型连续 {model_turn.retries} 次返回空响应，停止重试"
                                )
                                response = ""
                                break
                            logger.warning(f"节点 {self.id} 轮次 {round_idx+1} 模型返回空响应(0 token)，重试 ({model_turn.retries}/{_max_empty_retries})")
                            continue
                        turn_output = model_turn.output
                    else:
                        if not llm_response and not chunks:
                            _consecutive_empty_responses += 1
                            if _consecutive_empty_responses >= _max_empty_retries:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 模型连续 {_consecutive_empty_responses} 次返回空响应，停止重试"
                                )
                                response = ""
                                break
                            logger.warning(f"节点 {self.id} 轮次 {round_idx+1} 模型返回空响应(0 token)，重试 ({_consecutive_empty_responses}/{_max_empty_retries})")
                            continue
                        _consecutive_empty_responses = 0
                        turn_output = postprocess_model_output(llm_response, chunks=chunks)
                    if turn_output is None:
                        response = ""
                        if harness:
                            harness.on_error("model response processing returned no output", round=round_idx + 1)
                        break
                    if turn_output.has_tool_calls:
                        if harness:
                            harness.mark_tool_continuation_satisfied()
                        valid_tool_calls = turn_output.tool_calls
                        tool_names = [t.name for t in valid_tool_calls]
                        logger.info(
                            f"节点 {self.id} 轮次 {round_idx+1} LLM 返回: "
                            f"text_len={len(turn_output.text)}, tool_calls={tool_names}"
                        )
                        
                        # agentic 模式：推送 LLM 的文本内容（工具调用前的解释/思考）
                        text_content = turn_output.text
                        # 从 LLMResponse 中提取 reasoning 内容，写入上下文以防模型遗忘
                        reasoning_content = turn_output.reasoning

                        # 有工具调用，执行工具
                        logger.info(f"节点 {self.id} 调用工具: {[t.name for t in valid_tool_calls]}")
                        # 中间轮文本已在流式过程中实时推送，无需回放
                        tool_batch_id = f"round-{round_idx + 1}"

                        # 并行执行所有工具调用
                        if harness:
                            tool_exec_kwargs = harness.build_tool_exec_kwargs(state)
                            messages, round_tool_results, combined_content, feedback_count, _decision = await harness.run_tool_turn(
                                state=state,
                                messages=messages,
                                context=context,
                                tool_calls=valid_tool_calls,
                                tool_exec_kwargs=tool_exec_kwargs,
                                batch_id=tool_batch_id,
                                tool_schemas=tool_schemas,
                                text_content=text_content,
                                reasoning_content=reasoning_content,
                            )
                            self._record_skill_reference_diagnostics(
                                state,
                                tool_calls=valid_tool_calls,
                                round_tool_results=round_tool_results,
                            )
                            logger.info(
                                f"节点 {self.id} 轮次 {round_idx+1} reasoning 传播: "
                                f"reasoning_len={len(reasoning_content)}, text_len={len(text_content)}, "
                                f"combined_len={len(combined_content)}"
                            )
                            if _decision.action == "abort":
                                response = "工具调用已被拒绝，流程已停止。"
                                harness.on_error(_decision.reason, round_index=round_idx + 1, **_decision.metadata)
                                self._handle_node_success()
                                break
                            if feedback_count:
                                logger.info(f"节点 {self.id} 注入 Harness 工具反馈消息: {feedback_count}")
                            post_result = await harness.run_post_tool_processing(
                                context=context,
                                messages=messages,
                                round_tool_results=round_tool_results,
                                model_id=effective_model_id,
                                params=params,
                                tool_schemas=tool_schemas,
                            )
                            await self._push_harness_user_feedback(post_result.user_feedback, batch_id=tool_batch_id)
                            if post_result.flow_action in {"finish", "ask_user", "abort"}:
                                if post_result.flow_action == "finish":
                                    response, dsml_intercepted = await self._generate_harness_final_response(
                                        context=context,
                                        messages=messages,
                                        model_id=effective_model_id,
                                        images=images,
                                        params=params,
                                        push_to_user=self.output_to_user,
                                    )
                                    final_degraded = dsml_intercepted or self._is_final_response_degraded(response)
                                    if final_degraded and final_fallback_used < _HARNESS_FINAL_FALLBACK_MAX:
                                        final_fallback_used += 1
                                        reason = "DSML拦截(模型仍想调用工具)" if dsml_intercepted else f"回复为空/极短({len(response or '')}字符)"
                                        logger.warning(
                                            f"节点 {self.id}: harness_final {reason}，"
                                            f"回退 continue 重试 ({final_fallback_used}/{_HARNESS_FINAL_FALLBACK_MAX})"
                                        )
                                        continue
                                    if final_degraded:
                                        logger.warning(
                                            f"节点 {self.id}: harness_final 仍异常，"
                                            f"已达回退上限({_HARNESS_FINAL_FALLBACK_MAX})，强制结束"
                                        )
                                    harness.on_finish(response, "harness final response generated", round_index=round_idx + 1)
                                else:
                                    response = post_result.user_feedback or ""
                                self._handle_node_success()
                                break
                        else:
                            tool_exec_kwargs = self._build_legacy_tool_exec_kwargs(
                                state=state,
                                toolkit=effective_toolkit,
                                skill_mcp_manager=skill_mcp_manager,
                                skill_mcp_tool_names=skill_mcp_tool_names,
                                planning_mcp_manager=planning_mcp_manager,
                                planning_mcp_tool_names=planning_mcp_tool_names,
                                download_mcp_manager=download_mcp_manager,
                                download_mcp_tool_names=download_mcp_tool_names,
                                browser_mcp_manager=browser_mcp_manager,
                                browser_mcp_tool_names=browser_mcp_tool_names,
                                search_mcp_manager=search_mcp_manager,
                                search_mcp_tool_names=search_mcp_tool_names,
                                computer_mcp_manager=computer_mcp_manager,
                                computer_mcp_tool_names=computer_mcp_tool_names,
                                coding_mcp_manager=coding_mcp_manager,
                                coding_mcp_tool_names=coding_mcp_tool_names,
                                published_mcp_tools=published_mcp_tools,
                                published_mcp_tool_names=published_mcp_tool_names,
                            )
                            messages, combined_content = await self._run_legacy_tool_turn(
                                state=state,
                                messages=messages,
                                context=context,
                                tool_calls=valid_tool_calls,
                                tool_exec_kwargs=tool_exec_kwargs,
                                batch_id=tool_batch_id,
                                text_content=text_content,
                                reasoning_content=reasoning_content,
                            )
                            logger.info(
                                f"节点 {self.id} 轮次 {round_idx+1} legacy 工具结果传播: "
                                f"reasoning_len={len(reasoning_content)}, text_len={len(text_content)}, "
                                f"combined_len={len(combined_content)}"
                            )

                        continue  # 继续下一轮
                    else:
                        # 无工具调用，返回文本 — Harness 根据上一轮后处理决策判断是否继续
                        response = turn_output.text
                        logger.info(
                            f"节点 {self.id} 轮次 {round_idx+1} 无工具调用完成: "
                            f"text_len={len(response)}"
                        )
                        if harness:
                            continue_decision = harness.should_continue_after_model_text(response, round_index=round_idx + 1)
                            if continue_decision:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 根据上一轮后处理 continue 决策继续 Harness: "
                                    f"{continue_decision.reason}"
                                )
                                messages.append({
                                    "role": "user",
                                    "content": (
                                        "<HARNESS_CONTINUE_REQUIRED>\n"
                                        "The previous post-tool controller decision required another tool call, but your last response did not contain a valid tool call. "
                                        "Call the necessary tool now using the platform tool-calling interface. "
                                        "Do not answer with prose only unless the task is actually complete.\n"
                                        "</HARNESS_CONTINUE_REQUIRED>"
                                    ),
                                })
                                response = ""
                                continue
                            harness.on_finish(response, "model returned final response", round_index=round_idx + 1)
                            if force_tool_continue and self.output_to_user and response:
                                ch = get_output_channel()
                                if ch:
                                    await ch.push_output(response, self.id)
                        # 文本已在流式过程中实时推送，无需回放
                        self._handle_node_success()
                        break
                else:
                    # 非流式 + 工具调用
                    force_tool_continue = bool(harness and harness.requires_tool_continuation())
                    if harness:
                        harness.before_model_call(message_count=len(messages), tool_count=len(tool_schemas or []), stream=False)
                    invoke_params = dict(params)
                    invoke_params["_call_type"] = "agent_tool_required" if force_tool_continue else "agent_tool"
                    result = await context.llm_manager.invoke(
                        messages,
                        model_id=effective_model_id,
                        images=images,
                        tools=tool_schemas,
                        tool_choice="required" if (tool_schemas and force_tool_continue) else ((self.tool_choice if self.tool_choice != "auto" else None) if tool_schemas else None),
                        **invoke_params
                    )

                    if harness:
                        model_turn = harness.process_model_response(
                            result,
                            round_index=round_idx + 1,
                            max_empty_retries=_max_empty_retries,
                        )
                        if model_turn.is_empty:
                            if model_turn.should_abort:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 模型连续 {model_turn.retries} 次返回空响应，停止重试"
                                )
                                response = ""
                                break
                            logger.warning(f"节点 {self.id} 轮次 {round_idx+1} 模型返回空响应(0 token)，重试 ({model_turn.retries}/{_max_empty_retries})")
                            continue
                        turn_output = model_turn.output
                    else:
                        content = result.content if hasattr(result, "content") else str(result or "")
                        if not content and not getattr(result, "tool_calls", None):
                            _consecutive_empty_responses += 1
                            if _consecutive_empty_responses >= _max_empty_retries:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 模型连续 {_consecutive_empty_responses} 次返回空响应，停止重试"
                                )
                                response = ""
                                break
                            logger.warning(f"节点 {self.id} 轮次 {round_idx+1} 模型返回空响应(0 token)，重试 ({_consecutive_empty_responses}/{_max_empty_retries})")
                            continue
                        _consecutive_empty_responses = 0
                        turn_output = postprocess_model_output(result)

                    # 检查是否有工具调用
                    if turn_output is None:
                        response = ""
                        if harness:
                            harness.on_error("model response processing returned no output", round=round_idx + 1)
                        break
                    if turn_output.has_tool_calls:
                        if harness:
                            harness.mark_tool_continuation_satisfied()
                        valid_tool_calls = turn_output.tool_calls
                        
                        # 推送 LLM 的文本内容（工具调用前的解释/思考）
                        text_content = turn_output.text
                        # 从 LLMResponse 中提取 reasoning 内容，写入上下文以防模型遗忘
                        reasoning_content = turn_output.reasoning
                        if text_content and text_content.strip():
                            from agentclaw.runtime.streaming import get_output_channel
                            ch = get_output_channel()
                            if ch:
                                await ch.push_output(text_content, self.id)
                        
                        logger.info(f"节点 {self.id} 调用工具: {[t.name for t in valid_tool_calls]}")
                        # 执行工具调用
                        tool_batch_id = f"round-{round_idx + 1}"

                        # 并行执行所有工具调用
                        if harness:
                            tool_exec_kwargs = harness.build_tool_exec_kwargs(state)
                            messages, round_tool_results, combined_content, feedback_count, _decision = await harness.run_tool_turn(
                                state=state,
                                messages=messages,
                                context=context,
                                tool_calls=valid_tool_calls,
                                tool_exec_kwargs=tool_exec_kwargs,
                                batch_id=tool_batch_id,
                                tool_schemas=tool_schemas,
                                text_content=text_content,
                                reasoning_content=reasoning_content,
                            )
                            self._record_skill_reference_diagnostics(
                                state,
                                tool_calls=valid_tool_calls,
                                round_tool_results=round_tool_results,
                            )
                            _reasoning_preview = repr(reasoning_content[:100]) if reasoning_content else "(empty)"
                            logger.info(
                                f"节点 {self.id} 轮次 {round_idx+1} reasoning 传播(non-stream): "
                                f"reasoning_len={len(reasoning_content)}, text_len={len(text_content or '')}, "
                                f"combined_len={len(combined_content)}, "
                                f"reasoning_preview={_reasoning_preview}"
                            )
                            if _decision.action == "abort":
                                response = "工具调用已被拒绝，流程已停止。"
                                harness.on_error(_decision.reason, round_index=round_idx + 1, **_decision.metadata)
                                self._handle_node_success()
                                break
                            if feedback_count:
                                logger.info(f"节点 {self.id} 注入 Harness 工具反馈消息: {feedback_count}")
                            post_result = await harness.run_post_tool_processing(
                                context=context,
                                messages=messages,
                                round_tool_results=round_tool_results,
                                model_id=effective_model_id,
                                params=params,
                                tool_schemas=tool_schemas,
                            )
                            await self._push_harness_user_feedback(post_result.user_feedback, batch_id=tool_batch_id)
                            if post_result.flow_action in {"finish", "ask_user", "abort"}:
                                if post_result.flow_action == "finish":
                                    response, dsml_intercepted = await self._generate_harness_final_response(
                                        context=context,
                                        messages=messages,
                                        model_id=effective_model_id,
                                        images=images,
                                        params=params,
                                        push_to_user=self.output_to_user,
                                    )
                                    final_degraded = dsml_intercepted or self._is_final_response_degraded(response)
                                    if final_degraded and final_fallback_used < _HARNESS_FINAL_FALLBACK_MAX:
                                        final_fallback_used += 1
                                        reason = "DSML拦截(模型仍想调用工具)" if dsml_intercepted else f"回复为空/极短({len(response or '')}字符)"
                                        logger.warning(
                                            f"节点 {self.id}: harness_final {reason}，"
                                            f"回退 continue 重试 ({final_fallback_used}/{_HARNESS_FINAL_FALLBACK_MAX})"
                                        )
                                        continue
                                    if final_degraded:
                                        logger.warning(
                                            f"节点 {self.id}: harness_final 仍异常，"
                                            f"已达回退上限({_HARNESS_FINAL_FALLBACK_MAX})，强制结束"
                                        )
                                    harness.on_finish(response, "harness final response generated", round_index=round_idx + 1)
                                else:
                                    response = post_result.user_feedback or ""
                                self._handle_node_success()
                                break
                        else:
                            tool_exec_kwargs = self._build_legacy_tool_exec_kwargs(
                                state=state,
                                toolkit=effective_toolkit,
                                skill_mcp_manager=skill_mcp_manager,
                                skill_mcp_tool_names=skill_mcp_tool_names,
                                planning_mcp_manager=planning_mcp_manager,
                                planning_mcp_tool_names=planning_mcp_tool_names,
                                download_mcp_manager=download_mcp_manager,
                                download_mcp_tool_names=download_mcp_tool_names,
                                browser_mcp_manager=browser_mcp_manager,
                                browser_mcp_tool_names=browser_mcp_tool_names,
                                search_mcp_manager=search_mcp_manager,
                                search_mcp_tool_names=search_mcp_tool_names,
                                computer_mcp_manager=computer_mcp_manager,
                                computer_mcp_tool_names=computer_mcp_tool_names,
                                coding_mcp_manager=coding_mcp_manager,
                                coding_mcp_tool_names=coding_mcp_tool_names,
                                published_mcp_tools=published_mcp_tools,
                                published_mcp_tool_names=published_mcp_tool_names,
                            )
                            messages, combined_content = await self._run_legacy_tool_turn(
                                state=state,
                                messages=messages,
                                context=context,
                                tool_calls=valid_tool_calls,
                                tool_exec_kwargs=tool_exec_kwargs,
                                batch_id=tool_batch_id,
                                text_content=text_content,
                                reasoning_content=reasoning_content,
                            )
                            _reasoning_preview = repr(reasoning_content[:100]) if reasoning_content else "(empty)"
                            logger.info(
                                f"节点 {self.id} 轮次 {round_idx+1} legacy 工具结果传播(non-stream): "
                                f"reasoning_len={len(reasoning_content)}, text_len={len(text_content or '')}, "
                                f"combined_len={len(combined_content)}, "
                                f"reasoning_preview={_reasoning_preview}"
                            )

                        continue  # 继续下一轮
                    else:
                        # 无工具调用，返回文本
                        response = turn_output.text

                        if harness:
                            continue_decision = harness.should_continue_after_model_text(response, round_index=round_idx + 1)
                            if continue_decision:
                                logger.warning(
                                    f"节点 {self.id} 轮次 {round_idx+1} 根据上一轮后处理 continue 决策继续 Harness(non-stream): "
                                    f"{continue_decision.reason}"
                                )
                                messages.append({
                                    "role": "user",
                                    "content": (
                                        "<HARNESS_CONTINUE_REQUIRED>\n"
                                        "The previous post-tool controller decision required another tool call, but your last response did not contain a valid tool call. "
                                        "Call the necessary tool now using the platform tool-calling interface. "
                                        "Do not answer with prose only unless the task is actually complete.\n"
                                        "</HARNESS_CONTINUE_REQUIRED>"
                                    ),
                                })
                                response = ""
                                continue
                            harness.on_finish(response, "model returned final response", round_index=round_idx + 1)

                        # 如果配置了 output_to_user，推送到 OutputChannel
                        if self.output_to_user and response:
                            from agentclaw.runtime.streaming import get_output_channel
                            channel = get_output_channel()
                            if channel:
                                await channel.push_output(response, self.id)
                        
                        self._handle_node_success()
                        break
            except WorkflowCancelledError:
                raise
            except Exception as e:
                # 节点级降级处理
                fallback_model = self._handle_node_failure(e, context)
                if fallback_model:
                    effective_model_id = fallback_model
                    logger.warning(f"节点 {self.id} 降级到模型: {fallback_model}")
                    continue  # 使用降级模型重试
                await self._push_model_error(e, effective_model_id)
                raise
        
        # 如果工具调用轮数用完但没有最终回复，再调用一次 LLM 获取总结
        if response is None and len(messages) > 2:
            logger.info(f"节点 {self.id} 工具调用轮数已用完，获取最终回复...")
            if context:
                context.check_cancelled()
            try:
                # 不带工具，强制生成文本回复；使用流式以保证 SSE 实时推送
                chunks = []
                async for chunk in context.llm_manager.stream(
                    messages,
                    model_id=effective_model_id,
                    images=images,
                    push_to_context=self.output_to_user,
                    **params
                ):
                    chunks.append(chunk)
                response = "".join(chunks)
                if harness:
                    harness.on_finish(response, "max tool rounds reached; generated final summary", max_rounds=max_rounds)

                self._handle_node_success()
            except WorkflowCancelledError:
                raise
            except Exception as e:
                logger.warning(f"获取最终回复失败: {e}")
                response = ""
                if harness:
                    harness.on_error(e, reason="failed to generate final summary after max tool rounds")
        
        if response is None:
            response = ""
            if harness and harness_state and harness_state.continue_decision is None:
                harness.on_error("agentic loop ended without response", max_rounds=max_rounds)

        if harness_state and harness_state.continue_decision:
            logger.info(
                f"节点 {self.id} Harness 决策: {harness_state.continue_decision.action} - "
                f"{harness_state.continue_decision.reason}"
            )

        # 清理内部标记 — 防止 LLM 将内部元数据泄露到用户响应中
        if isinstance(response, str) and response:
            response = re.sub( 
                r"<TOOL_EXECUTION_SUMMARY>.*?</TOOL_EXECUTION_SUMMARY>",
                "", response, flags=re.DOTALL,
            )
            response = re.sub(
                r"<REPEATED_CALL_WARNING>.*?</REPEATED_CALL_WARNING>",
                "", response, flags=re.DOTALL,
            )
            response = re.sub(
                r"<HARNESS_POST_TOOL_PROCESSING>.*?</HARNESS_POST_TOOL_PROCESSING>",
                "", response, flags=re.DOTALL,
            )
            response = re.sub(
                r"<HARNESS_NEXT_INSTRUCTION>.*?</HARNESS_NEXT_INSTRUCTION>",
                "", response, flags=re.DOTALL,
            )
            response = re.sub(
                r"<HARNESS_POST_TOOL_RESULT>.*?</HARNESS_POST_TOOL_RESULT>",
                "", response, flags=re.DOTALL,
            )
            response = response.strip()

        # 内置 MCP 连接按节点级缓存复用，避免每轮请求重复拉起/销毁子进程

        # 处理输出
        if self.output_format == "json":
            response = self._parse_json(response)
            
            # JSON 解析失败时自动重试：将错误结果反馈给 LLM 重新生成
            if isinstance(response, dict) and "__error__" in response:
                max_retries = self.fallback_threshold
                if max_retries is None:
                    max_retries = context.llm_manager.fallback_threshold if context.llm_manager else 3
                
                raw_text = response.get("__raw__", "")
                # 使用临时副本，不污染真正的 messages 上下文
                retry_messages = [m.copy() for m in messages]
                for retry_idx in range(max_retries):
                    logger.warning(
                        f"节点 {self.id} JSON 重试 ({retry_idx + 1}/{max_retries})，"
                        f"原始响应: {raw_text[:200]}"
                    )
                    retry_messages.append({"role": "assistant", "content": raw_text})
                    retry_messages.append({
                        "role": "user",
                        "content": "Your response is not valid JSON. Please output ONLY a valid JSON object, no extra text."
                    })
                    
                    try:
                        retry_result = await context.llm_manager.invoke(
                            retry_messages,
                            model_id=effective_model_id,
                            **params
                        )
                        retry_text = retry_result.content if hasattr(retry_result, 'content') else str(retry_result)
                    except Exception as e:
                        logger.warning(f"节点 {self.id} JSON 重试调用失败: {e}")
                        break
                    
                    response = self._parse_json(retry_text)
                    if "__error__" not in response:
                        logger.info(f"节点 {self.id} JSON 重试成功 (第 {retry_idx + 1} 次)")
                        break
                    raw_text = response.get("__raw__", "")
        
        state[self.get_output_key()] = response
        logger.debug(f"节点 {self.id} 输出: {str(response)[:100]}...")

        # 自动更新 __messages__（保存对话历史）
        if self.save_to_context:
            messages = [m for m in (state.get("__messages__") or []) if isinstance(m, dict)]
            # 添加用户消息
            user_input_field = context.user_input_field if context and context.user_input_field else None
            user_input = state.get(user_input_field) if user_input_field else None
            if user_input is None:
                user_input = state.get("__user__")
            if user_input is not None and not isinstance(user_input, str):
                user_input = str(user_input)
            if user_input and not any(
                m.get("role") == "user" and m.get("content") == user_input
                for m in messages[-3:]  # 检查最近3条避免重复
            ):
                messages.append({"role": "user", "content": user_input})
            # 添加 AI 回复
            response_text = response if isinstance(response, str) else str(response)
            messages.append({"role": "assistant", "content": response_text})
            state["__messages__"] = messages

            # 上下文压缩（如果启用且超过阈值）
            if self.enable_compression and context.request_stream:
                await self._maybe_compress_context(state, context, messages)

            # 计算并推送会话上下文的 token 数
            if context.request_stream:
                from agentclaw.runtime.streaming.context import get_output_channel
                from agentclaw.utils.token_counter import count_messages_tokens

                channel = get_output_channel()
                if channel:
                    try:
                        # 用 tiktoken 统计对话记录的实际 token 数
                        context_tokens = count_messages_tokens(messages, exclude_system=True)
                        input_tokens = count_messages_tokens(
                            [m for m in messages if m.get("role") != "assistant"],
                            exclude_system=True,
                        )
                        output_tokens = count_messages_tokens(
                            [m for m in messages if m.get("role") == "assistant"],
                            exclude_system=True,
                        )
                        usage = {
                            "prompt_tokens": input_tokens,
                            "completion_tokens": output_tokens,
                            "total_tokens": context_tokens,
                        }
                        await channel.push_message_end(usage=usage, context_tokens=context_tokens)
                    except Exception as e:
                        logger.warning(f"Failed to calculate context tokens: {e}")
                        await channel.push_message_end()
                else:
                    logger.warning("LLMNode: No output channel found, cannot push message_end")

        return state
    
    def _is_tools_wildcard(self) -> bool:
        """检查 tools 是否为通配符（使用所有工具）"""
        return self.tools == "*" or self.tools == ["*"]
    
    def _get_effective_model_id(self, context: WorkflowContext) -> Optional[str]:
        """
        获取有效的模型 ID

        优先级：节点降级模型 > 节点指定模型 > fast模型 > 请求级模型选择 > 全局配置
        """
        if self._node_is_fallback and self.fallback_model_id:
            return self.fallback_model_id
        if self.model_id:
            return self.model_id
        if self.use_fast_model and context.llm_manager and context.llm_manager.fast_id:
            return context.llm_manager.fast_id
        if context.runtime_model_id:
            return context.runtime_model_id
        return None
    
    def _handle_node_failure(self, error: Exception, context: WorkflowContext) -> Optional[str]:
        """
        处理节点级失败，返回降级模型 ID（如果需要降级）
        """
        self._node_failure_count += 1
        
        # 确定是否启用自动降级
        auto_fallback = self.auto_fallback
        if auto_fallback is None:
            auto_fallback = context.llm_manager.auto_fallback if context.llm_manager else True
        
        if not auto_fallback:
            return None

        if self._node_is_fallback:
            return None
        
        # 确定失败阈值
        threshold = self.fallback_threshold
        if threshold is None:
            threshold = context.llm_manager.fallback_threshold if context.llm_manager else 3
        
        # 检查是否达到阈值
        if self._node_failure_count >= threshold:
            # 确定降级模型
            fallback_model = self.fallback_model_id
            if not fallback_model and context.llm_manager:
                fallback_model = context.llm_manager.fallback_id
                is_chat_model = getattr(context.llm_manager, "_is_chat_model_id", None)
                if callable(is_chat_model) and not is_chat_model(fallback_model):
                    fallback_model = None
            
            if fallback_model and fallback_model != self.model_id:
                self._node_is_fallback = True
                logger.warning(
                    f"节点 {self.id} 达到失败阈值 ({self._node_failure_count}/{threshold})，"
                    f"降级到模型: {fallback_model}"
                )
                return fallback_model
        
        return None
    
    def _handle_node_success(self) -> None:
        """处理节点调用成功"""
        if not self._node_is_fallback:
            self._node_failure_count = 0

    async def _run_legacy_tool_turn(
        self,
        *,
        state: dict[str, Any],
        messages: list[dict[str, Any]],
        context: "WorkflowContext",
        tool_calls: list[Any],
        tool_exec_kwargs: dict[str, Any],
        batch_id: str,
        text_content: str = "",
        reasoning_content: str = "",
    ) -> tuple[list[dict[str, Any]], str]:
        """Execute tools without Harness post-processing for default LLM nodes."""
        from agentclaw.runtime.streaming import get_output_channel

        channel = get_output_channel()
        raw_results = await _execute_tool_batch_with_conflict_resolution(
            tool_calls,
            state=state,
            context=context,
            tool_exec_kwargs=tool_exec_kwargs,
        )
        tool_call_dicts: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        combined_content = ""
        if reasoning_content:
            combined_content += reasoning_content
        if text_content:
            if combined_content:
                combined_content += "\n"
            combined_content += text_content

        for tool_call, raw in zip(tool_calls, raw_results):
            if isinstance(raw, Exception):
                outcome = _to_tool_execution_outcome(f"[ERROR] {raw}", explicit_status="failed")
            elif isinstance(raw, ToolExecutionOutcome):
                outcome = raw
            else:
                outcome = _to_tool_execution_outcome(raw)

            tool_result = outcome.result
            if outcome.status == "failed" and getattr(tool_call, "arguments", None):
                args_preview = tool_call.arguments[:500] if len(tool_call.arguments) > 500 else tool_call.arguments
                tool_result = f"{tool_result}\n\n[Your call arguments: {args_preview}]"

            if channel:
                await channel.push_tool(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    tool_arguments=tool_call.arguments,
                    tool_result=tool_result,
                    tool_status=_tool_event_status(outcome),
                    batch_id=batch_id,
                    node=self.id,
                )

            tool_call_dicts.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            })
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": _truncate_tool_result(tool_result),
            })

        assistant_msg = {
            "role": "assistant",
            "content": combined_content or None,
            "tool_calls": tool_call_dicts,
        }
        messages.append(assistant_msg)
        messages.extend(tool_messages)
        context_messages = [m for m in (state.get("__messages__") or []) if isinstance(m, dict)]
        context_messages.append(assistant_msg)
        context_messages.extend(tool_messages)
        state["__messages__"] = context_messages
        return messages, combined_content

    def _build_legacy_tool_exec_kwargs(
        self,
        *,
        state: dict[str, Any],
        toolkit: Any,
        skill_mcp_manager: Any,
        skill_mcp_tool_names: list[str],
        planning_mcp_manager: Any,
        planning_mcp_tool_names: list[str],
        download_mcp_manager: Any,
        download_mcp_tool_names: list[str],
        browser_mcp_manager: Any,
        browser_mcp_tool_names: list[str],
        search_mcp_manager: Any,
        search_mcp_tool_names: list[str],
        computer_mcp_manager: Any,
        computer_mcp_tool_names: list[str],
        coding_mcp_manager: Any,
        coding_mcp_tool_names: list[str],
        published_mcp_tools: dict[str, Any],
        published_mcp_tool_names: list[str],
    ) -> dict[str, Any]:
        return dict(
            state=state,
            toolkit=toolkit,
            mcp_manager=skill_mcp_manager,
            mcp_tool_names=skill_mcp_tool_names,
            planning_mcp_manager=planning_mcp_manager,
            planning_mcp_tool_names=planning_mcp_tool_names,
            download_mcp_manager=download_mcp_manager,
            download_mcp_tool_names=download_mcp_tool_names,
            browser_mcp_manager=browser_mcp_manager,
            browser_mcp_tool_names=browser_mcp_tool_names,
            search_mcp_manager=search_mcp_manager,
            search_mcp_tool_names=search_mcp_tool_names,
            computer_mcp_manager=computer_mcp_manager,
            computer_mcp_tool_names=computer_mcp_tool_names,
            coding_mcp_manager=coding_mcp_manager,
            coding_mcp_tool_names=coding_mcp_tool_names,
            published_mcp_tools=published_mcp_tools,
            published_mcp_tool_names=published_mcp_tool_names,
        )

    async def _generate_harness_final_response(
        self,
        *,
        context: "WorkflowContext",
        messages: list[dict[str, Any]],
        model_id: str | None,
        images: Optional[List[ImageInput]],
        params: dict[str, Any],
        push_to_user: bool,
    ) -> tuple[str, bool]:
        """Generate the final user response after Harness decides to finish.

        Returns (response, dsml_intercepted)：dsml_intercepted 表示无工具流式路径
        是否拦截到 DSML（模型仍想调用工具），用于 harness_final 兜底回退判断。
        """
        if context:
            context.check_cancelled()
        final_params = dict(params or {})
        final_params.pop("tools", None)
        final_params.pop("tool_choice", None)
        final_params.pop("parallel_tool_calls", None)
        from agentclaw.model.manager import _last_stream_dsml_intercepted

        chunks: list[str] = []
        final_params["_call_type"] = "harness_final"
        _last_stream_dsml_intercepted.set(False)  # reset before stream
        async for chunk in context.llm_manager.stream(
            messages,
            model_id=model_id,
            images=images,
            push_to_context=push_to_user,
            **final_params,
        ):
            chunks.append(chunk)
        dsml_intercepted = _last_stream_dsml_intercepted.get()
        return "".join(chunks), dsml_intercepted

    @staticmethod
    def _is_final_response_degraded(response: str) -> bool:
        """判断 harness_final 回复是否退化（空/极短）。

        harness_final 是无工具路径；若模型在该路径仍输出工具调用（DSML）被拦截，
        最终回复会为空/极短，用户会感知“卡住”。用于触发回退 continue 重试。
        """
        return len((response or "").strip()) < _HARNESS_FINAL_DEGRADED_MAX_LEN

    async def _maybe_compress_context(
        self,
        state: dict,
        context: "WorkflowContext",
        messages: List[Dict[str, Any]],
    ) -> None:
        """
        检查并执行上下文压缩

        在 LLM 调用结束后检查上下文长度，如果超过阈值则触发压缩。
        压缩时会发送 SSE 事件通知前端显示"正在压缩上下文"状态。
        """
        if not messages:
            return

        # 估算 token 数
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated_tokens = total_chars // 3

        # 检查是否需要压缩
        compressor = ContextCompressor(
            threshold=self.compression_threshold,
            compression_model=self.compression_model,
        )

        if not compressor.should_compress(messages, estimated_tokens):
            return

        logger.info(f"节点 {self.id}: 触发上下文压缩，预估 token: {estimated_tokens}")

        # 发送压缩开始事件
        channel = None
        if context.request_stream:
            from agentclaw.runtime.streaming.context import get_output_channel

            channel = get_output_channel()
            if channel:
                try:
                    await channel.push_context_compression_started(
                        original_tokens=estimated_tokens
                    )
                    logger.info(f"节点 {self.id}: 已发送 context_compression_started 事件")
                except Exception as e:
                    logger.warning(f"发送压缩开始事件失败: {e}")

        try:
            # 执行压缩，传入 LLM manager
            llm_manager = context.llm_manager if context else None
            compressed_msgs, info = await compressor.compress(messages, llm_manager=llm_manager)

            if not info.get("compressed"):
                logger.info(f"节点 {self.id}: 压缩未执行: {info.get('reason')}")
                return

            # 更新 state 中的消息
            state["__messages__"] = compressed_msgs

            # 更新数据库（如果配置了 checkpointer）
            conversation_id = context.thread_id
            if conversation_id:
                from agentclaw.state.checkpointer import get_checkpointer

                checkpointer = get_checkpointer()
                if checkpointer:
                    try:
                        # 转换为 LangChain 消息格式
                        lc_messages = []
                        for m in compressed_msgs:
                            msg_type = m.get("role", "user")
                            content = m.get("content", "")
                            if msg_type == "system":
                                lc_messages.append(("system", content))
                            elif msg_type == "user":
                                lc_messages.append(("human", content))
                            elif msg_type == "assistant":
                                lc_messages.append(("ai", content))
                            elif msg_type == "tool":
                                lc_messages.append(("tool", content))

                        # 保存到 checkpointer
                        await checkpointer.aput(
                            (conversation_id,),
                            {
                                "messages": lc_messages,
                                "compressed": True,
                                "compression_info": info,
                            },
                        )
                        logger.info(f"节点 {self.id}: 压缩后的上下文已保存到数据库")
                    except Exception as e:
                        logger.error(f"保存压缩上下文到数据库失败: {e}")

            # 发送压缩完成事件
            if channel:
                try:
                    # 重新计算压缩后的 token 数
                    compressed_chars = sum(
                        len(str(m.get("content", ""))) for m in compressed_msgs
                    )
                    compressed_tokens = compressed_chars // 3

                    await channel.push_context_compression_finished(
                        compressed_tokens=compressed_tokens,
                        compressed_message_count=len(compressed_msgs),
                        original_message_count=len(messages),
                    )
                    logger.info(f"节点 {self.id}: 已发送 context_compression_finished 事件")
                except Exception as e:
                    logger.warning(f"发送压缩完成事件失败: {e}")

            logger.info(
                f"节点 {self.id}: 上下文压缩完成，"
                f"原始消息: {info['original_count']} -> 压缩后: {info['compressed_count']},"
                f"摘要长度: {info['summary_length']}"
            )

        except Exception as e:
            logger.error(f"上下文压缩失败: {e}")
            # 压缩失败不影响正常流程

    def force_fallback(self, reason: str = "手动触发") -> None:
        """强制节点使用降级模型"""
        if self.fallback_model_id:
            self._node_is_fallback = True
            logger.info(f"节点 {self.id} 强制降级: {reason}")
    
    def force_primary(self) -> None:
        """强制节点恢复使用主模型"""
        self._node_is_fallback = False
        self._node_failure_count = 0
        logger.info(f"节点 {self.id} 恢复主模型")

    async def _build_agentic_knowledgebase_section(self) -> str:
        try:
            from agentclaw.knowledgebase import get_knowledgebase_service

            service = get_knowledgebase_service()
            if service is None:
                return ""
            knowledgebases = await service.list_knowledgebases()
        except Exception as e:
            logger.warning(f"节点 {self.id} 注入知识库提示失败: {e}")
            return ""

        if not knowledgebases:
            return ""

        lines = [
            "<knowledge_bases>",
            "Available knowledge bases:",
        ]
        for knowledgebase in knowledgebases:
            name = str(getattr(knowledgebase, "name", "") or "").strip()
            if not name:
                continue
            description = str(getattr(knowledgebase, "description", "") or "").strip()[:500]
            lines.append(f"- Name: {name}")
            lines.append(f"  Description: {description or '-'}")

        if len(lines) == 2:
            return ""

        lines.append("</knowledge_bases>")
        return "\n".join(lines)

    async def _resolve_prompt(self, state: dict, context: WorkflowContext) -> Optional[str]:
        """
        解析 prompt
        
        支持语法：
        - {variable}: 从 state 中取值
        - {@prompt_key}: 从 PromptManager 中取值
        
        热更新支持：
        - 自动以节点名作为 prompt_key
        - 如果 PromptManager 中存在自定义版本，优先使用
        - 这允许通过 API 更新提示词后立即生效
        
        Skills 知识注入：
        - 如果配置了 skills 参数，将项目技能知识追加到 system_prompt
        - 如果 enable_builtin_skills=True，自动注入内置技能知识
        
        Agent 风格：
        - agent_style="agentic" 时注入增强提示词
        - 启用内置工具能力时添加规划提醒（`enable_builtin_tools=True` 或 `tools="*"`）
        """
        if not self.system_prompt:
            result = ""
        else:
            result = self.system_prompt
        
        # 0. 检查 PromptManager 是否有该节点的自定义提示词（支持热更新）
        if context.prompt_manager and self.system_prompt:
            try:
                prompt_info = context.prompt_manager.get_prompt_info(self.id)
                if prompt_info and prompt_info.get("is_custom"):
                    # 使用自定义的提示词
                    result = prompt_info["content"]
                    logger.debug(f"节点 {self.id} 使用自定义提示词 (v{prompt_info.get('version', 1)})")
            except (KeyError, AttributeError):
                pass  # 没有自定义提示词，使用默认的
        
        # 0.5 应用 agent_style（在变量替换之前）
        if self.agent_style == "agentic":
            result = AGENTIC_PROMPT_TEMPLATE.format(original_prompt=result if result else "")
            logger.debug(f"节点 {self.id} 使用 agentic 风格提示词")

        # 1. 解析 {@key} 引用 PromptManager
        if context.prompt_manager and result:
            def replace_prompt_ref(match):
                key = match.group(1)
                try:
                    return context.prompt_manager.get_prompt(key, state)
                except KeyError:
                    raise ValueError(f"PromptManager 中未找到: {key}")
            
            result = re.sub(r'\{@(\w+)\}', replace_prompt_ref, result)
        
        # 2. 解析 {variable} 变量替换
        if result:
            try:
                result = _safe_format_prompt(result, state)
            except Exception as e:
                logger.warning(
                    f"Prompt 变量替换失败: {e}。"
                    "如需在 prompt 中展示 JSON/对象字面量，请将花括号写成 {{...}} 以避免被 format 解析。"
                )

        # 2.5 planning 提醒延后到末尾注入（见下方 step 5）
        builtin_tools_enabled = self.enable_builtin_tools or self._is_tools_wildcard()

        # 2.6 注入项目目录结构（agentic 模式 + 内置工具启用时）
        if builtin_tools_enabled:
            try:
                from agentclaw.config import get_config as _get_cfg
                _cfg = _get_cfg()
                _proj_dir = str(_cfg.project.project_dir) if _cfg.project.project_dir else None
            except Exception:
                _proj_dir = None
            if _proj_dir:
                tree_text = _build_project_tree(_proj_dir)
                if tree_text:
                    tree_section = f"<project_structure>\n{tree_text}\n</project_structure>"
                    result = f"{result}\n\n{tree_section}" if result else tree_section

        if self.agent_style == "agentic":
            knowledgebase_section = await self._build_agentic_knowledgebase_section()
            if knowledgebase_section:
                result = f"{result}\n\n{knowledgebase_section}" if result else knowledgebase_section

            workflow_capabilities_section = _build_agentic_workflow_capabilities_section(context.workflow_id)
            if workflow_capabilities_section:
                result = (
                    f"{result}\n\n{workflow_capabilities_section}"
                    if result
                    else workflow_capabilities_section
                )

        if self.enable_memory and context.workflow_id:
            try:
                from agentclaw.config import get_config as _get_cfg

                memory_content = read_workflow_memory(
                    _get_cfg().project.project_dir,
                    context.workflow_id,
                )
                memory_section = build_memory_section(memory_content)
                if memory_section:
                    result = f"{result}\n\n{memory_section}" if result else memory_section
            except Exception as e:
                logger.warning(f"节点 {self.id} 注入 workflow memory 失败: {e}")

        # 3. 注入 Skills 知识
        # 预过滤：上游 filter 节点提供相关技能名称列表
        _skill_name_filter: Optional[set] = None
        if self.skills_filter_key:
            _raw = state.get(self.skills_filter_key)
            if _raw is not None and isinstance(_raw, (list, set)):
                _skill_name_filter = {str(s).strip() for s in _raw}
                logger.info(f"节点 {self.id} 技能预过滤: {_skill_name_filter}")

        matched_skills = []
        skill_sources = {}

        def merge_skills(skills_list, source: str) -> None:
            for skill in skills_list:
                if skill.name in skill_sources:
                    continue
                skill_sources[skill.name] = source
                matched_skills.append(skill)

        # 3.1 项目 skills（现有机制）
        if self.skills and context.skill_manager:
            if self.skills == "*":
                context.skill_manager.refresh()
                project_skills = context.skill_manager.list()
                if project_skills:
                    logger.info(f"节点 {self.id} 注入项目技能 {len(project_skills)} 个（skills='*'）")
            else:
                names = self.skills if isinstance(self.skills, list) else [self.skills]
                project_skills = context.skill_manager.get_many(names)
            merge_skills(project_skills, "project")

        # 3.2 内置 skills（enable_builtin_skills 或 skills="*" 时自动纳入）
        builtin_skills_enabled = self.enable_builtin_skills or self.skills == "*"
        if builtin_skills_enabled:
            try:
                from agentclaw.skills import get_builtin_skill_manager

                builtin_manager = get_builtin_skill_manager(auto_init=True)
                if builtin_manager:
                    if self.skills == "*":
                        builtin_manager.refresh()
                        builtin_skills = builtin_manager.list()
                        logger.info(f"节点 {self.id} 注入内置技能 {len(builtin_skills)} 个（skills='*'）")
                    elif self.skills:
                        names = self.skills if isinstance(self.skills, list) else [self.skills]
                        builtin_skills = builtin_manager.get_many(names)
                    else:
                        builtin_manager.refresh()
                        builtin_skills = builtin_manager.list()
                        if builtin_skills:
                            logger.info(f"节点 {self.id} 自动注入全部内置技能 {len(builtin_skills)} 个")
                    merge_skills(builtin_skills, "builtin")
                else:
                    logger.debug(f"节点 {self.id} 内置技能已启用，但未找到内置技能目录")
            except Exception as e:
                logger.warning(f"节点 {self.id} 加载内置技能失败: {e}")

        # 3.3 过滤禁用技能
        if context.disabled_skills and matched_skills:
            before_count = len(matched_skills)
            matched_skills = [s for s in matched_skills if s.name not in context.disabled_skills]
            filtered = before_count - len(matched_skills)
            if filtered > 0:
                logger.info(f"节点 {self.id} 过滤了 {filtered} 个被禁用的 skill")

        # 3.4 预过滤：只保留上游 filter 节点选中的技能（metadata.always_inject 的技能不受过滤）
        if _skill_name_filter is not None and matched_skills:
            before_count = len(matched_skills)
            matched_skills = [
                s for s in matched_skills
                if s.name in _skill_name_filter or (s.metadata or {}).get("always_inject")
            ]
            filtered = before_count - len(matched_skills)
            if filtered > 0:
                logger.info(f"节点 {self.id} 预过滤移除 {filtered} 个不相关 skill，保留: {[s.name for s in matched_skills]}")

        required_skill_reads = _build_required_skill_reads(matched_skills, self.skills)
        if required_skill_reads:
            state["__required_skill_reads__"] = required_skill_reads
        else:
            state.pop("__required_skill_reads__", None)

        if matched_skills:
            skill_prompts = []
            skill_doc_paths: dict[str, str] = {}

            for skill in matched_skills:
                source = skill_sources.get(skill.name, "project")
                skill_prompt = skill.to_prompt(include_content=False)
                if source == "builtin":
                    skill_prompt = f"{skill_prompt}\nSource: builtin"
                skill_prompts.append(skill_prompt)
                skill_doc_paths[skill.name] = f"{skill.path}/SKILL.md"
                logger.debug(f"节点 {self.id} 注入技能摘要: {skill.name} ({source})")

            # 构建 Skills 提示（英文）
            # 只在 agentic 模式下添加面向执行的读取协议
            if self.agent_style == "agentic":
                skills_header = f"{SKILL_USAGE_PROTOCOL}\n\n"
            else:
                # 非 agentic 模式：简化提示
                skills_header = "# Available Skills\n\n"
            skills_content = skills_header + "\n\n".join(skill_prompts)

            if skill_doc_paths:
                read_instructions = "\n".join(
                    f"- `read_skill_file(skill_name=\"{name}\")` — {name}"
                    for name in skill_doc_paths
                )
                skills_content += (
                    "\n\n## Skill Files To Read When Relevant\n\n"
                    "When one of the following skills is clearly relevant, read it before using the corresponding workflow, platform capability, or tool guidance:\n"
                    f"{read_instructions}\n\n"
                    "Read only the skills that help the current task move forward."
                )

            if result:
                result = f"{result}\n\n{skills_content}"
            else:
                result = skills_content

            # 3.5 注入 skills 路径和脚本列表
            skills_tree = _build_skills_tree(matched_skills)
            if skills_tree:
                skills_tree_section = f"<available_skill_paths>\n{skills_tree}\n</available_skill_paths>"
                result = f"{result}\n\n{skills_tree_section}"

        # 4. 交付提示（只提示，不拦截）
        # 当启用了 agent_creator（项目或内置）时，提醒模型显式汇报验证状态，
        # 避免在未验证场景下直接宣称“完成”。
        has_agent_creator = any(s.name == "agent_creator" for s in matched_skills)
        if has_agent_creator:
            if result:
                result = f"{result}\n\n{DELIVERY_HINT_REMINDER}"
            else:
                result = DELIVERY_HINT_REMINDER

        # 5. planning 提醒放在最末尾（权重最高位置）
        if builtin_tools_enabled:
            if result:
                result = f"{result}\n\n{PLANNING_REMINDER}"
            else:
                result = PLANNING_REMINDER

        return result if result else None

    def _build_messages(self, state: dict, system_prompt: Optional[str], context: WorkflowContext) -> list:
        """构建消息列表"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 获取最大历史消息条数。agentic 模式不按消息条数截断，避免切断 assistant tool_calls/tool 结果对。
        max_messages = None if self.agent_style == "agentic" else (
            self.max_context_messages if self.max_context_messages is not None else _get_max_context_messages()
        )
        if max_messages is not None and max_messages <= 0:
            max_messages = None

        # 加载历史
        if self.use_context:
            history = state.get("__messages__") or []
            total_history = len(history)
            if max_messages is not None and total_history > max_messages:
                truncated = total_history - max_messages
                logger.info(
                    f"节点 {self.id} 上下文截断: 总历史={total_history}, "
                    f"max_context_messages={max_messages}, 丢弃最早 {truncated} 条"
                )
                history = history[-max_messages:]
            for msg in history:
                if hasattr(msg, 'content'):
                    role = "assistant" if msg.__class__.__name__ == "AIMessage" else "user"
                    messages.append({"role": role, "content": msg.content})
                elif isinstance(msg, dict):
                    messages.append(msg)
            messages = _repair_openai_tool_message_sequence(messages, node_id=self.id)
        
        # 获取用户输入：使用 context 中配置的字段名
        user_input_field = context.user_input_field if context and context.user_input_field else None
        user_input = state.get(user_input_field) if user_input_field else None
        if user_input is None:
            user_input = state.get("__user__")
        if user_input is not None and not isinstance(user_input, str):
            user_input = str(user_input)

        if user_input:
            # 检查最后一条消息是否已经是这个用户输入
            last_user_msg = None
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content")
                    break

            if last_user_msg != user_input:
                # 如果有自定义用户消息模板，使用模板
                if self.user_prompt:
                    try:
                        user_msg = self.user_prompt.format(**state)
                        messages.append({"role": "user", "content": user_msg})
                    except KeyError as e:
                        logger.warning(f"用户消息变量未找到: {e}")
                        messages.append({"role": "user", "content": user_input})
                else:
                    messages.append({"role": "user", "content": user_input})
        elif not any(m.get("role") == "user" for m in messages):
            # 没有用户输入且历史中也没有用户消息，使用模板
            if self.user_prompt:
                try:
                    user_msg = self.user_prompt.format(**state)
                    messages.append({"role": "user", "content": user_msg})
                except KeyError as e:
                    logger.warning(f"用户消息变量未找到: {e}")

        # 注入文件路径到用户消息（inject_files）
        should_inject = self.inject_files if self.inject_files is not None else (self.agent_style == "agentic")
        if should_inject:
            files = state.get("__files__")
            if files and isinstance(files, list) and messages:
                from pathlib import Path as _Path
                from agentclaw.database.file_storage import get_file_storage
                # 通过存储后端解析真实本地路径
                storage = get_file_storage()
                # 找到最后一条用户消息
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        lines = ["\n\n<attached_files>",
                                 "The user has uploaded the following files. Use `read_file` tool with the exact path below to read their content. Do NOT use list_files to browse directories."]
                        for f in files:
                            if isinstance(f, dict):
                                fpath = f.get('path', f.get('file_path', ''))
                                fpath = self._resolve_file_path(fpath, storage)
                                lines.append(f"- {f.get('original_name', 'unknown')}: {fpath}")
                            elif isinstance(f, str):
                                fpath = self._resolve_file_path(f, storage)
                                lines.append(f"- {fpath}")
                        lines.append("</attached_files>")
                        file_block = "\n".join(lines)
                        # 追加到用户消息内容
                        messages[i]["content"] = messages[i]["content"] + file_block
                        logger.info(f"节点 {self.id} 注入 {len(files)} 个文件路径到用户消息")
                        break

        return messages

    @staticmethod
    def _resolve_file_path(fpath: str, storage=None) -> str:
        """将文件存储 key 解析为真实本地绝对路径"""
        from pathlib import Path as _P
        if not fpath:
            return fpath
        if _P(fpath).is_absolute():
            return fpath
        # 通过存储后端获取真实本地路径
        if storage:
            local = storage.backend.get_local_path(fpath)
            if local:
                return local
        # fallback: 通过配置的 upload_dir 拼接
        try:
            from agentclaw.config import get_config
            cfg = get_config()
            base = _P(cfg.upload.upload_dir)
            if not base.is_absolute():
                base = cfg.project.project_dir / base
            full = base / fpath
            if full.exists():
                return str(full)
        except Exception:
            pass
        return str(_P(fpath).resolve())

    def _parse_json(self, response: str) -> dict:
        """智能解析 JSON 响应"""
        if not response:
            return {"__error__": "空响应"}
        
        text = response.strip()
        
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取代码块
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # 尝试提取 JSON 对象
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"节点 {self.id} JSON 解析失败，原始响应: {text[:500]}")
        return {"__raw__": text, "__error__": "JSON 解析失败"}
