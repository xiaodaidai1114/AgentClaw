"""
Workflow - 工作流核心模块

提供工作流定义和执行
"""

from __future__ import annotations
from typing import (
    Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING, get_args, get_origin
)
import asyncio
import functools
import inspect
from contextlib import asynccontextmanager
from pathlib import Path
import os

from agentclaw.graph.context import WorkflowContext
from agentclaw.node.types import ErrorStrategy
from agentclaw.node.base import BaseNode, FunctionNode
from agentclaw.node.llm import LLMNode
from agentclaw.node.human import HumanNode
from agentclaw.exceptions import ConfigError
from agentclaw.logger.config import get_logger

# 框架内部重量级字段 — 不应出现在 node_finished 的 outputs 中
# 注意: __filtered_tools__ / __filtered_skill_names__ 等轻量节点输出变量不在此列表中
_INTERNAL_HEAVY_KEYS = frozenset({
    "__messages__",
    "__status__",
    "__interrupted__",
    "__files__",
    "__user__",
    "__error__",
    "__interrupt_info__",
    "__debug_stopped__",
})

if TYPE_CHECKING:
    from agentclaw.base import BaseComponent
    from agentclaw.node.toolkit import ToolKit

logger = get_logger(__name__)

# 全局 MCPToolKit 缓存：同一 mcp.json 路径只创建一个 MCPToolKit 实例
# 避免多个 Workflow 对同一配置文件分别创建 MCPToolKit 导致重复启动 MCP Server 子进程
_mcp_toolkit_cache: dict = {}  # resolved_path_str -> MCPToolKit
LANGGRAPH_UNLIMITED_RECURSION_LIMIT = 1_000_000
DEFAULT_CHAT_AUDIO_CONFIG = {
    "enabled": False,
    "speech_input_enabled": False,
    "tts_enabled": False,
    "speech2text_model_id": "",
    "tts_model_id": "",
    "tts_voice": "",
}

BUILTIN_CHAT_AUDIO_CONFIG = {
    **DEFAULT_CHAT_AUDIO_CONFIG,
    "enabled": True,
    "speech_input_enabled": True,
    "tts_enabled": True,
}


def _get_mcp_connect_timeout() -> float:
    raw = os.getenv("AGENTCLAW_MCP_CONNECT_TIMEOUT", "10.0").strip()
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 10.0
    return max(timeout, 0.1)


def _classify_mcp_connect_results(
    results: Dict[str, Optional[str]],
) -> tuple[str, int, int]:
    """区分未配置、部分成功/成功、以及全部失败三种 MCP 连接结果。"""
    total = len(results)
    connected = sum(1 for error in results.values() if error is None)
    pending = sum(1 for error in results.values() if error == "connect still running in background")

    if total == 0:
        return ("unconfigured", connected, total)
    if connected > 0 or pending > 0:
        return ("connected", connected, total)
    return ("failed", connected, total)


class Workflow:
    """
    工作流定义和执行
    
    Example:
        workflow = Workflow(
            id="customer_service_v1",
            name="客服助手",
            version="1.0.0"
        )
        
        workflow.add_node(Node(id="理解意图", prompt_key="intent"))
        workflow.add_node(Node(id="生成回复", prompt_key="response"))
        
        workflow.publish()
    
    Inputs 定义:
        # 方式 1：字典简写
        workflow = Workflow(id="demo", inputs={"query": str, "count": int})
        
        # 方式 2：Input 对象
        from agentclaw import Input
        workflow = Workflow(
            id="demo",
            inputs=[
                Input("query", str, required=True, description="查询内容"),
                Input("count", int, default=10, min=1, max=100),
            ]
        )
        
        # 方式 3：Pydantic BaseModel
        class MyInputs(BaseModel):
            query: str
            count: int = 10
        workflow = Workflow(id="demo", inputs=MyInputs)
    """
    
    def __init__(
        self,
        id: str,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        desc: str = "",  # MCP 工具描述（发布为 MCP Server 时使用）
        timeout: int = 300,
        recursion_limit: int = 0,
        cancel_on_disconnect: bool = True,
        inputs: Optional[Any] = None,  # 输入参数定义
        user_input: Optional[str] = None,  # 指定哪个输入字段是用户输入（从对话框传入）
        auth_required: bool = False,
        allowed_roles: Optional[List[str]] = None,
        rate_limit: Optional[str] = None,
        public_share_enabled: bool = False,
        public_share_token: Optional[str] = None,
        publish_to_square: bool = False,
        api_published: bool = True,
        workflow_api_key: Optional[str] = None,
        safe_guard_apply_api: bool = False,
        safe_guard_apply_public: bool = True,
        public_conversation_limit: int = 20,
        public_message_limit: int = 200,
        inject_as_agentic_capability: bool = True,
        tracing: bool = True,
        mcp_config: Optional[str] = None,  # MCP 配置文件路径，None 表示自动查找
        models_config: Optional[str] = None,  # 模型配置文件路径，None 表示自动查找 models.json
        publish_as_mcp: bool = False,  # 是否发布为 MCP Server（默认不发布）
        mcp_server: Optional[str] = None,  # MCP 聚合名称，多个工作流可聚合到同一端点
        welcome: Optional[str] = None,  # 前端开场白（新对话时显示，不影响 API 调用）
        chat_audio: Optional[dict] = None,  # 聊天页语音输入/TTS 配置
        skills_dir: Optional[str] = None,  # Skills 目录路径，None 表示自动查找 ./skills/
    ):
        self.id = id
        self.name = name
        self.version = version
        self.description = description
        self.desc = desc  # MCP 工具描述
        self.welcome = welcome  # 前端开场白
        self._chat_audio_explicit = chat_audio is not None
        self.chat_audio = self._normalize_chat_audio(chat_audio)
        self._skills_dir = skills_dir  # Skills 目录路径
        
        self.timeout = timeout
        self.recursion_limit = recursion_limit if recursion_limit and recursion_limit > 0 else 0
        self.cancel_on_disconnect = cancel_on_disconnect
        
        self.auth_required = auth_required
        self.allowed_roles = allowed_roles
        self.rate_limit = rate_limit
        self.public_share_enabled = bool(public_share_enabled)
        self.public_share_token = public_share_token
        self.publish_to_square = bool(publish_to_square)
        self.api_published = bool(api_published)
        self.workflow_api_key = workflow_api_key
        self.safe_guard_apply_api = bool(safe_guard_apply_api)
        self.safe_guard_apply_public = bool(safe_guard_apply_public)
        self.public_conversation_limit = public_conversation_limit
        self.public_message_limit = public_message_limit
        self.inject_as_agentic_capability = bool(inject_as_agentic_capability)
        self.tracing = tracing
        
        # MCP Server 发布配置
        self.publish_as_mcp = publish_as_mcp
        self.mcp_server = mcp_server  # 聚合名称
        
        self._nodes: Dict[str, Node] = {}
        self._node_order: List[str] = []
        self._edges: Dict[str, List[str]] = {}  # 支持一对多并行
        self._conditional_edges: Dict[str, dict] = {}
        self._components: List[BaseComponent] = []
        self._start_node: Optional[str] = None  # 显式指定的开始节点
        
        # InputSchema（输入参数定义）
        self._input_schema: Optional["InputSchema"] = None
        self._user_input_field: Optional[str] = user_input  # 用户输入字段名
        
        # 解析 inputs 参数
        if inputs is not None:
            self._init_inputs(inputs)
        self._validate_user_input_binding()
        
        self._state_schema: Dict[str, type] = {
            '__messages__': list,
        }

        self._prompt_manager = None
        self._llm_manager = None
        self._toolkit = None
        self._mcp_toolkit = None
        self._skill_manager = None
        self._mcp_config = mcp_config
        self._models_config = models_config
        self._mcp_connect_lock = asyncio.Lock()  # 防止并发 MCP 连接
        self._mcp_connect_task: Optional[asyncio.Task] = None
        self._definition_file = self._detect_definition_file()
        self._compiled_graph = None
        self._checkpointer = None
        self._checkpointer_initialized = False
        self._prompts_registered = False  # 节点提示词是否已注册到 PromptManager

        logger.info(f"创建工作流: {id} ({name} v{version})")

    @staticmethod
    def _normalize_chat_audio(chat_audio: Optional[dict]) -> dict:
        config = dict(DEFAULT_CHAT_AUDIO_CONFIG)
        if isinstance(chat_audio, dict):
            for key in config:
                if key in chat_audio:
                    config[key] = chat_audio[key]
        for key in ("enabled", "speech_input_enabled", "tts_enabled"):
            config[key] = bool(config.get(key))
        for key in ("speech2text_model_id", "tts_model_id", "tts_voice"):
            config[key] = str(config.get(key) or "")
        return config

    @staticmethod
    def _is_framework_internal_file(path: Path) -> bool:
        """判断路径是否位于 agentclaw 框架包内部。"""
        try:
            resolved = path.resolve()
            framework_root = Path(__file__).resolve().parents[1]  # agentclaw/
            if not resolved.is_relative_to(framework_root):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _detect_definition_file() -> Optional[Path]:
        """
        尝试识别创建 Workflow 的业务源码文件（通常是 demo/workflows/*.py）。

        通过遍历调用栈，跳过 agentclaw 框架内部帧，返回首个外部文件路径。
        """
        frame = inspect.currentframe()
        try:
            current_file = Path(__file__).resolve()
            cursor = frame.f_back if frame else None
            first_non_self: Optional[Path] = None
            while cursor:
                file_path = cursor.f_globals.get("__file__")
                if file_path:
                    candidate = Path(file_path).resolve()
                    if candidate == current_file:
                        cursor = cursor.f_back
                        continue
                    if first_non_self is None:
                        first_non_self = candidate
                    if not Workflow._is_framework_internal_file(candidate):
                        return candidate
                cursor = cursor.f_back
            return first_non_self
        except Exception:
            return None
        finally:
            # 显式删除 frame 引用，避免循环引用
            del frame

    def _candidate_base_dirs(self) -> List[Path]:
        """
        配置自动发现的候选目录（按优先级）：
        1) 工作流文件同级目录的父目录（典型：<project>/workflows/*.py -> <project>）
        2) 工作流文件同级目录
        3) 全局运行项目目录（支持导入到 agents/<app>/agents/*.py 的模板工作流）
        4) 当前工作目录
        """
        candidates: List[Path] = []

        if self._definition_file:
            wf_dir = self._definition_file.parent
            candidates.append(wf_dir.parent)
            candidates.append(wf_dir)

        try:
            from agentclaw.config import get_config

            project = get_config().project
            for raw_path in (
                getattr(project, "project_dir", None),
                getattr(project, "models_config", None).parent if getattr(project, "models_config", None) else None,
                getattr(project, "mcp_config", None).parent if getattr(project, "mcp_config", None) else None,
                getattr(project, "skills_dir", None).parent if getattr(project, "skills_dir", None) else None,
            ):
                if raw_path:
                    candidates.append(Path(raw_path))
        except Exception as exc:
            logger.debug(f"读取全局项目配置失败，跳过运行项目目录候选: {exc}")

        candidates.append(Path.cwd().resolve())

        deduped: List[Path] = []
        seen: set[str] = set()
        for p in candidates:
            try:
                rp = p.resolve()
            except Exception:
                continue
            key = str(rp)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(rp)
        return deduped

    def _resolve_explicit_path(self, raw_path: str) -> Optional[Path]:
        """
        解析显式配置路径（支持相对路径，按候选 base 目录兜底）。
        """
        p = Path(raw_path)
        probes: List[Path] = []

        if p.is_absolute():
            probes.append(p)
        else:
            for base in self._candidate_base_dirs():
                probes.append(base / p)
            probes.append(Path.cwd() / p)

        seen: set[str] = set()
        for probe in probes:
            try:
                rp = probe.resolve()
            except Exception:
                continue
            key = str(rp)
            if key in seen:
                continue
            seen.add(key)
            if rp.exists():
                return rp
        return None

    def _find_models_config_path(self) -> Optional[Path]:
        """查找 models.json（显式优先，失败时自动发现）。"""
        if self._models_config:
            explicit = self._resolve_explicit_path(self._models_config)
            if explicit:
                return explicit
            logger.warning(f"指定的 models 配置文件不存在: {self._models_config}，将尝试自动发现")

        for base in self._candidate_base_dirs():
            for rel in ("models.json", ".kiro/models.json"):
                candidate = (base / rel).resolve()
                if candidate.exists():
                    return candidate
        return None

    def _find_mcp_config_path(self) -> Optional[Path]:
        """查找 mcp.json（显式优先，失败时自动发现）。"""
        if self._mcp_config:
            explicit = self._resolve_explicit_path(self._mcp_config)
            if explicit:
                return explicit
            logger.warning(
                f"指定的 MCP 配置文件不存在: {self._mcp_config} (CWD: {Path.cwd()})，将尝试自动发现"
            )

        for base in self._candidate_base_dirs():
            for rel in ("mcp.json", ".kiro/mcp.json"):
                candidate = (base / rel).resolve()
                if candidate.exists():
                    return candidate
        return None

    def _find_skills_dir(self) -> Optional[Path]:
        """查找 skills 目录（显式优先，失败时自动发现）。

        跳过 Python 包（含 __init__.py 的目录），避免将框架
        自身的 agentclaw/skills/ 模块误识别为用户 skills 目录。
        """
        if self._skills_dir:
            explicit = self._resolve_explicit_path(self._skills_dir)
            if explicit and explicit.is_dir():
                return explicit
            logger.warning(f"指定的 skills 目录不存在: {self._skills_dir}，将尝试自动发现")

        for base in self._candidate_base_dirs():
            candidate = (base / "skills").resolve()
            if candidate.exists() and candidate.is_dir() and not (candidate / "__init__.py").exists():
                return candidate
        return None

    def _ensure_components(self) -> None:
        """确保必要组件已初始化"""
        if self._llm_manager is None:
            from agentclaw.model.manager import LLMManager

            models_path = self._find_models_config_path()
            if models_path:
                self._llm_manager = LLMManager(config_path=str(models_path))
                self._llm_manager.on_init(self)
                logger.debug(f"自动加载 LLMManager: {models_path}")
        
        if self._prompt_manager is None:
            from agentclaw.prompt.manager import PromptManager
            import os
            
            # 智能选择 source：如果有数据库配置，使用 database，否则使用 memory
            source = "memory"
            hot_reload = False
            
            if os.getenv("PG_HOST"):
                source = "database"
                hot_reload = True
                logger.debug("检测到数据库配置，PromptManager 使用 database 模式")
            
            self._prompt_manager = PromptManager(
                source=source,
                hot_reload=hot_reload,
            )
            self._prompt_manager.on_init(self)
            logger.debug(f"自动加载 PromptManager (source={source}, hot_reload={hot_reload})")
        
        # 自动加载 MCP 配置
        if self._mcp_toolkit is None:
            self._try_load_mcp()
        
        # 自动加载 Skills
        if self._skill_manager is None:
            self._try_load_skills()
        
        # 注册节点提示词到 PromptManager（只做一次）
        if self._prompt_manager and not self._prompts_registered:
            for node in self._nodes.values():
                if hasattr(node, 'system_prompt') and node.system_prompt:
                    self._prompt_manager.register_default(node.id, node.system_prompt)
                elif hasattr(node, 'prompt') and node.prompt:
                    self._prompt_manager.register_default(node.id, node.prompt)
            self._prompts_registered = True
    
    def _try_load_mcp(self) -> None:
        """尝试自动加载 MCP 配置（使用全局缓存避免重复创建）"""
        config_path = self._find_mcp_config_path()
        if not config_path:
            logger.debug("未找到 mcp.json，跳过 MCP 加载")
            return

        try:
            resolved = str(config_path.resolve()) if hasattr(config_path, 'resolve') else str(Path(config_path).resolve())

            # 复用已有的 MCPToolKit（同一 mcp.json 只创建一次）
            cached = _mcp_toolkit_cache.get(resolved)
            if cached is not None:
                self._mcp_toolkit = cached
                self._components.append(cached)
                logger.info(f"复用 MCPToolKit: {config_path} (workflow={self.id})")
                return

            from agentclaw.mcp import MCPToolKit
            self._mcp_toolkit = MCPToolKit.from_config(config_path)
            self._mcp_toolkit.on_init(self)
            _mcp_toolkit_cache[resolved] = self._mcp_toolkit
            self._components.append(self._mcp_toolkit)
            logger.info(f"自动加载 MCP 配置: {config_path}")
        except Exception as e:
            logger.warning(f"加载 MCP 配置失败 ({config_path}): {e}")
    
    def _try_load_skills(self) -> None:
        """尝试自动加载 Skills（使用全局单例）"""
        try:
            from agentclaw.skills import get_skill_manager

            skills_dir = self._find_skills_dir()
            if not skills_dir:
                logger.debug("未找到项目 skills 目录，跳过 Skills 加载: workflow=%s", self.id)
                self._skill_manager = None
                return

            self._skill_manager = get_skill_manager(skills_dir=str(skills_dir))
            if self._skill_manager is None:
                logger.debug("项目 skills 目录不可用，跳过 Skills 加载: workflow=%s, skills_dir=%s", self.id, skills_dir)
                return

            self._skill_manager.refresh()
            skills = self._skill_manager.list()
            skill_summary = [
                {
                    "name": skill.name,
                    "dir": self._skill_manager.get_skill_dir_name(skill.name),
                    "refs": len(skill.references),
                    "scripts": len(skill.scripts),
                }
                for skill in skills
            ]
            logger.info(
                "项目 Skills 加载完成: workflow=%s, skills_dir=%s, count=%s, skills=%s",
                self.id,
                str(skills_dir) if skills_dir else "<default>",
                len(skills),
                skill_summary,
            )
        except Exception as e:
            logger.warning(f"加载 Skills 失败: {e}")
    
    # ========================================================================
    # Inputs 定义（推荐）
    # ========================================================================
    
    def _init_inputs(self, inputs: Any) -> None:
        """
        初始化输入参数定义
        
        支持三种格式：
        1. 字典简写: {"query": str, "count": int}
        2. Input 对象列表: [Input("query", str, required=True)]
        3. Pydantic BaseModel 类
        """
        from agentclaw.inputs import parse_inputs
        
        self._input_schema = parse_inputs(inputs)
        
        if self._input_schema:
            # 同步更新 input_schema（兼容旧版 API）
            self.input_schema = self._input_schema.to_json_schema()
            logger.debug(f"初始化 inputs: {list(self._input_schema.inputs.keys())}")

    @staticmethod
    def _is_text_input_type(input_type: Any) -> bool:
        """判断输入类型是否为文本（str / Optional[str] / Union[str, None]）。"""
        if input_type is str:
            return True
        origin = get_origin(input_type)
        if origin is Union:
            args = [arg for arg in get_args(input_type) if arg is not type(None)]
            return len(args) == 1 and args[0] is str
        return False

    def _validate_user_input_binding(self) -> None:
        """
        校验 user_input 与 inputs 的绑定关系。

        约束：
        1) 配置了 user_input 时，inputs 必须存在且包含同名字段
        2) 对应字段类型必须是文本（str/Optional[str]）
        """
        if not self._user_input_field:
            return

        if not self._input_schema:
            raise ConfigError(
                f"user_input='{self._user_input_field}' requires inputs schema with the same field."
            )

        user_input_def = self._input_schema.inputs.get(self._user_input_field)
        if user_input_def is None:
            raise ConfigError(
                f"user_input='{self._user_input_field}' 指定的字段不存在于 inputs 中。"
                f"可用字段: {list(self._input_schema.inputs.keys())}"
            )

        if not self._is_text_input_type(user_input_def.type):
            raise ConfigError(
                f"user_input='{self._user_input_field}' must bind to a string input field in inputs."
            )
    
    def get_input_schema(self) -> Optional[dict]:
        """获取输入参数 Schema（JSON Schema 格式）"""
        if self._input_schema:
            return self._input_schema.to_json_schema()
        return None
    
    def get_inputs_config(self) -> Optional[dict]:
        """获取输入参数配置（用于 API 返回）"""
        if self._input_schema:
            return self._input_schema.to_dict()
        return None
    
    def get_form_config(self) -> Optional[list]:
        """获取前端表单配置"""
        if self._input_schema:
            return self._input_schema.to_form_config()
        return None
    
    def get_user_input_field(self) -> Optional[str]:
        """获取用户输入字段名"""
        return self._user_input_field
    
    def validate_inputs(self, data: dict) -> List[str]:
        """验证输入参数，返回错误列表"""
        if self._input_schema:
            return self._input_schema.validate(data)
        return []
    
    # ========================================================================
    # Checkpointer
    # ========================================================================
    
    async def _ensure_checkpointer(self) -> None:
        """确保 Checkpointer 已初始化"""
        if self._checkpointer_initialized:
            return
        
        try:
            from agentclaw.state.checkpointer import get_checkpointer, setup_checkpointer, create_memory_checkpointer
            import os
            
            if os.getenv("PG_HOST"):
                # 先尝试获取全局 checkpointer
                self._checkpointer = get_checkpointer()
                
                # 如果没有，则初始化
                if self._checkpointer is None:
                    self._checkpointer = await setup_checkpointer()
                
                if self._checkpointer:
                    logger.info("使用 PostgreSQL Checkpointer")
                else:
                    logger.warning("PostgreSQL Checkpointer 初始化失败，使用内存模式")
                    self._checkpointer = create_memory_checkpointer()
            else:
                self._checkpointer = create_memory_checkpointer()
                logger.debug("使用内存 Checkpointer")
            
            self._checkpointer_initialized = True
        except Exception as e:
            logger.warning(f"Checkpointer 初始化失败: {e}")
            self._checkpointer = None
            self._checkpointer_initialized = True
    
    async def _connect_mcp_once(self) -> None:
        async with self._mcp_connect_lock:
            if not self._mcp_toolkit or self._mcp_toolkit.is_connected:
                return
            try:
                results = await self._mcp_toolkit.connect(
                    connect_timeout=_get_mcp_connect_timeout()
                )
                status, connected, total = _classify_mcp_connect_results(results)
                if status == "connected":
                    logger.info(f"MCP 连接完成: {connected}/{total} 成功")
                elif status == "failed":
                    logger.warning("MCP 连接失败，工具调用可能不可用")
            except Exception as e:
                logger.warning(f"MCP 连接失败: {e}")

    async def _ensure_mcp_connected(self, *, wait: bool = True) -> None:
        """确保 MCP 已连接（如果有配置）"""
        self._ensure_components()

        if not self._mcp_toolkit or self._mcp_toolkit.is_connected:
            return
        if getattr(self._mcp_toolkit, "is_connecting", False):
            return

        task = self._mcp_connect_task
        if task and task.done():
            self._mcp_connect_task = None
            task = None

        if task is None:
            task = asyncio.create_task(
                self._connect_mcp_once(),
                name=f"workflow-mcp-connect-{self.id}",
            )
            self._mcp_connect_task = task
            task.add_done_callback(
                lambda finished: (
                    setattr(self, "_mcp_connect_task", None)
                    if self._mcp_connect_task is finished else None
                )
            )

        if wait:
            await task
    
    def _compile_to_langgraph(self):
        """将 Workflow 编译为 LangGraph StateGraph"""
        if self._compiled_graph is not None:
            return self._compiled_graph
        
        try:
            from langgraph.graph import StateGraph
            from langgraph.constants import START, END
            from typing import Any, Annotated
            
            # 构建动态 TypedDict 状态类型
            # 使用 Annotated + reducer 使并行节点可以同时更新不同字段
            def _last_value(existing, new):
                """Reducer: 取最新非 None 值，防止并行分支用 None 覆盖另一分支的有效值"""
                if new is None:
                    return existing
                return new

            def _shallow_merge_value(existing, new):
                """Reducer: shallow merge dict patches from parallel branches."""
                if new is None:
                    return existing
                if isinstance(existing, dict) and isinstance(new, dict):
                    return {**existing, **new}
                return new

            def _deep_merge_value(existing, new):
                """Reducer: deep merge dict patches from parallel branches."""
                if new is None:
                    return existing
                if isinstance(existing, dict) and isinstance(new, dict):
                    from agentclaw.graph.state_path import merge_path
                    merged = {"value": existing}
                    merge_path(merged, "value", new, strategy="deep_merge")
                    return merged["value"]
                return new

            merge_reducers = {
                "replace": _last_value,
                "shallow_merge": _shallow_merge_value,
                "deep_merge": _deep_merge_value,
            }

            field_merge_strategies = {}
            for node_id in self._node_order:
                node = self._nodes[node_id]
                if hasattr(node, "get_state_merge_strategies"):
                    try:
                        field_merge_strategies.update(node.get_state_merge_strategies())  # type: ignore[attr-defined]
                    except Exception as e:
                        logger.debug(f"读取节点 {node_id} 状态合并策略失败: {e}")

            def _field_reducer(field_name: str):
                strategy = field_merge_strategies.get(field_name, "replace")
                return merge_reducers.get(strategy, _last_value)
            
            # 收集所有可能的状态字段（从 _state_schema + 节点 output_key + inputs）
            all_fields = {}
            for key in self._state_schema:
                all_fields[key] = Annotated[Any, _field_reducer(key)]
            
            # 添加节点的 output_key
            for node_id in self._node_order:
                node = self._nodes[node_id]
                output_key = getattr(node, 'output_key', None) or node.id
                if output_key not in all_fields:
                    all_fields[output_key] = Annotated[Any, _field_reducer(output_key)]
                # HumanNode 的 feedback_field 也需要写入 state
                feedback_field = getattr(node, 'feedback_field', None)
                if feedback_field and feedback_field not in all_fields:
                    all_fields[feedback_field] = Annotated[Any, _field_reducer(feedback_field)]
            
            # 添加 inputs 定义的字段
            if self._input_schema:
                for key in self._input_schema.inputs:
                    if key not in all_fields:
                        all_fields[key] = Annotated[Any, _field_reducer(key)]
            
            # 添加常见的内部字段
            for internal_key in ['thread_id', 'user_id', '__messages__', '__status__', '__interrupted__', '__files__',
                                 '__filtered_tools__', '__filtered_skill_names__', '__skip_filter__', '__runtime_model_id__',
                                 '__request_from_channel__', '__disable_confirm_tool__', '__tool_confirmation_required__',
                                 '__tool_confirmation_level__']:
                if internal_key not in all_fields:
                    all_fields[internal_key] = Annotated[Any, _last_value]

            # 扫描 LLMNode 的 filter key，确保 state schema 包含
            for node_id in self._node_order:
                _n = self._nodes[node_id]
                for _fk in (getattr(_n, 'tools_filter_key', None), getattr(_n, 'skills_filter_key', None)):
                    if _fk and _fk not in all_fields:
                        all_fields[_fk] = Annotated[Any, _field_reducer(_fk)]
            
            # 动态创建 TypedDict
            from typing import TypedDict
            WorkflowState = TypedDict('WorkflowState', {k: v for k, v in all_fields.items()})  # type: ignore
            
            builder = StateGraph(WorkflowState)
            
            # 添加所有节点
            for node_id in self._node_order:
                node = self._nodes[node_id]
                # 将 agentclaw 节点包装为 LangGraph 节点函数
                node_fn = self._wrap_node_for_langgraph(node)
                builder.add_node(node_id, node_fn)
            
            # 设置入口点：优先使用显式指定的开始节点，否则使用第一个节点
            start_node = self._start_node if self._start_node else (self._node_order[0] if self._node_order else None)
            if start_node:
                builder.add_edge(START, start_node)
                logger.debug(f"设置入口点: START -> {start_node}")
            
            # 添加边（支持一对多并行）
            for from_node, to_nodes in self._edges.items():
                for to_node in to_nodes:
                    if to_node in ("__end__", "END"):
                        builder.add_edge(from_node, END)
                    else:
                        builder.add_edge(from_node, to_node)
            
            # 添加条件边
            for from_node, edge_config in self._conditional_edges.items():
                condition = edge_config["condition"]
                targets = edge_config.get("targets")
                
                if edge_config.get("direct_mode"):
                    # 直接返回节点名的条件函数
                    def make_direct_condition(cond_fn):
                        def wrapped(state):
                            result = cond_fn(state)
                            return END if result in ("__end__", "END") else result
                        return wrapped
                    builder.add_conditional_edges(from_node, make_direct_condition(condition))
                else:
                    # 转换目标中的 __end__ 为 END
                    converted_targets = {}
                    for key, target in (targets or {}).items():
                        converted_targets[key] = END if target in ("__end__", "END") else target
                    builder.add_conditional_edges(from_node, condition, converted_targets)
            
            # 编译，传入 checkpointer
            self._compiled_graph = builder.compile(checkpointer=self._checkpointer)
            logger.info(f"工作流已编译为 LangGraph: {self.id}")
            return self._compiled_graph
            
        except Exception as e:
            logger.error(f"编译 LangGraph 失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _build_langgraph_config(self, thread_id: str) -> dict:
        """Build LangGraph runtime config from AgentClaw workflow settings."""

        limit = int(self.recursion_limit or 0)
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": limit if limit > 0 else LANGGRAPH_UNLIMITED_RECURSION_LIMIT,
        }
    
    def _wrap_node_for_langgraph(self, node):
        """将 agentclaw 节点包装为 LangGraph 节点函数"""
        async def wrapped_node(state: dict):
            # 创建临时 context
            context = WorkflowContext(
                thread_id=state.get("thread_id"),
                metadata={},
            )
            context.from_channel = bool(state.get("__request_from_channel__"))
            context.disable_confirm_tool = bool(state.get("__disable_confirm_tool__"))
            context.tool_confirmation_required = bool(state.get("__tool_confirmation_required__"))
            context.tool_confirmation_level = str(state.get("__tool_confirmation_level__") or ("high" if context.tool_confirmation_required else "off"))
            if state.get("user_id") is not None:
                context.user_id = state.get("user_id")
            context.workflow_id = self.id
            context.workflow_name = self.name
            context.user_input_field = self._user_input_field
            context.runtime_model_id = state.get("__runtime_model_id__")
            context.timeout = self.timeout if self.timeout and self.timeout > 0 else None

            # 加载运行时工具配置（禁用的 skills/tools）
            try:
                from agentclaw.api.services.tool_config_service import get_tool_config_manager
                tcm = get_tool_config_manager()
                context.disabled_skills = tcm.get_disabled_skills(self.id)
                context.disabled_tools = tcm.get_disabled_tools(self.id)
            except Exception:
                pass
            
            self._ensure_components()
            context.prompt_manager = self._prompt_manager
            context.llm_manager = self._llm_manager
            context.skill_manager = self._skill_manager
            
            # 设置 toolkit (支持 ToolKit 和 MCPToolKit)
            from agentclaw.node.toolkit import ToolKit
            from agentclaw.mcp.toolkit import MCPToolKit
            for comp in self._components:
                if isinstance(comp, (ToolKit, MCPToolKit)):
                    context.toolkit = comp
                    break
            
            # 创建工作副本
            working_state = state.copy()
            
            # 获取或创建 OutputChannel
            from agentclaw.runtime.streaming.context import OutputChannel, _output_channel_var
            import time
            existing_channel = _output_channel_var.get()
            
            if existing_channel:
                # 复用已有的 channel，更新 state 引用
                existing_channel.state = working_state
                channel = existing_channel
                token = None  # 不需要重置
            else:
                # 创建临时 OutputChannel
                channel = OutputChannel(
                    workflow_id=self.id,
                    thread_id=state.get("thread_id", ""),
                    stream_mode=False,
                )
                channel.state = working_state
                token = _output_channel_var.set(channel)
            
            # 设置当前节点名（用于 message 事件的 node_id）
            prev_node = channel._current_node
            channel._current_node = node.id
            
            # 获取节点类型
            node_type = type(node).__name__.lower().replace("node", "")
            
            # 推送 node_started 事件
            node_start_time = time.perf_counter()
            state_keys_before = set(working_state.keys())
            node_inputs = {k: v for k, v in working_state.items() if not k.startswith("__")}
            node_title = getattr(node, 'description', None) or node.id
            await channel.push_node_started(node.id, node_type, inputs=node_inputs, title=node_title)

            try:
                # 执行节点
                result = await node.execute(working_state, context)

                # 合并 output(save_to_context=True) 添加的 __messages__
                if channel.state and "__messages__" in channel.state:
                    result["__messages__"] = channel.state["__messages__"]

                # 推送 node_finished 事件（只显示节点新增/变更的 key，过滤内部字段）
                elapsed_time = time.perf_counter() - node_start_time
                node_outputs = {k: v for k, v in result.items() if k not in _INTERNAL_HEAVY_KEYS and (k not in state_keys_before or result[k] is not working_state.get(k))}
                await channel.push_node_finished(
                    node.id,
                    status="succeeded",
                    outputs=node_outputs,
                    elapsed_time=elapsed_time,
                )
                
                return result
            except Exception as e:
                # 检查是否是中断（GraphInterrupt）
                from langgraph.errors import GraphInterrupt
                elapsed_time = time.perf_counter() - node_start_time
                
                if isinstance(e, GraphInterrupt):
                    # 中断不是失败，标记为 interrupted
                    await channel.push_node_finished(
                        node.id,
                        status="interrupted",
                        elapsed_time=elapsed_time,
                    )
                else:
                    # 推送 node_finished 事件（失败）
                    await channel.push_node_finished(
                        node.id,
                        status="failed",
                        elapsed_time=elapsed_time,
                        error=str(e),
                    )
                raise
            finally:
                # 恢复当前节点名
                channel._current_node = prev_node
                # 恢复 ContextVar（仅当我们创建了新的 channel 时）
                if token is not None:
                    _output_channel_var.reset(token)
        
        return wrapped_node
    
    @staticmethod
    def _get_nested_value(state: dict, key: str):
        """获取嵌套字段值，支持 a.b.c 格式"""
        parts = key.split(".")
        value = state
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    @staticmethod
    def _has_effective_input_changes(previous_state: dict, new_inputs: Optional[dict]) -> bool:
        """
        判断本次输入相对上次快照是否有实质变化。

        仅比较用户可见输入字段，忽略内部字段（__*）与 thread_id。
        """
        if not new_inputs:
            return False

        for key, new_value in new_inputs.items():
            if key == "thread_id" or key.startswith("__"):
                continue
            if previous_state.get(key) != new_value:
                return True
        return False
    
    def add_node(self, node: Node) -> Workflow:
        """添加节点"""
        # 校验 node id 是否重复
        if node.id in self._nodes:
            raise ValueError(
                f"Node ID '{node.id}' already exists in workflow '{self.id}'. "
                f"Each node must have a unique ID."
            )
        
        self._nodes[node.id] = node
        self._node_order.append(node.id)
        
        output_keys = [getattr(node, 'output_key', None) or node.id]
        if hasattr(node, "get_state_output_keys"):
            try:
                output_keys = list(node.get_state_output_keys())  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f"读取节点 {node.id} 状态输出字段失败: {e}")

        for output_key in output_keys:
            if output_key and output_key not in self._state_schema:
                self._state_schema[output_key] = str
        
        self._compiled_graph = None
        logger.debug(f"添加节点: {node.id}")
        return self
    
    def get_node(self, name: str) -> Optional[Node]:
        """
        获取指定名称的节点
        
        Args:
            name: 节点名称
            
        Returns:
            节点对象，如果不存在返回 None
            
        Example:
            # 获取节点并控制降级
            node = workflow.get_node("classify")
            if node:
                node.force_fallback("主模型响应过慢")
                # 或恢复主模型
                node.force_primary()
        """
        return self._nodes.get(name)
    
    def register_state_field(self, name: str, field_type: type = str) -> Workflow:
        """注册自定义状态字段"""
        if name not in self._state_schema:
            self._state_schema[name] = field_type
            self._compiled_graph = None
        return self
    
    def _parse_output_fields(self, func: Callable) -> List[str]:
        """从函数注解自动解析输出字段"""
        import inspect
        import ast
        
        fields = set()
        type_hints = {}
        
        hints = getattr(func, '__annotations__', {})
        return_type = hints.get('return')
        
        if return_type is not None and return_type is not dict:
            if hasattr(return_type, '__annotations__'):
                type_hints = return_type.__annotations__
        
        try:
            source = inspect.getsource(func)
            lines = source.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('def ') or line.strip().startswith('async def '):
                    lines = lines[i:]
                    break
            if lines:
                indent = len(lines[0]) - len(lines[0].lstrip())
                lines = [line[indent:] if len(line) > indent else line for line in lines]
            source = '\n'.join(lines)
            
            tree = ast.parse(source)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Return) and node.value:
                    if isinstance(node.value, ast.Dict):
                        for key in node.value.keys:
                            field_name = None
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                field_name = key.value
                            elif isinstance(key, ast.Str):
                                field_name = key.s
                            
                            if field_name:
                                fields.add(field_name)
                                field_type = type_hints.get(field_name, str)
                                self.register_state_field(field_name, field_type)
        except Exception as e:
            logger.debug(f"AST 解析失败: {e}")
            for field_name, field_type in type_hints.items():
                fields.add(field_name)
                self.register_state_field(field_name, field_type)
        
        return list(fields)
    
    def node(self, id: Optional[str] = None, *, output_key: Optional[str] = None, 
             output_fields: Optional[List[str]] = None, **node_kwargs):
        """装饰器：将函数注册为工作流节点"""
        def decorator(func: Callable):
            node_id = id or func.__name__
            
            if output_fields:
                for field in output_fields:
                    self.register_state_field(field, str)
            else:
                self._parse_output_fields(func)
            
            node = FunctionNode(
                id=node_id,
                handler=func,
                output_key=output_key or node_id,
                **node_kwargs
            )
            self.add_node(node)
            return func
        return decorator
    
    def llm_node(self, id: Optional[str] = None, *, system_prompt: Optional[str] = None,
                 user_prompt: Optional[str] = None, **node_kwargs):
        """装饰器：注册 LLM 节点"""
        def decorator(func: Callable):
            node_id = id or func.__name__
            node = LLMNode(
                id=node_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                **node_kwargs
            )
            self.add_node(node)
            return func
        return decorator
    
    def add_router(self, after: str, routes: Dict[str, Union[str, BaseNode]],
                   condition: Union[Callable[[dict], str], str]) -> Workflow:
        """添加路由节点
        
        Args:
            after: 路由源节点名
            routes: 路由映射 {条件值: 目标节点}，支持 "default" 作为兜底
            condition: 条件函数或状态字段名（支持嵌套访问如 "a.b.c"）
        """
        # 构建目标映射
        targets = {}
        default_target = None
        for key, target in routes.items():
            if isinstance(target, str):
                target_name = target
            else:
                self._nodes[target.name] = target
                target_name = target.name
            
            if key == "default":
                default_target = target_name
            else:
                targets[key] = target_name
        
        # 包装 condition 函数，处理 default 情况
        if isinstance(condition, str):
            key = condition
            raw_condition = lambda s, k=key: self._get_nested_value(s, k)
        else:
            raw_condition = condition
        
        # 创建带 default 处理的 condition
        valid_keys = set(targets.keys())
        def wrapped_condition(state, cond=raw_condition, keys=valid_keys, default=default_target):
            result = cond(state)
            if result in keys:
                return result
            elif default:
                return "default"
            else:
                # 没有 default，返回第一个目标
                return next(iter(keys)) if keys else None
        
        # 如果有 default，添加到 targets
        if default_target:
            targets["default"] = default_target
        
        if after in self._edges:
            del self._edges[after]
        
        target_names = list(targets.values())
        for target_name in target_names:
            if target_name in self._edges:
                # 检查是否有边指向其他路由目标
                self._edges[target_name] = [t for t in self._edges[target_name] if t not in target_names]
                if not self._edges[target_name]:
                    del self._edges[target_name]
        
        self._conditional_edges[after] = {
            "condition": wrapped_condition,
            "targets": targets,
            "direct_mode": False,
        }
        
        self._compiled_graph = None
        return self

    def add_llm_router(self, after: str, routes: Dict[str, Union[str, "BaseNode"]],
                        prompt: str, input_field: Optional[str] = None,
                        model_id: Optional[str] = None) -> Workflow:
        """添加 LLM 意图识别路由

        内部自动创建隐藏 LLMNode 进行意图分类，根据 LLM 输出路由到不同目标节点。

        Args:
            after: 路由源节点名
            routes: 路由映射 {意图: 目标节点}，支持 "default" 作为兜底
            prompt: 意图识别提示词（描述各意图的含义）
            input_field: 传给 LLM 的 state 字段名，默认使用 user_input_field
            model_id: 可选，指定模型 ID

        Example::

            workflow.add_llm_router(
                after="review",
                routes={"approved": "finalize", "revise": "draft", "default": "draft"},
                prompt="判断用户审核意见：满意/没意见→approved，有修改意见→revise",
                input_field="review_feedback",
            )
        """
        from agentclaw.node.llm import LLMNode

        # 收集有效路由 key（排除 default）
        route_keys = [k for k in routes.keys() if k != "default"]

        # 自动生成 system_prompt
        keys_desc = ", ".join(route_keys)
        system_prompt = (
            f"You are an intent classifier. Classify the user input into one of these intents: {keys_desc}\n"
            f"{prompt}\n\n"
            f'Output JSON only: {{{{"route": "<intent>"}}}}\n'
            f"Do not output anything else."
        )

        # 确定 input_field
        effective_input = input_field or self._user_input_field or "user_input"

        # 创建隐藏 LLMNode
        router_id = f"__{after}_llm_router__"
        output_key = f"__{after}_route__"

        router_node = LLMNode(
            id=router_id,
            system_prompt=system_prompt,
            user_prompt=f"{{{effective_input}}}",
            output_format="json",
            output_key=output_key,
            output_to_user=False,
            save_to_context=False,
            model_id=model_id,
        )

        # 注册隐藏节点
        self.add_node(router_node)

        # 连接 after → 隐藏节点
        self.add_edge(after, router_id)

        # 用 add_router 完成路由
        self.add_router(
            after=router_id,
            routes=routes,
            condition=lambda state, _key=output_key: (
                state.get(_key, {}).get("route")
                if isinstance(state.get(_key), dict)
                else "default"
            ),
        )

        return self

    def add_conditional_edge(self, source: str, condition: Callable[[dict], str],
                             targets: Optional[Dict[str, str]] = None) -> Workflow:
        """添加条件边"""
        if targets:
            for target in targets.values():
                if target not in self._nodes and target not in ("__end__", "END"):
                    raise ValueError(f"目标节点 '{target}' 不存在")
        
        if source in self._edges:
            del self._edges[source]
        
        self._compiled_graph = None
        
        if targets is None:
            self._conditional_edges[source] = {
                "condition": condition,
                "targets": None,
                "direct_mode": True,
            }
        else:
            self._conditional_edges[source] = {
                "condition": condition,
                "targets": targets,
                "direct_mode": False,
            }
        return self

    def _attach_component(self, component: "BaseComponent") -> None:
        """Attach component once and sync internal manager references."""
        if component in self._components:
            return

        self._components.append(component)
        component.on_init(self)

        from agentclaw.prompt.manager import PromptManager
        from agentclaw.model.manager import LLMManager
        from agentclaw.node.toolkit import ToolKit
        from agentclaw.mcp.toolkit import MCPToolKit

        if isinstance(component, PromptManager):
            self._prompt_manager = component
        elif isinstance(component, LLMManager):
            self._llm_manager = component
        elif isinstance(component, ToolKit):
            # Primary local toolkit used by workflow.tool and LLM tool schemas.
            if self._toolkit is None:
                self._toolkit = component
        elif isinstance(component, MCPToolKit):
            self._mcp_toolkit = component

    def _resolve_primary_toolkit(self) -> Optional["ToolKit"]:
        """Resolve and cache primary local ToolKit if exists."""
        from agentclaw.node.toolkit import ToolKit

        if isinstance(self._toolkit, ToolKit):
            return self._toolkit

        for comp in self._components:
            if isinstance(comp, ToolKit):
                self._toolkit = comp
                return comp
        return None

    def _ensure_default_toolkit(self) -> "ToolKit":
        """
        Ensure a default local ToolKit exists for `@workflow.tool`.

        This is the default path for simple workflow-local tools.
        """
        from agentclaw.node.toolkit import ToolKit

        existing = self._resolve_primary_toolkit()
        if existing is not None:
            return existing

        toolkit = ToolKit()
        self._attach_component(toolkit)
        self._toolkit = toolkit
        logger.info(f"自动创建默认 ToolKit: workflow={self.id}")
        return toolkit

    def register_toolkit(
        self,
        toolkit: "ToolKit",
        *,
        merge: bool = True,
        overwrite: bool = False,
    ) -> Workflow:
        """
        Register a local ToolKit for advanced reuse/plugin scenarios.

        Defaults to merging tools into primary toolkit to keep one effective
        local toolkit for LLM tool schema/execution.
        """
        from agentclaw.node.toolkit import ToolKit

        if not isinstance(toolkit, ToolKit):
            raise TypeError(
                f"register_toolkit expects ToolKit, got {type(toolkit).__name__}"
            )

        primary = self._resolve_primary_toolkit()
        if primary is None:
            self._attach_component(toolkit)
            self._toolkit = toolkit
            logger.debug(f"注册本地 ToolKit: workflow={self.id}, tools={len(toolkit.list_tools())}")
            return self

        # Same object, just ensure attached once.
        if primary is toolkit:
            self._attach_component(toolkit)
            return self

        if not merge:
            # Keep compatibility for explicit multiple toolkit attachment.
            self._attach_component(toolkit)
            logger.debug(
                f"附加额外 ToolKit(merge=False): workflow={self.id}, tools={len(toolkit.list_tools())}"
            )
            return self

        merged = 0
        skipped = 0
        for tool_name in toolkit.list_tools():
            tool_def = toolkit.get_tool(tool_name)
            if tool_def is None:
                continue

            exists = primary.get_tool(tool_name) is not None
            if exists and not overwrite:
                skipped += 1
                continue

            primary.register(tool_def)
            merged += 1

        if skipped:
            logger.warning(
                f"ToolKit 合并存在同名工具，已跳过: workflow={self.id}, skipped={skipped} "
                "(set overwrite=True to replace)"
            )
        logger.debug(
            f"合并 ToolKit 完成: workflow={self.id}, merged={merged}, skipped={skipped}, overwrite={overwrite}"
        )
        return self

    def tool(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        params: Optional[Dict[str, Dict[str, Any]]] = None,
        require_approval: bool = False,
        timeout: int = 30,
    ) -> Callable:
        """
        Decorator: register workflow-local tool via default ToolKit.

        Example:
            @workflow.tool
            def query_db(sql: str) -> str:
                ...
        """
        toolkit = self._ensure_default_toolkit()
        return toolkit.tool(
            func=func,
            name=name,
            description=description,
            params=params,
            require_approval=require_approval,
            timeout=timeout,
        )
    
    def use(self, component: BaseComponent) -> Workflow:
        """注册组件"""
        from agentclaw.node.toolkit import ToolKit

        # Backward-compatible path: workflow.use(toolkit)
        if isinstance(component, ToolKit):
            self.register_toolkit(component)
            logger.debug(f"注册组件: {component.__class__.__name__}")
            return self

        self._attach_component(component)
        logger.debug(f"注册组件: {component.__class__.__name__}")
        return self
    
    @property
    def llm(self):
        if not self._llm_manager:
            raise RuntimeError("LLMManager 未配置")
        return self._llm_manager
    
    @property
    def prompts(self):
        if not self._prompt_manager:
            raise RuntimeError("PromptManager 未配置")
        return self._prompt_manager
    
    def add_edge(self, from_node: str, to_node: Union[str, List[str]]) -> Workflow:
        """
        添加普通边（支持一对多并行）
        
        当一个节点连接多个目标时，这些目标会并行执行。
        
        Args:
            from_node: 源节点名（可以是 "__start__" 表示工作流入口）
            to_node: 目标节点名或列表（可以是 "__end__" 表示工作流结束）
            
        Example:
            workflow.add_edge("__start__", "first_node")  # 设置入口点
            workflow.add_edge("node1", "node2")           # 普通边
            workflow.add_edge("last_node", "__end__")     # 设置结束点
            
            # 并行执行方式1：多次调用
            workflow.add_edge("start", "task_a")
            workflow.add_edge("start", "task_b")
            workflow.add_edge("start", "task_c")
            
            # 并行执行方式2：列表语法（推荐）
            workflow.add_edge("start", ["task_a", "task_b", "task_c"])
        """
        # 如果 to_node 是列表，处理并行分支
        if isinstance(to_node, list):
            if from_node in ("__start__", "START"):
                if len(to_node) == 1:
                    # 单目标：直接设置入口点
                    return self.add_edge(from_node, to_node[0])
                # 多目标：创建虚拟入口节点，走 edges 并行调度
                from agentclaw.node.custom import CustomNode as _CN
                class _StartPassthrough(_CN):
                    def process(self, **kwargs):
                        return {}
                _start = _StartPassthrough(id="__start_fork__", output_to_user=False, description="初始化智能体")
                if "__start_fork__" not in self._nodes:
                    self.add_node(_start)
                self._start_node = "__start_fork__"
                for target in to_node:
                    if target not in self._nodes:
                        raise ValueError(f"目标节点 '{target}' 不存在")
                    if "__start_fork__" not in self._edges:
                        self._edges["__start_fork__"] = []
                    if target not in self._edges["__start_fork__"]:
                        self._edges["__start_fork__"].append(target)
                self._compiled_graph = None
                return self
            else:
                for target in to_node:
                    self.add_edge(from_node, target)
                return self

        # 处理 __start__ 特殊节点
        if from_node in ("__start__", "START"):
            if to_node not in self._nodes:
                raise ValueError(f"目标节点 '{to_node}' 不存在")
            self._start_node = to_node
            self._compiled_graph = None
            logger.debug(f"设置入口点: START -> {to_node}")
            return self
        
        # 处理普通边
        if from_node not in self._nodes:
            raise ValueError(f"源节点 '{from_node}' 不存在")
        if to_node not in self._nodes and to_node not in ("__end__", "END"):
            raise ValueError(f"目标节点 '{to_node}' 不存在")
        
        # 支持一对多：追加到列表
        if from_node not in self._edges:
            self._edges[from_node] = []
        if to_node not in self._edges[from_node]:
            self._edges[from_node].append(to_node)
        
        self._compiled_graph = None
        return self
    
    def interrupt_node(self, id: str, **kwargs) -> Callable:
        """装饰器：注册中断节点（人工介入）"""
        def decorator(func: Callable) -> Callable:
            # 创建一个带 handler 的 HumanNode
            node = HumanNode(
                id=id,
                interrupt=True,
                **kwargs
            )
            self.add_node(node)
            
            @functools.wraps(func)
            async def wrapper(*args, **kw):
                return await func(*args, **kw)
            return wrapper
        return decorator
    
    async def _ensure_tracing(self) -> None:
        """确保追踪器已初始化（如果启用）"""
        if not self.tracing:
            return
        
        from agentclaw.runtime.tracing import get_db_tracer
        tracer = get_db_tracer()
        
        # 如果还没有 tracer，尝试自动初始化
        if tracer is None:
            from agentclaw.runtime.tracing.db_tracer import auto_setup_tracing
            await auto_setup_tracing()
    
    def run(self, inputs: Optional[dict] = None, context: Optional[WorkflowContext] = None, *,
            stream: bool = False, thread_id: Optional[str] = None, user_id: Optional[str] = None,
            timeout: Optional[int] = None, metadata: Optional[dict] = None,
            debug: bool = False, debug_queue: Optional[asyncio.Queue] = None):
        """执行工作流
        
        Args:
            inputs: 输入数据
            context: 上下文（用于子工作流继承）
            stream: 是否流式输出
            thread_id: 会话 ID
            user_id: 用户 ID
            timeout: 超时时间
            metadata: 元数据
            debug: 是否启用调试模式
            debug_queue: 调试输出队列（可选，用于 SSE 流式输出）
        
        Note:
            当 tracing=True（默认）时，会自动检测数据库并启用追踪。
            如果数据库不可用，会给出警告并禁用追踪，不影响工作流执行。
            
            当 debug=True 时，会创建调试会话，支持断点、单步执行等功能。
        """
        if stream:
            return self._run_stream(inputs, context, thread_id, user_id, timeout, metadata, debug, debug_queue)
        else:
            return self._run_blocking(inputs, context, thread_id, user_id, timeout, metadata, debug, debug_queue)
    
    async def _run_with_tracing(self, inputs, context, stream, thread_id, user_id, timeout, metadata):
        """带追踪的执行入口"""
        # 确保追踪器已初始化
        await self._ensure_tracing()
        
        # 检查是否有可用的 tracer
        if self.tracing:
            from agentclaw.runtime.tracing import get_db_tracer, TracedWorkflow
            tracer = get_db_tracer()
            if tracer and tracer.enabled:
                traced = TracedWorkflow(self, tracer)
                if stream:
                    async for event in traced.run(inputs, context, stream=True, thread_id=thread_id,
                                                   user_id=user_id, timeout=timeout, metadata=metadata):
                        yield event
                    return
                else:
                    result = await traced.run(inputs, context, stream=False, thread_id=thread_id,
                                              user_id=user_id, timeout=timeout, metadata=metadata)
                    yield result
                    return
        
        # 无追踪的执行
        if stream:
            async for event in self._run_stream_internal(inputs, context, thread_id, user_id, timeout, metadata):
                yield event
        else:
            result = await self._execute_workflow(inputs, context, thread_id, user_id, timeout, metadata)
            yield {
                "outputs": [],
                "state": result,
                "metadata": {
                    "workflow_id": self.id,
                    "thread_id": thread_id or (context.thread_id if context else None),
                }
            }
    
    async def _run_blocking(self, inputs, context, thread_id, user_id, timeout, metadata, debug=False, debug_queue=None) -> dict:
        """非流式执行"""
        import time
        start_time = time.time()
        
        # 设置调试会话
        if debug:
            from agentclaw.runtime.debugger import get_session_manager, set_current_session
            manager = get_session_manager()
            # 调试模式下从 ContextVar 获取当前会话
            from agentclaw.runtime.debugger import get_current_session
            session = get_current_session()
            if not session:
                session = manager.create_session(self.id, thread_id)
                set_current_session(session)
        
        try:
            # 调试模式下跳过 tracing，直接使用内置引擎
            if debug:
                state = await self._execute_builtin(inputs, context, thread_id, user_id, timeout, metadata, debug_queue=debug_queue)
                duration_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "outputs": [],
                    "state": state,
                    "metadata": {
                        "workflow_id": self.id,
                        "thread_id": thread_id or (context.thread_id if context else None),
                        "duration_ms": duration_ms,
                        "node_count": len(self._node_order),
                        "debug": debug,
                    }
                }
            
            # 检查是否已经在 trace 上下文中（由 TracedWorkflow 创建）
            # 如果是，则跳过自动追踪，避免重复包装
            from agentclaw.runtime.tracing.db_tracer import _current_trace
            already_traced = _current_trace.get() is not None
            
            if not already_traced:
                # 确保追踪器已初始化
                await self._ensure_tracing()
                
                # 检查是否有可用的 tracer
                if self.tracing:
                    from agentclaw.runtime.tracing import get_db_tracer, TracedWorkflow
                    tracer = get_db_tracer()
                    if tracer and tracer.enabled:
                        traced = TracedWorkflow(self, tracer)
                        return await traced.run(inputs, context, stream=False, thread_id=thread_id,
                                                user_id=user_id, timeout=timeout, metadata=metadata)
            
            # 无追踪的执行
            state = await self._execute_workflow(inputs, context, thread_id, user_id, timeout, metadata)
            duration_ms = int((time.time() - start_time) * 1000)
            
            return {
                "outputs": [],
                "state": state,
                "metadata": {
                    "workflow_id": self.id,
                    "thread_id": thread_id or (context.thread_id if context else None),
                    "duration_ms": duration_ms,
                    "node_count": len(self._node_order),
                    "debug": debug,
                }
            }
        finally:
            if debug:
                from agentclaw.runtime.debugger import set_current_session
                set_current_session(None)
    
    async def _run_stream(self, inputs, context, thread_id, user_id, timeout, metadata, debug=False, debug_queue=None):
        """流式执行"""
        import time
        start_time = time.time()
        
        # 设置调试会话
        if debug:
            from agentclaw.runtime.debugger import get_session_manager, set_current_session, get_current_session
            manager = get_session_manager()
            session = get_current_session()
            if not session:
                session = manager.create_session(self.id, thread_id)
                set_current_session(session)
        
        try:
            # 检查是否已经在 trace 上下文中
            from agentclaw.runtime.tracing.db_tracer import _current_trace
            already_traced = _current_trace.get() is not None
            
            if not already_traced:
                # 确保追踪器已初始化
                await self._ensure_tracing()
                
                # 检查是否有可用的 tracer
                if self.tracing:
                    from agentclaw.runtime.tracing import get_db_tracer, TracedWorkflow
                    tracer = get_db_tracer()
                    if tracer and tracer.enabled:
                        traced = TracedWorkflow(self, tracer)
                        async for event in traced.run(inputs, context, stream=True, thread_id=thread_id,
                                                      user_id=user_id, timeout=timeout, metadata=metadata):
                            yield event
                        return
            
            # 无追踪的流式执行
            yield {"type": "start", "workflow_id": self.id}
            
            try:
                state = await self._execute_workflow(inputs, context, thread_id, user_id, timeout, metadata)
                duration_ms = int((time.time() - start_time) * 1000)
                yield {
                    "type": "result",
                    "data": state,
                    "metadata": {"workflow_id": self.id, "thread_id": thread_id, "duration_ms": duration_ms, "debug": debug}
                }
            except Exception as e:
                logger.error(f"工作流执行失败: {e}")
                yield {"type": "error", "data": str(e)}
        finally:
            if debug:
                from agentclaw.runtime.debugger import set_current_session
                set_current_session(None)
    
    async def _execute_workflow(self, inputs, parent_context, thread_id, user_id, timeout, metadata) -> dict:
        """核心执行逻辑"""
        # 初始化 checkpointer
        await self._ensure_checkpointer()
        
        # 自动连接 MCP（如果有配置）
        await self._ensure_mcp_connected(wait=False)
        
        # 从 inputs 中获取 thread_id（如果顶层没有）
        effective_thread_id = thread_id or inputs.get("thread_id")
        
        logger.info(f"执行工作流决策: checkpointer={self._checkpointer is not None}, thread_id={effective_thread_id}")
        
        # 统一计算执行超时时间（秒）
        timeout_seconds = timeout if timeout is not None else self.timeout
        if timeout_seconds is not None and timeout_seconds <= 0:
            timeout_seconds = None

        # 如果有 checkpointer 和 thread_id，使用 LangGraph 编译图执行（自动持久化）
        if self._checkpointer and effective_thread_id:
            compiled = self._compile_to_langgraph()
            if compiled:
                logger.info(f"✅ 使用 LangGraph 模式执行: {self.id}")
                return await self._execute_with_langgraph(
                    compiled,
                    inputs,
                    effective_thread_id,
                    timeout_seconds=timeout_seconds,
                    runtime_model_id=getattr(parent_context, "runtime_model_id", None),
                    request_context=parent_context,
                )
            else:
                logger.warning("❌ LangGraph 编译失败，回退到内置引擎")
        else:
            if not self._checkpointer:
                logger.debug("未配置 Checkpointer，使用内置引擎")
            if not effective_thread_id:
                import uuid
                effective_thread_id = str(uuid.uuid4())[:8]
                logger.debug(f"自动生成 thread_id: {effective_thread_id}")
        
        # 否则使用内置执行引擎（同样应用超时保护，防止节点/模型调用无限挂起）
        try:
            if timeout_seconds:
                return await asyncio.wait_for(
                    self._execute_builtin(inputs, parent_context, effective_thread_id, user_id, timeout, metadata),
                    timeout=timeout_seconds,
                )
            return await self._execute_builtin(inputs, parent_context, effective_thread_id, user_id, timeout, metadata)
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"Workflow '{self.id}' execution timed out after {int(timeout_seconds)}s") from e
    
    async def _execute_with_langgraph(
        self,
        compiled_graph,
        inputs: dict,
        thread_id: str,
        *,
        timeout_seconds: Optional[int] = None,
        runtime_model_id: Optional[str] = None,
        request_context: Optional[WorkflowContext] = None,
    ) -> dict:
        """使用 LangGraph 编译图执行（支持 checkpointer 自动持久化）"""
        logger.info(f"使用 LangGraph 执行工作流: {self.id}, thread_id: {thread_id}")

        config = self._build_langgraph_config(thread_id)
        
        from langgraph.errors import GraphInterrupt
        from langgraph.types import Command
        from agentclaw.runtime.streaming import get_output_channel
        
        # 获取 tracer（仅当 tracing=True 时）
        tracer = None
        if self.tracing:
            from agentclaw.runtime.tracing import get_db_tracer
            tracer = get_db_tracer()
        
        # 检查是否已有 OutputChannel（由 API 服务器创建）
        # 如果没有，说明是直接调用，不需要创建（output() 会自动处理）
        existing_channel = get_output_channel()
        
        # 获取用户输入字段名
        user_input_field = self._user_input_field

        def _apply_runtime_model(state: dict) -> dict:
            if runtime_model_id:
                state["__runtime_model_id__"] = runtime_model_id
            else:
                state.pop("__runtime_model_id__", None)
            return state

        async def _ainvoke_with_timeout(payload):
            try:
                if timeout_seconds:
                    return await asyncio.wait_for(
                        compiled_graph.ainvoke(payload, config=config),
                        timeout=timeout_seconds,
                    )
                return await compiled_graph.ainvoke(payload, config=config)
            except asyncio.TimeoutError as e:
                raise TimeoutError(
                    f"Workflow '{self.id}' execution timed out after {int(timeout_seconds)}s"
                ) from e
        
        # 检查是否是恢复调用（已有状态快照且有用户输入）
        # 优先使用 workflow 配置的 user_input 字段；缺失时回退到 __user__
        user_input = self._build_human_resume_value(inputs or {}, user_input_field)

        snapshot = await compiled_graph.aget_state(config)

        # --- 检测残留挂起状态（取消/超时导致的非正常挂起） ---
        # 正常中断（如 HumanNode 审批）在 snapshot.tasks 中有 interrupt data，
        # 而取消/超时导致的挂起没有。检测到后清理 checkpoint 并保留对话上下文。
        if snapshot and snapshot.next and user_input is not None:
            has_interrupt_data = any(
                hasattr(task, 'interrupts') and task.interrupts
                for task in (snapshot.tasks or ())
            )
            if not has_interrupt_data:
                logger.info(
                    f"检测到残留挂起状态（非正常中断），清理后重新执行: {self.id}, "
                    f"thread_id: {thread_id}, pending: {snapshot.next}"
                )
                # snapshot.values 就是挂起节点执行前的完整 state，
                # 包含项目信息、累积变量、对话上下文等所有历史数据
                state = dict(snapshot.values)

                # 被取消执行的用户消息尚未写入 __messages__（LLM 节点在完成后才保存），
                # 需要补充到对话历史中，否则下次请求缺少上下文
                cancelled_user_msg = None
                if user_input_field:
                    cancelled_user_msg = state.get(user_input_field)
                if cancelled_user_msg is None:
                    cancelled_user_msg = state.get("__user__")
                if cancelled_user_msg and isinstance(cancelled_user_msg, str):
                    msgs = state.get("__messages__") or []
                    # 避免重复：检查最后一条消息是否已经是这条
                    last_user = None
                    for m in reversed(msgs):
                        r = m.get("role") if isinstance(m, dict) else getattr(m, "type", None)
                        if r in ("user", "human"):
                            last_user = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
                            break
                    if last_user != cancelled_user_msg:
                        msgs = list(msgs)
                        msgs.append({"role": "user", "content": cancelled_user_msg})
                        state["__messages__"] = msgs
                        logger.info(f"已补充被取消执行的用户消息到 __messages__: {cancelled_user_msg[:50]}")

                state.update(inputs or {})
                state["thread_id"] = thread_id
                _apply_runtime_model(state)

                await self._delete_thread_checkpoints(thread_id)

                if self.welcome and not state.get("__messages__"):
                    state["__messages__"] = [{"role": "assistant", "content": self.welcome}]

                existing_channel = get_output_channel()
                if existing_channel:
                    existing_channel._pre_run_msg_count = len(state.get("__messages__") or [])

                async with self._trace_context(tracer, thread_id, inputs, "start"):
                    try:
                        result = await _ainvoke_with_timeout(state)
                        result = self._check_interrupt_marker(result)
                        if not result.get("__interrupted__"):
                            result = await self._detect_interrupt_from_snapshot(compiled_graph, config, result)
                        if not result.get("__interrupted__"):
                            logger.info(f"残留状态清理后执行完成: {self.id}")
                        return result
                    except GraphInterrupt as e:
                        return await self._handle_interrupt(compiled_graph, config, e)

        # 检查工作流是否已经完成
        if snapshot and snapshot.values and not snapshot.next:
            # 重跑判定：
            # 1) 有 user_input（典型多轮对话）
            # 2) 结构化工作流（未配置 user_input）- 每次调用都应执行一次，避免返回陈旧快照
            # 3) 非 user_input 字段发生变化（表单参数更新）
            should_rerun = bool(user_input)
            if user_input_field is None:
                should_rerun = True
            elif self._has_effective_input_changes(dict(snapshot.values), inputs or {}):
                should_rerun = True

            if should_rerun:
                logger.info(
                    f"工作流已完成，检测到新请求，重新执行: {self.id}, thread_id: {thread_id}"
                )

                # 以快照为基础，并注入本次输入
                state = dict(snapshot.values)
                state.update(inputs)
                state["thread_id"] = thread_id
                _apply_runtime_model(state)

                # 结构化工作流默认清空历史消息，避免上一轮上下文污染新一轮结构化计算
                if user_input_field is None:
                    state.pop("__messages__", None)

                # 记录执行前的 messages 数量
                existing_channel = get_output_channel()
                if existing_channel:
                    existing_channel._pre_run_msg_count = len(state.get("__messages__") or [])

                async with self._trace_context(tracer, thread_id, inputs, "start"):
                    try:
                        result = await _ainvoke_with_timeout(state)
                        result = self._check_interrupt_marker(result)
                        return result
                    except GraphInterrupt as e:
                        return await self._handle_interrupt(compiled_graph, config, e)

            # 工作流已完成且无新输入，返回最终状态
            logger.info(f"工作流已完成: {self.id}, thread_id: {thread_id}")
            result_state = self._make_serializable(dict(snapshot.values))
            result_state["__status__"] = "completed"
            return result_state
        
        if snapshot and snapshot.next and user_input is not None:
            # 恢复模式：使用 Command(resume=...)
            logger.info(f"恢复工作流: {self.id}, thread_id: {thread_id}")

            # 构造 resume 值：HumanNode 文本与按钮都通过 feedback_field 恢复。
            # 同步注入本次请求级运行参数，避免恢复中断时沿用旧 checkpoint 中的模型/权限。
            resume_value = user_input
            resume_update = {}
            if runtime_model_id:
                resume_update["__runtime_model_id__"] = runtime_model_id
            if request_context:
                resume_update["__tool_confirmation_required__"] = bool(request_context.tool_confirmation_required)
                resume_update["__tool_confirmation_level__"] = str(getattr(request_context, "tool_confirmation_level", "off") or "off")

            # 记录执行前的 messages 数量
            existing_channel = get_output_channel()
            if existing_channel:
                existing_channel._pre_run_msg_count = len(snapshot.values.get("__messages__") or [])

            async with self._trace_context(tracer, thread_id, inputs, "resume"):
                try:
                    command = Command(resume=resume_value, update=resume_update or None)
                    result = await _ainvoke_with_timeout(command)
                    # 检查新版 LangGraph 的中断标记
                    result = self._check_interrupt_marker(result)
                    # snapshot 兜底
                    if not result.get("__interrupted__"):
                        result = await self._detect_interrupt_from_snapshot(compiled_graph, config, result)
                    if not result.get("__interrupted__"):
                        logger.info(f"LangGraph 恢复执行完成: {self.id}")
                    return result
                except GraphInterrupt as e:
                    return await self._handle_interrupt(compiled_graph, config, e)
        
        # 新会话模式
        state = (inputs or {}).copy()
        state["thread_id"] = thread_id
        if request_context:
            state["__request_from_channel__"] = bool(request_context.from_channel)
            state["__disable_confirm_tool__"] = bool(request_context.disable_confirm_tool)
            state["__tool_confirmation_required__"] = bool(request_context.tool_confirmation_required)
            state["__tool_confirmation_level__"] = str(getattr(request_context, "tool_confirmation_level", "off") or "off")
            if request_context.user_id is not None:
                state["user_id"] = request_context.user_id
        _apply_runtime_model(state)
        
        # 注入 welcome 开场白（仅新对话）
        if self.welcome:
            msgs = state.get("__messages__") or []
            if not msgs:
                state["__messages__"] = [{"role": "assistant", "content": self.welcome}]
        
        # 记录执行前的 messages 数量
        existing_channel = get_output_channel()
        if existing_channel:
            existing_channel._pre_run_msg_count = len(state.get("__messages__") or [])
        
        async with self._trace_context(tracer, thread_id, inputs, "start"):
            try:
                result = await _ainvoke_with_timeout(state)
                # 检查新版 LangGraph 的中断标记（__interrupt__ 字段）
                result = self._check_interrupt_marker(result)
                # 如果 marker 检测没发现中断，用 snapshot 兜底
                if not result.get("__interrupted__"):
                    result = await self._detect_interrupt_from_snapshot(compiled_graph, config, result)
                if not result.get("__interrupted__"):
                    logger.info(f"LangGraph 执行完成: {self.id}")
                return result

            except GraphInterrupt as e:
                return await self._handle_interrupt(compiled_graph, config, e)

    async def _detect_interrupt_from_snapshot(self, compiled_graph, config: dict, result: dict) -> dict:
        """通过 snapshot 检测中断状态（兜底方案，兼容所有 LangGraph 版本）"""
        try:
            snapshot = await compiled_graph.aget_state(config)
            if not snapshot or not snapshot.next:
                return result
            # snapshot.next 非空说明图被挂起（中断）
            logger.info(f"通过 snapshot 检测到工作流中断: {self.id}")
            result["__interrupted__"] = True
            result["__status__"] = "waiting_for_input"
            # 从 snapshot.tasks 提取中断 payload
            if hasattr(snapshot, 'tasks') and snapshot.tasks:
                for task in snapshot.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        first = task.interrupts[0]
                        if hasattr(first, 'value') and isinstance(first.value, dict):
                            result["__interrupt_info__"] = first.value
                        break
        except Exception as ex:
            logger.debug(f"snapshot 中断检测失败: {ex}")
        return self._normalize_interrupt_state(result)

    def _check_interrupt_marker(self, result: dict) -> dict:
        """
        检查新版 LangGraph 的中断标记
        
        新版 LangGraph 不再抛出 GraphInterrupt 异常，
        而是在返回结果中添加 __interrupt__ 字段
        """
        if "__interrupt__" in result:
            interrupt_info = result.get("__interrupt__", [])
            logger.info(f"工作流中断，等待用户输入: {self.id}")
            
            # 标记中断状态
            result["__interrupted__"] = True
            result["__status__"] = "waiting_for_input"
            
            # 提取中断信息
            if interrupt_info and len(interrupt_info) > 0:
                first_interrupt = interrupt_info[0]
                if hasattr(first_interrupt, 'value'):
                    result["__interrupt_info__"] = first_interrupt.value
            # 移除内部字段，避免序列化问题
            del result["__interrupt__"]

        return self._normalize_interrupt_state(result)

    @staticmethod
    def _normalize_interrupt_state(result: dict) -> dict:
        """标准化中断返回字段，方便外层识别嵌套工作流中断。"""
        interrupt_info = result.get("__interrupt_info__")
        if not isinstance(interrupt_info, dict):
            return result

        subworkflow_info = interrupt_info.get("subworkflow")
        if isinstance(subworkflow_info, dict):
            result["__subworkflow_interrupt__"] = subworkflow_info

        return result

    @staticmethod
    def _build_human_resume_value(inputs: dict, user_input_field: Optional[str] = None):
        """从本次请求中提取 HumanNode 恢复值，保留按钮 value 的原始类型。"""
        if not inputs:
            return None
        if "__human_input__" in inputs:
            return {"__human_input__": inputs.get("__human_input__")}
        if user_input_field and user_input_field in inputs:
            return inputs.get(user_input_field)
        if "__user__" in inputs:
            return inputs.get("__user__")
        return None
    
    @asynccontextmanager
    async def _trace_context(self, tracer, thread_id: str, inputs: dict, mode: str):
        """Trace 上下文管理器"""
        if not tracer or not tracer.enabled:
            yield
            return
        
        # 检查是否已经在 trace 上下文中（由 TracedWorkflow 创建）
        from agentclaw.runtime.tracing.db_tracer import _current_trace
        if _current_trace.get() is not None:
            # 已经在 trace 中，跳过创建新的
            yield
            return
        
        async with tracer.trace(
            name=f"{self.id}:{mode}",
            workflow_id=self.id,
            thread_id=thread_id,
            input_data=inputs,
        ):
            yield
    
    async def _delete_thread_checkpoints(self, thread_id: str):
        """删除指定 thread 的所有 checkpoint 数据（用于清理取消/超时导致的残留挂起状态）"""
        try:
            from agentclaw.state.checkpointer import get_checkpointer
            checkpointer = get_checkpointer()
            if not checkpointer:
                return

            async_delete_thread = getattr(checkpointer, "adelete_thread", None)
            if async_delete_thread:
                result = async_delete_thread(thread_id)
                if inspect.isawaitable(result):
                    await result
                logger.info(f"已清理 thread {thread_id} 的所有 checkpoint 数据")
                return

            delete_thread = getattr(checkpointer, "delete_thread", None)
            if delete_thread:
                await asyncio.to_thread(delete_thread, thread_id)
                logger.info(f"已清理 thread {thread_id} 的所有 checkpoint 数据")
                return

            if hasattr(checkpointer, 'conn'):
                pool = checkpointer.conn
                connection = getattr(pool, "connection", None)
                if not connection:
                    await self._delete_thread_checkpoints_from_connection(pool, thread_id)
                else:
                    connection_context = connection()
                    if hasattr(connection_context, "__aenter__"):
                        async with connection_context as conn:
                            await self._delete_thread_checkpoints_from_connection(conn, thread_id)
                    else:
                        await asyncio.to_thread(self._delete_thread_checkpoints_from_sync_pool, pool, thread_id)
                logger.info(f"已清理 thread {thread_id} 的所有 checkpoint 数据")
        except Exception as e:
            logger.warning(f"清理 checkpoint 数据失败: {e}")

    async def _delete_thread_checkpoints_from_connection(self, conn, thread_id: str) -> None:
        """通过异步连接删除指定 thread 的 checkpoint 数据。"""
        for statement in (
            "DELETE FROM checkpoint_writes WHERE thread_id = %s",
            "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
            "DELETE FROM checkpoints WHERE thread_id = %s",
        ):
            result = conn.execute(statement, (thread_id,))
            if inspect.isawaitable(result):
                await result

    @staticmethod
    def _delete_thread_checkpoints_from_sync_pool(pool, thread_id: str) -> None:
        """通过同步连接池删除指定 thread 的 checkpoint 数据。"""
        with pool.connection() as conn:
            for statement in (
                "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
                "DELETE FROM checkpoints WHERE thread_id = %s",
            ):
                conn.execute(statement, (thread_id,))

    async def _handle_interrupt(self, compiled_graph, config: dict, e) -> dict:
        """处理 GraphInterrupt 异常"""
        logger.info(f"工作流中断，等待用户输入: {self.id}")
        
        # 获取当前状态快照
        snapshot = await compiled_graph.aget_state(config)
        result_state = self._make_serializable(dict(snapshot.values)) if snapshot and snapshot.values else {}
        
        result_state["__interrupted__"] = True
        result_state["__status__"] = "waiting_for_input"
        
        # 提取中断信息
        if e.args and len(e.args) > 0:
            interrupt_data = e.args[0]
            # e.args[0] 可能是 Interrupt 列表而非单个 Interrupt
            if isinstance(interrupt_data, (list, tuple)) and len(interrupt_data) > 0:
                interrupt_data = interrupt_data[0]
            if hasattr(interrupt_data, 'value') and isinstance(interrupt_data.value, dict):
                result_state["__interrupt_info__"] = interrupt_data.value

        # 如果上面没提取到，从 snapshot.tasks 中提取
        if "__interrupt_info__" not in result_state and snapshot:
            try:
                if hasattr(snapshot, 'tasks') and snapshot.tasks:
                    for task in snapshot.tasks:
                        if hasattr(task, 'interrupts') and task.interrupts:
                            first = task.interrupts[0]
                            if hasattr(first, 'value') and isinstance(first.value, dict):
                                result_state["__interrupt_info__"] = first.value
                            break
            except Exception:
                pass

        return self._normalize_interrupt_state(result_state)
    
    def _make_serializable(self, obj):
        """递归清理对象，确保可以 JSON 序列化"""
        from agentclaw.state.serializer import make_serializable
        return make_serializable(obj, warn=True)
    
    async def _execute_builtin(self, inputs, parent_context, thread_id, user_id, timeout, metadata, debug_queue=None) -> dict:
        """使用内置执行引擎（无持久化）"""
        import time as time_module
        
        # 如果有父上下文，继承它
        if parent_context:
            context = parent_context.copy()
            context.workflow_id = self.id
            context.workflow_name = self.name
        else:
            context = WorkflowContext(
                thread_id=thread_id,
                user_id=user_id,
                metadata=metadata or {},
            )
            context.workflow_id = self.id
            context.workflow_name = self.name
        
        timeout_val = self.timeout if timeout is None else timeout
        context.timeout = timeout_val if timeout_val and timeout_val > 0 else None
        context.user_input_field = self._user_input_field  # 设置用户输入字段名
        
        # 加载运行时工具配置（禁用的 skills/tools）
        try:
            from agentclaw.api.services.tool_config_service import get_tool_config_manager
            tcm = get_tool_config_manager()
            context.disabled_skills = tcm.get_disabled_skills(self.id)
            context.disabled_tools = tcm.get_disabled_tools(self.id)
        except Exception:
            pass
        
        self._ensure_components()
        context.prompt_manager = self._prompt_manager
        context.llm_manager = self._llm_manager
        context.skill_manager = self._skill_manager
        
        from agentclaw.node.toolkit import ToolKit
        from agentclaw.mcp.toolkit import MCPToolKit
        for comp in self._components:
            if isinstance(comp, (ToolKit, MCPToolKit)):
                context.toolkit = comp
                break
        
        # 检查是否有调试会话
        debugger = None
        from agentclaw.runtime.debugger import get_current_session, WorkflowDebugger, BreakpointType, DebugStopException
        debug_session = get_current_session()
        if debug_session and debug_session.workflow_id == self.id:
            debugger = WorkflowDebugger(self, debug_session)
            context.debug_mode = True  # 调试模式下禁用超时检查
            logger.info(f"使用调试模式执行工作流: {self.id}, session={debug_session.id}")
        else:
            logger.info(f"使用内置引擎执行工作流: {self.id}, thread_id: {context.thread_id}")
        
        # 获取或创建 OutputChannel
        from agentclaw.runtime.streaming.context import OutputChannel, _output_channel_var
        existing_channel = _output_channel_var.get()
        
        if existing_channel:
            # 复用已有的 channel（由 API 创建）
            channel = existing_channel
            # 如果有调试队列，设置到 channel
            if debug_queue is not None:
                channel.debug_queue = debug_queue
            channel_token = None
        else:
            # 创建新的 OutputChannel
            channel = OutputChannel(
                workflow_id=self.id,
                thread_id=thread_id or "",
                stream_mode=False,  # 非流式，收集所有输出
                debug_queue=debug_queue,  # 直接传入调试队列
            )
            channel_token = _output_channel_var.set(channel)
        
        state = (inputs or {}).copy()
        
        # 注入 welcome 开场白（仅新对话，内置引擎无持久化所以每次都是新对话）
        if self.welcome:
            msgs = state.get("__messages__") or []
            if not msgs:
                state["__messages__"] = [{"role": "assistant", "content": self.welcome}]
        
        # 设置 OutputChannel 的 state 引用（用于 save_to_context）
        channel.state = state
        
        # 使用显式指定的开始节点，否则使用第一个节点
        current_node = self._start_node if self._start_node else (self._node_order[0] if self._node_order else None)
        max_iterations = len(self._nodes) * 10
        iteration = 0
        
        while current_node and iteration < max_iterations:
            iteration += 1
            
            node = self._nodes.get(current_node)
            if node:
                logger.info(f"执行节点: {current_node}")
                
                # 更新调试会话的当前节点
                if debugger:
                    debugger.session.current_node = current_node
                
                # 记录节点执行前的输出数量（用于捕获新输出）
                outputs_before = len(channel.outputs)
                
                # 设置当前节点名（用于 output() 记录和 message 事件的 node_id）
                prev_node = channel._current_node
                channel._current_node = current_node
                
                # 获取节点类型
                node_type = type(node).__name__.lower().replace("node", "")
                
                # 推送 node_started 事件
                node_start_time = time_module.perf_counter()
                state_keys_before = set(state.keys())
                state_snapshot = {k: v for k, v in state.items()}
                node_inputs = {k: v for k, v in state.items() if not k.startswith("__")}
                node_title = getattr(node, 'description', None) or current_node
                await channel.push_node_started(current_node, node_type, inputs=node_inputs, title=node_title)

                try:
                    # 检查是否为 HumanNode（调试模式下作为固定断点）
                    is_human_node = isinstance(node, HumanNode)
                    
                    if debugger:
                        if is_human_node:
                            # HumanNode 在调试模式下自动作为固定断点
                            # 强制暂停，等待用户通过 set_state 设置输入
                            logger.info(f"HumanNode {current_node} 调试模式：自动暂停等待用户输入")
                            state = await debugger._pause(current_node, state, BreakpointType.BEFORE)
                            # 用户已通过 set_state 设置输入，跳过 HumanNode 的实际执行
                            # 因为 HumanNode 的本质就是等待用户输入，调试模式下已经通过 set_state 完成
                            logger.info(f"HumanNode {current_node} 调试模式：用户输入已设置，跳过节点执行")
                            # 更新当前状态
                            debugger.session.current_state = state.copy()
                            # 记录节点执行完成
                            debugger.session.history.append({
                                "action": "node_executed",
                                "node": current_node,
                                "type": "human",
                                "timestamp": __import__("datetime").datetime.now().isoformat(),
                            })
                            # 推送 node_finished 事件
                            elapsed_time = time_module.perf_counter() - node_start_time
                            await channel.push_node_finished(current_node, status="succeeded", elapsed_time=elapsed_time)
                        else:
                            # 非 HumanNode：检查断点
                            state = await debugger.check_breakpoint(current_node, state, BreakpointType.BEFORE)
                            # 执行节点
                            state = await node.execute(state, context)
                            
                            # 捕获节点执行期间的 output() 内容
                            outputs_after = len(channel.outputs)
                            if outputs_after > outputs_before:
                                # 有新的输出内容 - 合并所有输出为一条记录
                                new_outputs = channel.outputs[outputs_before:outputs_after]
                                # outputs 是字符串列表，直接拼接
                                combined_content = "".join(new_outputs)
                                if combined_content:
                                    debugger.session.history.append({
                                        "action": "node_output",
                                        "node": current_node,
                                        "content": combined_content,
                                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                                    })
                                    logger.debug(f"捕获节点输出: {current_node}, 内容长度: {len(combined_content)}")
                            
                            # 记录节点执行完成
                            debugger.session.history.append({
                                "action": "node_executed",
                                "node": current_node,
                                "type": type(node).__name__,
                                "timestamp": __import__("datetime").datetime.now().isoformat(),
                            })
                            # 更新当前状态
                            debugger.session.current_state = state.copy()
                            # 更新 OutputChannel 的 state 引用
                            channel.state = state
                            # 推送 node_finished 事件（只显示节点新增/变更的 key，过滤内部字段）
                            elapsed_time = time_module.perf_counter() - node_start_time
                            node_outputs = {k: v for k, v in state.items() if k not in _INTERNAL_HEAVY_KEYS and (k not in state_keys_before or state[k] is not state_snapshot.get(k))}
                            await channel.push_node_finished(current_node, status="succeeded", outputs=node_outputs, elapsed_time=elapsed_time)
                            # 节点执行后断点
                            state = await debugger.check_breakpoint(current_node, state, BreakpointType.AFTER)
                    else:
                        # 非调试模式：正常执行节点
                        state = await node.execute(state, context)
                        # 更新 OutputChannel 的 state 引用
                        channel.state = state
                        # 推送 node_finished 事件（只显示节点新增/变更的 key，过滤内部字段）
                        elapsed_time = time_module.perf_counter() - node_start_time
                        node_outputs = {k: v for k, v in state.items() if k not in _INTERNAL_HEAVY_KEYS and (k not in state_keys_before or state[k] is not state_snapshot.get(k))}
                        await channel.push_node_finished(current_node, status="succeeded", outputs=node_outputs, elapsed_time=elapsed_time)
                        
                except DebugStopException:
                    logger.info(f"调试停止: {self.id}")
                    state["__debug_stopped__"] = True
                    # 推送 node_finished 事件（停止）
                    elapsed_time = time_module.perf_counter() - node_start_time
                    await channel.push_node_finished(current_node, status="stopped", elapsed_time=elapsed_time)
                    # 恢复当前节点名
                    channel._current_node = prev_node
                    # 清理 OutputChannel
                    if channel_token is not None:
                        _output_channel_var.reset(channel_token)
                    return state
                except Exception as e:
                    # 推送 node_finished 事件（失败）
                    elapsed_time = time_module.perf_counter() - node_start_time
                    await channel.push_node_finished(current_node, status="failed", elapsed_time=elapsed_time, error=str(e))
                    # 恢复当前节点名
                    channel._current_node = prev_node
                    raise
                finally:
                    # 恢复当前节点名
                    channel._current_node = prev_node
                
                # 非调试模式下，检查节点的 interrupt 属性
                # 调试模式下，HumanNode 已经通过 _pause 处理了用户输入，不需要中断
                if not debugger and getattr(node, 'interrupt', False):
                    state["__interrupted__"] = True
                    state["__interrupt_node__"] = current_node
                    state["__status__"] = "waiting_for_input"
                    if isinstance(node, HumanNode):
                        state["__interrupt_info__"] = node.build_interrupt_payload(state)
                    return state
                if not debugger and state.get("__interrupted__"):
                    return state

            if current_node in self._conditional_edges:
                edge_config = self._conditional_edges[current_node]
                condition_result = edge_config["condition"](state)
                
                if edge_config.get("direct_mode"):
                    next_node = condition_result
                else:
                    next_node = edge_config["targets"].get(condition_result)
                
                if isinstance(next_node, list):
                    parallel_targets = [node_id for node_id in next_node if node_id not in ("__end__", "END", None)]
                    if not parallel_targets:
                        break
                    parallel_results = await self._execute_parallel_nodes(
                        parallel_targets, state, context, channel, debugger, time_module
                    )
                    for i, result in enumerate(parallel_results):
                        new_keys = {k: v for k, v in result.items() if k.startswith("__") and k not in state}
                        if new_keys:
                            logger.info(f"并行节点 {parallel_targets[i]} 新增 state keys: {list(new_keys.keys())}")
                        state = self._merge_parallel_result(state, result, parallel_targets[i])
                    channel.state = state

                    common_next = self._find_common_successor(parallel_targets)
                    if common_next:
                        current_node = common_next
                        continue
                    break

                if next_node in ("__end__", "END", None):
                    break
                current_node = next_node
            elif current_node in self._edges:
                next_nodes = self._edges[current_node]
                if len(next_nodes) == 1:
                    # 单目标：顺序执行
                    current_node = next_nodes[0]
                elif len(next_nodes) > 1:
                    # 多目标：并行执行
                    parallel_results = await self._execute_parallel_nodes(
                        next_nodes, state, context, channel, debugger, time_module
                    )
                    # 合并并行执行结果到 state
                    for i, result in enumerate(parallel_results):
                        # 提取并行节点注入的 __ 前缀 key
                        new_keys = {k: v for k, v in result.items() if k.startswith("__") and k not in state}
                        if new_keys:
                            logger.info(f"并行节点 {next_nodes[i]} 新增 state keys: {list(new_keys.keys())}")
                        state = self._merge_parallel_result(state, result, next_nodes[i])
                    logger.info(f"并行合并完成，state 中 filter keys: "
                                f"__filtered_tools__={'__filtered_tools__' in state}, "
                                f"__filtered_skill_names__={'__filtered_skill_names__' in state}")
                    channel.state = state
                    
                    # 找到所有并行节点的共同后继节点
                    # 如果所有并行节点都指向同一个节点，则继续执行该节点
                    common_next = self._find_common_successor(next_nodes)
                    if common_next:
                        current_node = common_next
                    else:
                        # 没有共同后继，结束
                        break
                else:
                    break
            else:
                break
        
        if iteration >= max_iterations:
            logger.warning(f"工作流 {self.id} 达到最大迭代次数")
        
        # 清理 OutputChannel（仅当我们创建了新的 channel 时）
        if channel_token is not None:
            _output_channel_var.reset(channel_token)
        
        # 标记调试完成
        if debugger:
            from agentclaw.runtime.debugger import DebugStatus
            debugger.session.status = DebugStatus.COMPLETED
            debugger.session.current_node = None  # 清除当前节点
            debugger.session.current_state = state  # 更新最终状态
        
        logger.info(f"工作流执行完成: {self.id}, 耗时: {context.elapsed_seconds():.2f}s")
        return state
    
    async def _execute_parallel_nodes(
        self,
        node_ids: List[str],
        state: dict, 
        context: "WorkflowContext",
        channel,
        debugger,
        time_module
    ) -> List[dict]:
        """并行执行多个节点"""
        from uuid import uuid4
        from agentclaw.runtime.debugger import BreakpointType, DebugStopException

        pg_id = f"pg-{uuid4().hex[:8]}"

        async def execute_single_node(node_id: str) -> dict:
            """执行单个节点并返回结果"""
            node = self._nodes.get(node_id)
            if not node:
                return {}

            # 创建状态副本
            node_state = state.copy()

            logger.info(f"并行执行节点: {node_id}")

            # 设置当前节点名
            prev_node = channel._current_node
            channel._current_node = node_id

            # 获取节点类型
            node_type = type(node).__name__.lower().replace("node", "")

            # 推送 node_started 事件
            node_start_time = time_module.perf_counter()
            state_keys_before = set(node_state.keys())
            node_inputs = {k: v for k, v in node_state.items() if not k.startswith("__")}
            node_title = getattr(node, 'description', None) or node_id
            await channel.push_node_started(node_id, node_type, inputs=node_inputs, parallel_group_id=pg_id, title=node_title)

            try:
                if debugger:
                    # 调试模式
                    node_state = await debugger.check_breakpoint(node_id, node_state, BreakpointType.BEFORE)
                    node_state = await node.execute(node_state, context)
                    debugger.session.history.append({
                        "action": "node_executed",
                        "node": node_id,
                        "type": type(node).__name__,
                        "timestamp": __import__("datetime").datetime.now().isoformat(),
                    })
                    node_state = await debugger.check_breakpoint(node_id, node_state, BreakpointType.AFTER)
                else:
                    # 正常执行
                    node_state = await node.execute(node_state, context)

                # 推送 node_finished 事件（只显示节点新增/变更的 key，过滤内部字段）
                elapsed_time = time_module.perf_counter() - node_start_time
                node_outputs = {k: v for k, v in node_state.items() if k not in _INTERNAL_HEAVY_KEYS and (k not in state_keys_before or node_state[k] is not state.get(k))}
                await channel.push_node_finished(node_id, status="succeeded", outputs=node_outputs, elapsed_time=elapsed_time, parallel_group_id=pg_id)

                return node_state

            except DebugStopException:
                elapsed_time = time_module.perf_counter() - node_start_time
                await channel.push_node_finished(node_id, status="stopped", elapsed_time=elapsed_time, parallel_group_id=pg_id)
                raise
            except Exception as e:
                elapsed_time = time_module.perf_counter() - node_start_time
                await channel.push_node_finished(node_id, status="failed", elapsed_time=elapsed_time, error=str(e), parallel_group_id=pg_id)
                raise
            finally:
                channel._current_node = prev_node
        
        # 并行执行所有节点
        tasks = [execute_single_node(node_id) for node_id in node_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"并行节点 {node_ids[i]} 执行失败: {result}")
                # 可以选择抛出异常或继续
                raise result
            else:
                successful_results.append(result)

        return successful_results

    def _merge_parallel_result(self, state: dict, result: dict, node_id: str) -> dict:
        """Merge one parallel branch result back into built-in workflow state."""
        node = self._nodes.get(node_id)
        strategies = {}
        if node and hasattr(node, "get_state_merge_strategies"):
            try:
                strategies = node.get_state_merge_strategies()  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f"读取节点 {node_id} 状态合并策略失败: {e}")

        if not strategies:
            state.update(result)
            return state

        from agentclaw.graph.state_path import merge_path

        for key, value in result.items():
            strategy = strategies.get(key)
            if strategy in ("deep_merge", "shallow_merge", "append"):
                merge_path(state, key, value, strategy=strategy)
            else:
                state[key] = value
        return state

    def _find_common_successor(self, node_ids: List[str]) -> Optional[str]:
        """
        查找多个节点的共同后继节点
        
        如果所有节点都指向同一个目标节点，返回该节点
        否则返回 None
        """
        successors = set()
        for node_id in node_ids:
            if node_id in self._edges:
                next_nodes = self._edges[node_id]
                if len(next_nodes) == 1:
                    successors.add(next_nodes[0])
                else:
                    # 如果某个节点有多个后继，无法确定共同后继
                    return None
            elif node_id in self._conditional_edges:
                # 条件边不参与共同后继计算
                return None
        
        # 如果所有节点都指向同一个目标
        if len(successors) == 1:
            successor = successors.pop()
            if successor not in ("__end__", "END"):
                return successor
        
        return None
    
    async def resume(self, thread_id: str, resume_value: Any = None, *, config: Optional[dict] = None) -> dict:
        """恢复暂停的工作流"""
        if not self._compiled_graph:
            raise ValueError("工作流未编译，无法使用 resume")
        
        from langgraph.types import Command
        
        run_config = config or {}
        if "configurable" not in run_config:
            run_config["configurable"] = {}
        run_config["configurable"]["thread_id"] = thread_id
        
        try:
            result = await self._compiled_graph.ainvoke(Command(resume=resume_value), config=run_config)
            return result
        except Exception as e:
            if "GraphInterrupt" in str(type(e)):
                return {"__status__": "waiting_for_input", "__error__": str(e)}
            raise
    
    def set_compiled_graph(self, compiled_graph) -> None:
        """设置编译后的 LangGraph 图"""
        self._compiled_graph = compiled_graph

    async def save_partial_response(self, thread_id: str, partial_content: str) -> None:
        """中断时保存部分回复到 checkpoint，使下次请求能看到上下文"""
        if not self._checkpointer or not thread_id or not partial_content:
            return
        try:
            compiled = self._compile_to_langgraph()
            if not compiled:
                return
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = await compiled.aget_state(config)
            if snapshot and snapshot.values:
                messages = list(snapshot.values.get("__messages__") or [])
                messages.append({"role": "assistant", "content": partial_content + "\n\n[已停止]"})
                await compiled.aupdate_state(config, {"__messages__": messages})
                logger.info(f"已保存中断时的部分回复到 checkpoint (thread_id={thread_id}, len={len(partial_content)})")
        except Exception as e:
            logger.warning(f"保存部分回复到 checkpoint 失败: {e}")
    
    def publish(self, stream: bool = True, endpoints: Optional[List[dict]] = None,
                traffic_split: Optional[Dict[str, str]] = None, require_auth: bool = True) -> None:
        """发布工作流为 API"""
        from agentclaw.api.registry import WorkflowRegistry
        
        self._default_stream = stream
        
        # 确保组件初始化，这样提示词会被注册到 PromptManager
        self._ensure_components()
        
        self._validate()
        WorkflowRegistry.register(self, stream, endpoints, traffic_split, require_auth)
        
        auth_status = "🔒" if require_auth else "🔓"
        logger.info(f"工作流已发布: {self.id}, stream={stream} {auth_status}")
    
    def _validate(self) -> None:
        """验证工作流配置"""
        if self._prompt_manager:
            for node in self._nodes.values():
                if isinstance(node, LLMNode) and getattr(node, 'prompt_key', None) and getattr(node, 'required_prompt', False):
                    if not self._prompt_manager.has_prompt(node.prompt_key):
                        raise ConfigError(f"节点 '{node.id}' 的 prompt_key '{node.prompt_key}' 不存在")
        
        if not self._node_order:
            raise ConfigError("工作流没有任何节点")
    
    def visualize(self, format: str = "text") -> str:
        """生成工作流可视化图"""
        if format == "mermaid":
            return self._visualize_mermaid()
        return self._visualize_text()
    
    def _visualize_text(self) -> str:
        lines = [f"Workflow: {self.name} (v{self.version})", ""]
        for i, node_id in enumerate(self._node_order):
            node = self._nodes[node_id]
            lines.append(f"  [{i+1}] {node_id} ({type(node).__name__})")
            if node_id in self._edges:
                targets = self._edges[node_id]
                if len(targets) == 1:
                    lines.append(f"      └─> {targets[0]}")
                else:
                    # 并行边
                    lines.append(f"      └─> [{', '.join(targets)}] (并行)")
            elif node_id in self._conditional_edges:
                targets = self._conditional_edges[node_id]["targets"]
                for cond, target in targets.items():
                    lines.append(f"      └─({cond})─> {target}")
        return "\n".join(lines)
    
    def _visualize_mermaid(self) -> str:
        lines = ["```mermaid", "graph TD",
                 f"    START([Start]) --> {self._node_order[0] if self._node_order else 'END'}"]
        
        for node_id in self._node_order:
            node = self._nodes[node_id]
            if getattr(node, 'interrupt', False):
                lines.append(f'    {node_id}[["{node_id}"]]')
            else:
                lines.append(f'    {node_id}["{node_id}"]')
            
            if node_id in self._edges:
                targets = self._edges[node_id]
                for target in targets:
                    lines.append(f"    {node_id} --> {'END([End])' if target in ('__end__', 'END') else target}")
            elif node_id in self._conditional_edges:
                targets = self._conditional_edges[node_id]["targets"]
                for cond, target in targets.items():
                    t = "END([End])" if target in ("__end__", "END") else target
                    lines.append(f"    {node_id} -->|{cond}| {t}")
            else:
                lines.append(f"    {node_id} --> END([End])")
        
        lines.append("```")
        return "\n".join(lines)
    
    def _extract_node_schema(self, handler) -> tuple:
        """
        从函数签名和文档字符串中提取输入/输出 schema
        
        Returns:
            (input_schema, output_schema) 元组
        """
        import inspect
        import ast
        
        input_schema = {}
        output_schema = {}
        
        try:
            # 从文档字符串提取信息
            doc = handler.__doc__
            if doc:
                input_schema["description"] = doc.strip().split('\n')[0]
            
            # 从函数源码分析返回值
            source = inspect.getsource(handler)
            lines = source.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('def ') or line.strip().startswith('async def '):
                    lines = lines[i:]
                    break
            if lines:
                indent = len(lines[0]) - len(lines[0].lstrip())
                lines = [line[indent:] if len(line) > indent else line for line in lines]
            source = '\n'.join(lines)
            
            tree = ast.parse(source)
            
            # 分析 return 语句中的字典键
            output_fields = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Return) and node.value:
                    if isinstance(node.value, ast.Dict):
                        for key in node.value.keys:
                            field_name = None
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                field_name = key.value
                            elif isinstance(key, ast.Str):
                                field_name = key.s
                            if field_name:
                                output_fields.append(field_name)
            
            if output_fields:
                output_schema["fields"] = output_fields
            
            # 分析 state.get() 调用来推断输入字段
            input_fields = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # 检查 state.get("xxx") 模式
                    if (isinstance(node.func, ast.Attribute) and 
                        node.func.attr == 'get' and
                        isinstance(node.func.value, ast.Name) and
                        node.func.value.id == 'state' and
                        node.args):
                        arg = node.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            input_fields.append(arg.value)
                        elif isinstance(arg, ast.Str):
                            input_fields.append(arg.s)
            
            if input_fields:
                input_schema["fields"] = list(set(input_fields))  # 去重
                
        except Exception as e:
            logger.debug(f"提取节点 schema 失败: {e}")
        
        return input_schema or None, output_schema or None
    
    def get_structure(self) -> dict:
        """
        导出工作流结构（用于可视化）
        
        Returns:
            工作流结构字典，包含：
            - id: 工作流 ID
            - name: 工作流名称
            - version: 版本号
            - description: 描述
            - nodes: 节点列表（包含输入/输出 schema）
            - edges: 边列表
            - node_order: 节点执行顺序
            - input_schema: 工作流输入 schema
        """
        nodes = []
        # 收集隐藏的内部节点（如 __*_llm_router__）
        hidden_nodes = {name for name in self._nodes if name.startswith("__") and name.endswith("__")}

        for name, node in self._nodes.items():
            if name in hidden_nodes:
                continue
            node_info = {
                "id": name,
                "name": name,
                "type": getattr(node, "node_type", node.__class__.__name__.lower()),
            }
            
            # LLM 节点额外信息
            if hasattr(node, "model_id") and node.model_id:
                node_info["model_id"] = node.model_id
            
            # 检查是否有提示词
            if hasattr(node, "system_prompt") and node.system_prompt:
                node_info["has_prompt"] = True
            elif hasattr(node, "prompt") and node.prompt:
                node_info["has_prompt"] = True
            else:
                node_info["has_prompt"] = False
            
            # 中断节点标记
            if hasattr(node, "interrupt") and node.interrupt:
                node_info["interrupt"] = True
            
            # 输出键
            if hasattr(node, "output_key") and node.output_key:
                node_info["output_key"] = node.output_key
            
            # HumanNode 特殊信息
            if hasattr(node, "feedback_field"):
                node_info["feedback_field"] = node.feedback_field
                node_info["input_hint"] = f"请输入 '{node.feedback_field}' 字段的值"
            if hasattr(node, "approval_mode") and node.approval_mode:
                node_info["approval_mode"] = True
            
            # 尝试从 FunctionNode 的 handler 获取输入/输出信息
            if hasattr(node, "handler") and node.handler:
                node_info["input_schema"], node_info["output_schema"] = self._extract_node_schema(node.handler)
            
            nodes.append(node_info)
        
        edges = []

        # __start__ 边（来自 _start_node）
        if self._start_node:
            edges.append({
                "source": "__start__",
                "target": self._start_node,
                "type": "normal",
            })

        # 普通边（支持一对多），跳过涉及隐藏节点的边
        for from_node, to_nodes in self._edges.items():
            for to_node in to_nodes:
                if from_node in hidden_nodes or to_node in hidden_nodes:
                    continue
                edges.append({
                    "source": from_node,
                    "target": to_node,
                    "type": "normal" if len(to_nodes) == 1 else "parallel",
                })

        # 条件边：隐藏节点的条件边重映射到其上游节点
        for from_node, config in self._conditional_edges.items():
            targets = config.get("targets", {})

            # 如果条件源是隐藏节点，找到其上游节点作为可视化源
            visual_source = from_node
            if from_node in hidden_nodes:
                for fn, tn_list in self._edges.items():
                    if from_node in tn_list and fn not in hidden_nodes:
                        visual_source = fn
                        break

            if targets:
                for condition, target in targets.items():
                    if target in hidden_nodes:
                        continue
                    edges.append({
                        "source": visual_source,
                        "target": target,
                        "type": "conditional",
                        "condition": condition,
                    })
            else:
                # direct_mode: 条件函数直接返回目标节点名
                # 推断可能的目标节点（用于可视化）
                nodes_with_incoming = set()
                # _start_node 有隐式入边
                if self._start_node:
                    nodes_with_incoming.add(self._start_node)
                for _fn, _tn_list in self._edges.items():
                    for _tn in _tn_list:
                        if _tn not in ("__end__", "END", "__start__"):
                            nodes_with_incoming.add(_tn)
                for _fn, _cfg in self._conditional_edges.items():
                    _tgts = _cfg.get("targets")
                    if _tgts:
                        for _t in _tgts.values():
                            if _t not in ("__end__", "END"):
                                nodes_with_incoming.add(_t)

                # 没有入边且不是条件源本身的节点，视为条件边的可能目标
                possible_targets = [
                    nid for nid in self._nodes
                    if nid != from_node and nid not in nodes_with_incoming and nid not in hidden_nodes
                ]
                if possible_targets:
                    for target in possible_targets:
                        edges.append({
                            "source": visual_source,
                            "target": target,
                            "type": "conditional",
                        })
                else:
                    edges.append({
                        "source": visual_source,
                        "target": "__dynamic__",
                        "type": "conditional",
                        "condition": "dynamic",
                    })
        
        is_builtin_workflow = self.id == "__builtin__" or bool(getattr(self, "is_builtin", False))
        chat_audio = self._normalize_chat_audio(getattr(self, "chat_audio", None))
        if is_builtin_workflow and not getattr(self, "_chat_audio_explicit", False):
            chat_audio = dict(BUILTIN_CHAT_AUDIO_CONFIG)
        result = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "chat_audio": chat_audio,
            "public_share_enabled": False if is_builtin_workflow else bool(getattr(self, "public_share_enabled", False)),
            "public_share_token": "" if is_builtin_workflow else (getattr(self, "public_share_token", "") or ""),
            "publish_to_square": False if is_builtin_workflow else bool(getattr(self, "publish_to_square", False)),
            "api_published": False if is_builtin_workflow else getattr(self, "api_published", True) is not False,
            "safe_guard_apply_api": bool(getattr(self, "safe_guard_apply_api", False)),
            "safe_guard_apply_public": getattr(self, "safe_guard_apply_public", True) is not False,
            "rate_limit": getattr(self, "rate_limit", "") or "",
            "public_conversation_limit": getattr(self, "public_conversation_limit", 20) or 20,
            "public_message_limit": getattr(self, "public_message_limit", 200) or 200,
            "inject_as_agentic_capability": bool(getattr(self, "inject_as_agentic_capability", True)),
            "workflow_api_key_set": bool(getattr(self, "workflow_api_key", None)),
            "nodes": nodes,
            "edges": edges,
            "node_order": [n for n in self._node_order if n not in hidden_nodes],
            "input_schema": self.get_input_schema(),  # 工作流输入 schema (JSON Schema 格式)
        }

        # 添加 inputs 配置（用于前端表单生成）
        if self._input_schema:
            result["inputs_config"] = self._input_schema.to_dict()
            result["form_config"] = self._input_schema.to_form_config()

        # 添加用户输入字段名
        result["user_input_field"] = self._user_input_field

        # 添加前端开场白
        result["welcome"] = self.welcome

        # 添加是否为内置智能体标识
        result["is_builtin"] = is_builtin_workflow
        result["agent_square_app_id"] = getattr(self, "agent_square_app_id", "") or ""
        result["recommended_input"] = getattr(self, "recommended_input", "") or ""

        return result
