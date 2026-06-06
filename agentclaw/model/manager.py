"""
LLMManager - LLM 调用管理组件

支持：
- 多模型配置（从 models.json 加载）
- 按 id 选择模型
- 顺序自动降级（失败后切换下一个）
- 流式/非流式调用
- 节点级模型指定

配置文件 models.json:
{
    "default": "qwen3-next",
    "models": [
        {"id": "qwen3-next", "model": "...", "api_key": "...", "base_url": "..."},
        {"id": "qwen3-32b", "model": "...", ...},
    ]
}

使用方式:
    # 工作流级别指定默认模型
    workflow.use(LLMManager(default="qwen3-next"))
    
    # 节点级别指定模型
    workflow.add_node(Node(id="视觉分析", model_id="qwen3-vl", ...))
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Literal, Union
import asyncio
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib

from agentclaw.base import BaseComponent
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.workflow import Workflow

logger = get_logger(__name__)


_LLM_DUMP_SECRET_KEYS = (
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_key",
)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _redact_llm_failure_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(secret_key in key_text for secret_key in _LLM_DUMP_SECRET_KEYS):
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact_llm_failure_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_llm_failure_payload(item) for item in value]
    return value


def _maybe_dump_llm_failure_payload(
    create_kwargs: dict[str, Any],
    *,
    model_id: str,
    channel: str,
) -> Optional[str]:
    """Optionally dump a redacted failed LLM request payload for local debugging."""
    if not _truthy_env("AGENTCLAW_DUMP_LLM_FAILURE_PAYLOAD"):
        return None
    import time

    dump_dir = Path(os.getenv("AGENTCLAW_LLM_FAILURE_DUMP_DIR", "/tmp")).expanduser()
    dump_dir.mkdir(parents=True, exist_ok=True)
    safe_model = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(model_id or "model"))
    dump_path = dump_dir / f"llm_fail_{safe_model}_{int(time.time())}.json"
    payload = {
        "model_id": model_id,
        "channel": channel,
        "request": _redact_llm_failure_payload(create_kwargs),
    }
    fd = os.open(dump_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
    except Exception:
        try:
            dump_path.unlink(missing_ok=True)
        finally:
            raise
    return str(dump_path)


_PLACEHOLDER_API_KEYS = {
    "your-key",
    "your-api-key",
    "your-api-key-here",
    "your-openai-api-key",
    "your-anthropic-api-key",
    "your-deepseek-api-key",
    "your-azure-openai-api-key",
    "sk-your-api-key",
    "sk-your-openai-api-key",
    "sk-your-anthropic-api-key",
    "sk-your-azure-openai-api-key",
    "sk-your-workflow-key",
    "<your-api-key>",
}


def _strip_secret_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _clean_api_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = _strip_secret_quotes(str(value))
    if not value:
        return None
    if value.lower() in _PLACEHOLDER_API_KEYS:
        return None
    return value


def _resolve_env_reference(value: Optional[str]) -> Optional[str]:
    value = _clean_api_key(value)
    if not value:
        return None
    if value.startswith("${") and value.endswith("}"):
        return _clean_api_key(os.getenv(value[2:-1]))
    if value.startswith("$") and len(value) > 1:
        return _clean_api_key(os.getenv(value[1:]))
    return value


class _MissingChatCompletions:
    def __init__(self, message: str):
        self._message = message

    async def create(self, *args, **kwargs):
        raise RuntimeError(self._message)


class _MissingChatClient:
    def __init__(self, message: str):
        self.completions = _MissingChatCompletions(message)


class _MissingLLMClient:
    def __init__(self, message: str):
        self.chat = _MissingChatClient(message)


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class LLMResponse:
    """LLM 响应（支持工具调用）"""
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    reasoning: Optional[str] = None


@dataclass
class LLMConfig:
    """LLM 配置"""
    id: str = "default"  # 模型 ID
    channel: str = "openai"  # 渠道: openai / anthropic / codex
    provider: Literal["openai", "azure", "anthropic", "custom"] = "openai"
    model: str = "gpt-4"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_type: str = "chat"  # chat / embedding / rerank
    supports_vision: bool = False

    # Azure 特有
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    api_version: Optional[str] = None

    # 调用配置
    temperature: float = 0.1
    max_tokens: int = 8192
    timeout: int = 240

    # 自定义请求参数（用于适配不同模型的特殊需求，如 reasoning）
    # 这些参数会直接传递给 API 调用，避免为每个模型硬编码
    extra_headers: Optional[Dict[str, str]] = None  # 额外的 HTTP headers
    extra_body: Optional[Dict[str, Any]] = None     # 额外的请求 body 参数

    # 流式 usage 统计：部分代理/模型不支持 stream_options，设为 False 可跳过
    stream_usage: bool = True

    # 自定义提供商
    custom_client: Optional[Any] = None

    # 渠道 → provider 映射
    _CHANNEL_PROVIDER_MAP: Dict[str, str] = field(default_factory=dict, repr=False, init=False)

    @classmethod
    def from_dict(cls, data: dict) -> "LLMConfig":
        """从字典创建配置"""
        channel = data.get("channel", "openai")
        # 根据 channel 推导 provider
        # 当设置了 base_url（代理模式）时统一使用 openai provider
        has_base_url = bool(data.get("base_url"))
        if has_base_url:
            provider = "openai"
        else:
            provider = {
                "openai": "openai",
                "anthropic": "anthropic",
                "codex": "openai",
                "azure": "azure",
            }.get(channel, "openai")
        # 非 openai 渠道默认不发送 stream_options（多数代理/模型不支持）
        default_stream_usage = channel == "openai"
        api_key = _resolve_env_reference(data.get("api_key"))
        raw_model_type = str(data.get("type", data.get("model_type", "chat")) or "chat").strip().lower()
        legacy_vision_type = raw_model_type == "vision"
        model_type = "chat" if legacy_vision_type else raw_model_type
        supports_vision = bool(data.get("supports_vision") or legacy_vision_type)
        extra_body = data.get("extra_body")
        if extra_body is None:
            extra_body = {
                key: data[key]
                for key in (
                    "audio_format",
                    "audio_type",
                    "default_voice",
                    "file_upload_limit_mb",
                    "supported_file_extensions",
                    "voice",
                    "voices",
                    "word_limit",
                )
                if key in data
            } or None
        return cls(
            id=data.get("id", "default"),
            channel=channel,
            provider=provider,
            model=data.get("model", "gpt-4"),
            api_key=api_key,
            base_url=data.get("base_url"),
            model_type=model_type,
            supports_vision=supports_vision,
            temperature=data.get("temperature", 0.1),
            max_tokens=data.get("max_tokens", 8192),
            timeout=data.get("timeout", 240),
            extra_headers=data.get("extra_headers"),
            extra_body=extra_body,
            stream_usage=data.get("stream_usage", default_stream_usage),
        )
    
    @classmethod
    def from_env(cls, prefix: str = "", fallback: bool = False) -> "LLMConfig":
        """从环境变量加载配置（兼容旧方式）"""
        if fallback:
            return cls(
                id="fallback",
                provider="openai",
                api_key=_clean_api_key(os.getenv("FALLBACK_API_KEY")) or _clean_api_key(os.getenv(f"{prefix}API_KEY")),
                base_url=os.getenv("FALLBACK_BASE_URL") or os.getenv(f"{prefix}BASE_URL"),
                model=os.getenv("FALLBACK_MODEL_NAME", "gpt-3.5-turbo"),
            )
        
        return cls(
            id="primary",
            provider="openai",
            api_key=_clean_api_key(os.getenv(f"{prefix}API_KEY")),
            base_url=os.getenv(f"{prefix}BASE_URL"),
            model=os.getenv(f"{prefix}CHAT_MODEL_NAME", "gpt-4"),
        )


@dataclass
class FallbackState:
    """降级状态"""
    is_fallback: bool = False
    fallback_reason: Optional[str] = None
    fallback_until: Optional[datetime] = None
    failure_count: int = 0


@dataclass
class UsageStats:
    """调用统计（Token Usage + Latency）"""
    model_id: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: float = 0.0  # 耗时（毫秒）
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def cache_ratio(self) -> float:
        if self.prompt_tokens <= 0:
            return 0.0
        return self.cached_tokens / self.prompt_tokens

    @property
    def cost_estimate(self) -> float:
        """估算成本（基于常见定价，仅供参考）"""
        # 简化估算：$0.01 / 1K tokens
        return self.total_tokens * 0.00001
    
    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_ratio": self.cache_ratio,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


class LLMManager(BaseComponent):
    """
    LLM 调用管理器
    
    支持多模型配置、按 ID 选择、自动降级
    
    Example:
        # 自动从 models.json 加载
        workflow.use(LLMManager())
        
        # 指定默认模型
        workflow.use(LLMManager(default="qwen3-32b"))
        
        # 节点级别指定模型
        workflow.add_node(Node(id="视觉分析", model_id="qwen3-vl"))
    """
    
    def __init__(
        self,
        default: Optional[str] = None,  # 默认模型 ID
        fallback: Optional[str] = None,  # 降级模型 ID（不指定则按顺序）
        fast: Optional[str] = None,  # 快速模型 ID（用于小任务）
        config_path: str = "models.json",  # 配置文件路径
        # 降级配置
        auto_fallback: bool = True,
        fallback_threshold: int = 3,
        fallback_duration: int = 300,
        # Redis（用于分布式状态）
        redis_client: Optional[Any] = None,
    ):
        # 实例级缓存
        self._models_config: Optional[dict] = None
        self._models_cache: Dict[str, LLMConfig] = {}
        self._models_config_path = config_path
        self._default_override = default
        self._fallback_override = fallback
        self._fast_override = fast

        # 加载配置
        self._load_models_config(config_path)

        # 确定默认模型、降级模型、快速模型和视觉模型
        self.default_id = default or self._models_config.get("default")
        self.fallback_id = fallback or self._models_config.get("fallback")
        self.fast_id = fast or self._models_config.get("fast")
        self.vision_id: Optional[str] = self._models_config.get("vision")
        self.speech2text_id: Optional[str] = self._models_config.get("speech2text")
        self.tts_id: Optional[str] = self._models_config.get("tts")
        self.tts_voice: Optional[str] = self._models_config.get("tts_voice")
        self.safe_guard_id: Optional[str] = self._models_config.get("safe_guard")
        self.safe_guard_rules: str = str(self._models_config.get("safe_guard_rules") or "")
        
        # 模型列表（按顺序，用于自动降级）
        self.model_ids = [m["id"] for m in self._models_config.get("models", [])]
        
        self.auto_fallback = auto_fallback
        self.fallback_threshold = fallback_threshold
        self.fallback_duration = fallback_duration
        self.redis_client = redis_client
        
        # 内部状态
        self._workflow_id: Optional[str] = None
        self._fallback_state = FallbackState()
        self._clients: Dict[str, Any] = {}
        self._current_model_id: Optional[str] = None
        
        # 使用统计
        self._usage_history: List[UsageStats] = []
        self._total_tokens: int = 0
        self._total_latency_ms: float = 0.0
        
        channels = {m["id"]: m.get("channel", "openai") for m in self._models_config.get("models", [])}
        logger.info(f"LLMManager 初始化: default={self.default_id}, fallback={self.fallback_id}, fast={self.fast_id}, vision={self.vision_id}, safe_guard={self.safe_guard_id}, models={self.model_ids}, channels={channels}")
    
    def _load_models_config(self, config_path: str) -> None:
        """加载 models.json 配置"""
        if self._models_config is not None:
            return
        
        path = Path(config_path)
        if not path.exists():
            # 尝试在项目根目录查找
            for parent in [Path.cwd(), Path(__file__).parent.parent.parent]:
                candidate = parent / config_path
                if candidate.exists():
                    path = candidate
                    break
        
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._models_config = self._normalize_models_config(json.load(f), path)
                
            # 缓存所有模型配置
            for model_data in self._models_config.get("models", []):
                config = LLMConfig.from_dict(model_data)
                self._models_cache[config.id] = config
                
            logger.info(f"从 {path} 加载了 {len(self._models_cache)} 个模型配置")
        else:
            # 回退到环境变量
            logger.warning(f"未找到 {config_path}，使用环境变量配置")
            self._models_config = {"default": "primary", "models": []}
            self._models_cache["primary"] = LLMConfig.from_env()

    def reload_models_config(self, config_path: Optional[str] = None) -> None:
        """Reload models.json without recreating the manager instance."""
        target_path = config_path or self._models_config_path
        self._models_config_path = target_path
        self._models_config = None
        self._models_cache = {}
        self._clients = {}
        self._load_models_config(target_path)
        self.default_id = self._default_override or self._models_config.get("default")
        self.fallback_id = self._fallback_override or self._models_config.get("fallback")
        self.fast_id = self._fast_override or self._models_config.get("fast")
        self.vision_id = self._models_config.get("vision")
        self.speech2text_id = self._models_config.get("speech2text")
        self.tts_id = self._models_config.get("tts")
        self.tts_voice = self._models_config.get("tts_voice")
        self.safe_guard_id = self._models_config.get("safe_guard")
        self.safe_guard_rules = str(self._models_config.get("safe_guard_rules") or "")
        self.model_ids = [m["id"] for m in self._models_config.get("models", [])]
        if self._workflow_id:
            self._current_model_id = self.default_id
            self._init_clients()

    @staticmethod
    def _normalize_models_config(raw_config: dict, path: Path) -> dict:
        """兼容旧版 dict 模型配置，并统一转为 list 结构"""
        if not isinstance(raw_config, dict):
            raise ValueError(f"{path} 格式错误：顶层必须是 JSON object")

        normalized = dict(raw_config)
        models = normalized.get("models", [])

        if isinstance(models, dict):
            normalized_models = []
            for model_id, model_data in models.items():
                if isinstance(model_data, str):
                    item = {"id": model_id, "model": model_data}
                elif isinstance(model_data, dict):
                    item = dict(model_data)
                    item.setdefault("id", model_id)
                else:
                    raise ValueError(f"{path} 中模型 {model_id!r} 配置必须是 object 或 string")

                if "channel" not in item and item.get("provider"):
                    item["channel"] = item["provider"]
                normalized_models.append(item)
            normalized["models"] = normalized_models
            logger.warning(f"{path} 使用旧版 models dict 配置，已自动兼容；建议改为 models list 格式")
            return normalized

        if isinstance(models, list):
            normalized_models = []
            for index, model_data in enumerate(models):
                if not isinstance(model_data, dict):
                    raise ValueError(f"{path} 中 models[{index}] 必须是 object")
                item = dict(model_data)
                item.setdefault("id", item.get("model", f"model_{index}"))
                if "channel" not in item and item.get("provider"):
                    item["channel"] = item["provider"]
                normalized_models.append(item)
            normalized["models"] = normalized_models
            return normalized

        raise ValueError(f"{path} 中 models 必须是 list 或 object")
    
    def get_model(self, model_id: Optional[str] = None) -> LLMConfig:
        """获取指定模型配置"""
        target_id = model_id or self._current_model_id or self.default_id
        
        if target_id in self._models_cache:
            return self._models_cache[target_id]
        
        # 回退到默认
        if self.default_id in self._models_cache:
            return self._models_cache[self.default_id]
        
        # 最后回退到环境变量
        return LLMConfig.from_env()
    
    def get_vision_model_id(self) -> Optional[str]:
        """
        获取视觉模型 ID
        
        优先级：
        1. models.json 中显式指定的 "vision" 字段
        2. 第一个 supports_vision=true 的 chat 模型
        
        Returns:
            视觉模型 ID，如果没有配置返回 None
        """
        # 优先使用显式配置
        if self.vision_id and self.vision_id in self._models_cache:
            return self.vision_id
        
        # 自动查找第一个支持视觉的对话模型
        for model_id, config in self._models_cache.items():
            if config.supports_vision or config.model_type == "vision":
                return model_id
        
        return None
    
    def on_init(self, workflow: "Workflow") -> None:
        """组件初始化"""
        self._workflow_id = workflow.id
        self._current_model_id = self.default_id
        
        # 初始化客户端
        self._init_clients()
        
        default_model = self.get_model()
        logger.info(f"LLMManager 初始化完成: workflow={workflow.id}, default={default_model.model}")

    def _is_chat_model_id(self, model_id: Optional[str]) -> bool:
        if not model_id:
            return False
        config = self._models_cache.get(model_id)
        return bool(config and config.model_type == "chat")
    
    def _init_clients(self) -> None:
        """初始化所有模型的 LLM 客户端"""
        for model_id, config in self._models_cache.items():
            self._clients[model_id] = self._create_client(config)
            logger.debug(f"初始化客户端: {model_id} -> {config.model} (channel={config.channel}, provider={config.provider})")

    @staticmethod
    def _parse_raw_response(raw: str) -> str:
        """解析代理返回的原始 SSE/JSON 字符串，提取实际内容"""
        import json
        content_parts = []
        for line in raw.strip().split('\n'):
            line = line.strip()
            if not line or line == 'data: [DONE]':
                continue
            payload = line[6:] if line.startswith('data: ') else line
            try:
                data = json.loads(payload)
                for choice in data.get('choices', []):
                    # 非流式格式
                    msg = choice.get('message', {})
                    if msg.get('content'):
                        content_parts.append(msg['content'])
                    # 流式格式
                    delta = choice.get('delta', {})
                    if delta.get('content'):
                        content_parts.append(delta['content'])
            except (json.JSONDecodeError, TypeError):
                continue
        return ''.join(content_parts)

    def _create_client(self, config: LLMConfig) -> Any:
        """创建 LLM 客户端"""
        if config.custom_client:
            return config.custom_client
        
        if config.provider == "openai":
            try:
                from openai import AsyncOpenAI
                api_key = _clean_api_key(config.api_key)
                if not api_key:
                    if config.base_url:
                        api_key = "agentclaw-no-api-key"
                        logger.warning(
                            f"模型 {config.id} 未配置 api_key；base_url 已设置，将使用占位 key 初始化 OpenAI 兼容客户端"
                        )
                    else:
                        message = (
                            f"模型 '{config.id}' 缺少 api_key。请在 models.json 为该模型配置 api_key。"
                        )
                        logger.warning(message)
                        return _MissingLLMClient(message)
                return AsyncOpenAI(
                    api_key=api_key,
                    base_url=config.base_url,
                    timeout=config.timeout,
                    max_retries=0,
                )
            except ImportError:
                raise ImportError(
                    "openai 库未安装。请运行: pip install openai"
                )
        
        elif config.provider == "azure":
            try:
                from openai import AsyncAzureOpenAI
                api_key = _clean_api_key(config.api_key)
                if not api_key:
                    message = (
                        f"Azure 模型 '{config.id}' 缺少 api_key。请在 models.json 为该模型配置 api_key。"
                    )
                    logger.warning(message)
                    return _MissingLLMClient(message)
                return AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=config.azure_endpoint,
                    api_version=config.api_version or "2024-02-15-preview",
                    timeout=config.timeout,
                    max_retries=0,
                )
            except ImportError:
                raise ImportError(
                    "openai 库未安装。请运行: pip install openai"
                )
        
        elif config.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic
                api_key = _clean_api_key(config.api_key)
                if not api_key:
                    message = (
                        f"Anthropic 模型 '{config.id}' 缺少 api_key。请在 models.json 为该模型配置 api_key。"
                    )
                    logger.warning(message)
                    return _MissingLLMClient(message)
                return AsyncAnthropic(
                    api_key=api_key,
                    timeout=config.timeout,
                )
            except ImportError:
                raise ImportError(
                    "anthropic 库未安装。请运行: pip install anthropic"
                )
        
        else:
            raise ValueError(
                f"不支持的 LLM provider: {config.provider}。"
                f"支持的类型: openai, azure, anthropic"
            )
    
    def _get_current_client(self, model_id: Optional[str] = None) -> tuple[Any, LLMConfig]:
        """获取当前应使用的客户端"""
        # 确保客户端已初始化
        if not self._clients:
            self._init_clients()

        # 解析别名
        if model_id == "fast":
            model_id = self.fast_id
        elif model_id == "vision":
            model_id = self.vision_id

        target_id = model_id or self._current_model_id or self.default_id
        
        # 检查是否在降级状态
        if self._fallback_state.is_fallback and not model_id:
            if self._fallback_state.fallback_until and datetime.now() < self._fallback_state.fallback_until:
                # _current_model_id 已经在降级时被设为降级模型，直接使用
                fallback_id = self._current_model_id
                if fallback_id and fallback_id in self._clients and self._is_chat_model_id(fallback_id):
                    config = self._models_cache[fallback_id]
                    return self._clients[fallback_id], config
                self._fallback_state.is_fallback = False
                self._fallback_state.failure_count = 0
                self._current_model_id = self.default_id
                target_id = self._current_model_id or self.default_id
                logger.warning(f"忽略非对话降级模型: {fallback_id}")
            else:
                # 降级时间结束，恢复默认模型
                self._fallback_state.is_fallback = False
                self._fallback_state.failure_count = 0
                self._current_model_id = self.default_id
                target_id = self._current_model_id or self.default_id
                logger.info("降级时间结束，恢复使用默认模型")
        
        if target_id in self._clients:
            config = self._models_cache.get(target_id, self.get_model(target_id))
            return self._clients[target_id], config
        
        # 回退到默认
        default_config = self.get_model()
        return self._clients.get(self.default_id), default_config
    
    def _get_fallback_model_id(self, current_id: str) -> Optional[str]:
        """获取下一个降级模型 ID"""
        # 优先使用指定的 fallback
        if self.fallback_id and self.fallback_id != current_id and self._is_chat_model_id(self.fallback_id):
            return self.fallback_id
        
        # 否则按顺序找下一个
        if current_id in self.model_ids:
            idx = self.model_ids.index(current_id)
            for next_id in self.model_ids[idx + 1:]:
                if self._is_chat_model_id(next_id):
                    return next_id
        
        return None
    
    def _handle_failure(self, error: Exception) -> None:
        """处理调用失败"""
        self._fallback_state.failure_count += 1
        
        if self.auto_fallback:
            if self._fallback_state.failure_count >= self.fallback_threshold:
                next_model = self._get_fallback_model_id(self._current_model_id)
                if next_model:
                    self._fallback_state.is_fallback = True
                    self._fallback_state.fallback_reason = str(error)
                    self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
                    self._current_model_id = next_model
                    logger.warning(f"切换到降级模型: {next_model}, 原因: {error}")
    
    def _handle_success(self) -> None:
        """处理调用成功"""
        if not self._fallback_state.is_fallback:
            self._fallback_state.failure_count = 0
    
    def _record_usage(self, stats: UsageStats) -> None:
        """记录使用统计"""
        self._usage_history.append(stats)
        self._total_tokens += stats.total_tokens
        self._total_latency_ms += stats.latency_ms
        
        # 保留最近 1000 条记录
        if len(self._usage_history) > 1000:
            self._usage_history = self._usage_history[-1000:]
        
        logger.debug(
            f"LLM 调用完成: model={stats.model_id}, "
            f"tokens={stats.total_tokens}, prompt={stats.prompt_tokens}, "
            f"cached={stats.cached_tokens}, cache_ratio={stats.cache_ratio:.2%}, "
            f"latency={stats.latency_ms:.0f}ms"
        )

    @staticmethod
    def _extract_reasoning_from_details(details: Any) -> Optional[str]:
        if details is None:
            return None
        if isinstance(details, str):
            text = details.strip()
            return text or None
        if isinstance(details, dict):
            detail_type = str(details.get("type") or "").lower()
            if "encrypted" in detail_type:
                return None
            for key in ("summary", "text", "content", "reasoning"):
                value = details.get(key)
                if isinstance(value, str):
                    text = value.strip()
                    if text:
                        return text
                if isinstance(value, list):
                    joined = "".join(str(v) for v in value if v is not None).strip()
                    if joined:
                        return joined
            return None
        if isinstance(details, list):
            parts = []
            for item in details:
                part = LLMManager._extract_reasoning_from_details(item)
                if part:
                    parts.append(part)
            if not parts:
                return None
            return "".join(parts)
        return None

    @staticmethod
    def _extract_reasoning_content(payload: Any) -> Optional[str]:
        if payload is None:
            return None

        for field_name in ("reasoning_content", "thinking", "reasoning", "thought"):
            value = getattr(payload, field_name, None)
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text

        details_value = getattr(payload, "reasoning_details", None)
        details_text = LLMManager._extract_reasoning_from_details(details_value)
        if details_text:
            return details_text

        model_extra = getattr(payload, "model_extra", None)
        if isinstance(model_extra, dict):
            for field_name in ("reasoning_content", "thinking", "reasoning", "thought"):
                value = model_extra.get(field_name)
                if isinstance(value, str):
                    text = value.strip()
                    if text:
                        return text
            details_text = LLMManager._extract_reasoning_from_details(model_extra.get("reasoning_details"))
            if details_text:
                return details_text

        return None
    
    def get_usage_stats(self) -> dict:
        """
        获取使用统计（用于监控和计费）
        
        Returns:
            {
                "total_calls": 10,
                "total_tokens": 5000,
                "total_latency_ms": 12000,
                "avg_latency_ms": 1200,
                "recent_calls": [...]
            }
        """
        return {
            "total_calls": len(self._usage_history),
            "total_tokens": self._total_tokens,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": self._total_latency_ms / len(self._usage_history) if self._usage_history else 0,
            "recent_calls": [s.to_dict() for s in self._usage_history[-10:]],
        }
    
    async def _create_chat_completion_with_visible_retries(
        self,
        client: Any,
        create_kwargs: dict,
        *,
        config: LLMConfig,
        call_type: str,
        max_attempts: int = 3,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    client.chat.completions.create(**create_kwargs),
                    timeout=max(float(config.timeout), 1.0),
                )
            except asyncio.TimeoutError as exc:
                last_error = exc
                err_str = f"LLM request timed out after {config.timeout}s"
                logger.warning(
                    f"LLM 请求超时: call_type={call_type}, model={config.id}, "
                    f"attempt={attempt}/{max_attempts}, timeout={config.timeout}s"
                )
                if attempt >= max_attempts:
                    await self._push_model_error_event(err_str, config=config, call_type=call_type)
                    raise
                delay = min(2.0, 0.5 * attempt)
                await self._push_model_retry_event(
                    err_str,
                    config=config,
                    call_type=call_type,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                last_error = exc
                err_str = str(exc)
                logger.warning(
                    f"LLM 请求失败: call_type={call_type}, model={config.id}, "
                    f"attempt={attempt}/{max_attempts}, error={err_str[:300]}"
                )
                if attempt >= max_attempts:
                    await self._push_model_error_event(err_str, config=config, call_type=call_type)
                    raise
                delay = min(2.0, 0.5 * attempt)
                await self._push_model_retry_event(
                    err_str,
                    config=config,
                    call_type=call_type,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                )
                await asyncio.sleep(delay)
        if last_error:
            raise last_error
        raise RuntimeError("LLM request failed without an exception")

    async def _push_model_retry_event(
        self,
        error: str,
        *,
        config: LLMConfig,
        call_type: str,
        attempt: int,
        max_attempts: int,
        delay: float,
    ) -> None:
        try:
            from agentclaw.runtime.streaming import get_output_channel
            channel = get_output_channel()
            if channel:
                await channel.push_model_retry(
                    error=error,
                    model=config.id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                    call_type=call_type,
                )
        except Exception as event_exc:
            logger.debug(f"推送模型重试事件失败: {event_exc}")

    async def _push_model_error_event(
        self,
        error: str,
        *,
        config: LLMConfig,
        call_type: str,
    ) -> None:
        try:
            from agentclaw.runtime.streaming import get_output_channel
            channel = get_output_channel()
            if channel:
                await channel.push_model_error(error=error, model=config.id, call_type=call_type)
        except Exception as event_exc:
            logger.debug(f"推送模型错误事件失败: {event_exc}")

    # ============================================================
    # LLM 调用
    # ============================================================
    
    async def invoke(
        self,
        messages: List[dict],
        *,
        response_format: Optional[dict] = None,
        model_id: Optional[str] = None,
        images: Optional[List["ImageInput"]] = None,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> Union[str, "LLMResponse"]:
        """
        非流式调用 LLM
        
        Args:
            messages: 消息列表，格式 [{"role": "user/assistant/system", "content": "..."}]
            response_format: 响应格式（如 {"type": "json_object"}）
            model_id: 指定使用的模型 ID
            images: 图像输入列表（用于视觉模型）
            tools: 工具定义列表（OpenAI function calling 格式）
            tool_choice: 工具选择策略（auto/required/none）
        
        Returns:
            如果没有工具调用，返回 LLM 响应文本
            如果有工具调用，返回 LLMResponse 对象（包含 content 和 tool_calls）
        """
        client, config = self._get_current_client(model_id)
        request_max_attempts = kwargs.pop("_max_attempts", 3)
        try:
            request_max_attempts = max(1, int(request_max_attempts))
        except (TypeError, ValueError):
            request_max_attempts = 3
        
        # 处理图像输入
        if images:
            from agentclaw.model.vision import build_vision_messages
            vision_msgs = build_vision_messages("", images, provider="openai")
            messages = messages + [m for m in vision_msgs if m.get("role") == "user"]
        
        import time
        start_time = time.perf_counter()
        
        call_type = str(kwargs.pop("_call_type", "invoke") or "invoke")
        prefix_hash = _messages_prefix_hash(messages)
        tools_sig = _tools_signature(tools)
        logger.info(
            f"LLM invoke: call_type={call_type}, model={config.id}, messages={len(messages)}, "
            f"tools={len(tools or [])}, tools_sig={tools_sig}, prefix_hash={prefix_hash}"
        )
        
        try:
            create_kwargs = {
                "model": config.azure_deployment or config.model,
                "messages": messages,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            }
            if response_format:
                create_kwargs["response_format"] = response_format
            if tools:
                create_kwargs["tools"] = tools
                create_kwargs["parallel_tool_calls"] = False
                if tool_choice:
                    create_kwargs["tool_choice"] = tool_choice

            # 应用自定义请求参数（用于 reasoning 等特殊配置）
            if config.extra_headers:
                create_kwargs["extra_headers"] = config.extra_headers
            if config.extra_body:
                create_kwargs["extra_body"] = config.extra_body
            
            create_kwargs.update(kwargs)
            
            completion = await self._create_chat_completion_with_visible_retries(
                client,
                create_kwargs,
                config=config,
                call_type=call_type,
                max_attempts=request_max_attempts,
            )

            # 防御：某些代理不支持非流式，返回了 AsyncStream 或原始字符串
            # 尝试当作流式响应消费，聚合为伪非流式结果
            if isinstance(completion, str):
                logger.warning(f"LLM 返回了原始字符串，尝试解析 (model={config.id})")
                parsed = self._parse_raw_response(completion)
                if parsed:
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    self._record_usage(UsageStats(
                        model_id=config.id, model_name=config.model,
                        prompt_tokens=0, completion_tokens=0, total_tokens=0,
                        latency_ms=latency_ms, success=True,
                    ))
                    self._handle_success()
                    return parsed
                # 解析失败，回退到流式模式重试
                logger.info(f"代理可能不支持非流式，以流式模式重试 (model={config.id})")
                completion = await self._create_chat_completion_with_visible_retries(
                    client,
                    {**create_kwargs, "stream": True},
                    config=config,
                    call_type=call_type,
                    max_attempts=request_max_attempts,
                )

            # 如果返回的是异步迭代器（AsyncStream），消费并聚合
            if hasattr(completion, '__aiter__'):
                logger.info(f"LLM 返回了流式响应，聚合为非流式结果 (model={config.id})")
                content_parts = []
                reasoning_parts = []
                agg_usage = None
                tool_calls_map = {}
                async for chunk in completion:
                    if hasattr(chunk, 'usage') and chunk.usage:
                        agg_usage = chunk.usage
                    if not getattr(chunk, 'choices', None):
                        continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        content_parts.append(delta.content)
                    # 收集 reasoning
                    r = self._extract_reasoning_content(delta)
                    if r:
                        reasoning_parts.append(r)
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = getattr(tc, 'index', 0) or 0
                            if tc.id:
                                tool_calls_map[idx] = {"id": tc.id, "name": "", "arguments": ""}
                            if idx in tool_calls_map:
                                if hasattr(tc, 'function') and tc.function:
                                    if tc.function.name:
                                        tool_calls_map[idx]["name"] = tc.function.name
                                    if tc.function.arguments:
                                        tool_calls_map[idx]["arguments"] += tc.function.arguments

                latency_ms = (time.perf_counter() - start_time) * 1000
                usage_stats = UsageStats(
                    model_id=config.id, model_name=config.model,
                    prompt_tokens=_usage_token_value(agg_usage, "prompt_tokens"),
                    completion_tokens=_usage_token_value(agg_usage, "completion_tokens"),
                    total_tokens=_usage_token_value(agg_usage, "total_tokens"),
                    cached_tokens=_extract_cached_tokens(agg_usage),
                    latency_ms=latency_ms, success=True,
                )
                self._record_usage(usage_stats)
                self._handle_success()
                aggregated_content = "".join(content_parts)
                aggregated_reasoning = "".join(reasoning_parts) if reasoning_parts else None

                if tool_calls_map:
                    return LLMResponse(
                        content=aggregated_content or None,
                        tool_calls=[
                            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                            for tc in tool_calls_map.values()
                        ],
                        reasoning=aggregated_reasoning,
                    )
                if not aggregated_content:
                    raise RuntimeError(f"代理流式响应内容为空 (model={config.id})")
                return aggregated_content

            # 防御：choices 为空
            if not getattr(completion, 'choices', None):
                logger.warning(f"LLM 返回了空 choices (model={config.id})")
                raise RuntimeError(f"代理返回空 choices (model={config.id})")

            message = completion.choices[0].message
            usage = completion.usage

            # 提取 reasoning 内容（非流式路径）
            reasoning_content = self._extract_reasoning_content(message)

            latency_ms = (time.perf_counter() - start_time) * 1000
            
            stats = UsageStats(
                model_id=config.id,
                model_name=config.model,
                prompt_tokens=_usage_token_value(usage, "prompt_tokens"),
                completion_tokens=_usage_token_value(usage, "completion_tokens"),
                total_tokens=_usage_token_value(usage, "total_tokens"),
                cached_tokens=_extract_cached_tokens(usage),
                latency_ms=latency_ms,
                success=True,
            )
            self._record_usage(stats)
            
            logger.debug(f"LLM 完成: {stats.total_tokens} tokens, {latency_ms:.0f}ms")
            
            self._handle_success()
            
            # 如果有工具调用，返回 LLMResponse 对象
            if message.tool_calls:
                return LLMResponse(
                    content=message.content,
                    tool_calls=[
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        )
                        for tc in message.tool_calls
                    ],
                    reasoning=reasoning_content,
                )
            
            return message.content
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            self._handle_failure(e)
            
            # 立即降级调用（不等待阈值）
            if not model_id:
                next_model = self._get_fallback_model_id(self._current_model_id)
                if next_model:
                    self._current_model_id = next_model
                    self._fallback_state.is_fallback = True
                    self._fallback_state.fallback_reason = str(e)
                    self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
                    logger.warning(f"LLM 调用失败，立即降级到: {next_model}, 原因: {e}")
                    return await self.invoke(
                        messages, model_id=next_model, 
                        response_format=response_format,
                        tools=tools,
                        tool_choice=tool_choice,
                        **kwargs
                    )
            
            raise
    
    async def stream(
        self,
        messages: List[dict],
        *,
        model_id: Optional[str] = None,
        images: Optional[List["ImageInput"]] = None,
        push_to_context: bool = True,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        流式调用 LLM
        
        Args:
            messages: 消息列表，格式 [{"role": "user/assistant/system", "content": "..."}]
            model_id: 指定使用的模型 ID
            images: 图像输入列表（用于视觉模型）
            push_to_context: 是否推送 chunk 到 StreamContext（默认 True）
        
        Yields:
            响应文本片段
        """
        import time
        start_time = time.perf_counter()

        client, config = self._get_current_client(model_id)
        call_type = str(kwargs.pop("_call_type", "stream") or "stream")
        prefix_hash = _messages_prefix_hash(messages)
        prefix_shape = _messages_prefix_shape(messages)
        tools_sig = _tools_signature(tools)
        logger.info(
            f"LLM stream: call_type={call_type}, requested={model_id}, actual={config.id}, "
            f"model={config.model}, current={self._current_model_id}, "
            f"messages={len(messages)}, tools={len(tools or [])}, tools_sig={tools_sig}, "
            f"prefix_hash={prefix_hash}, prefix_shape={prefix_shape}"
        )

        # 处理图像输入
        if images:
            from agentclaw.model.vision import build_vision_messages
            vision_msgs = build_vision_messages("", images, provider="openai")
            messages = messages + [m for m in vision_msgs if m.get("role") == "user"]

        # 获取输出通道（如果存在）
        # reasoning 始终推送（思考过程不受 push_to_context 限制）
        # message 推送受 push_to_context 控制
        output_channel = None
        reasoning_channel = None
        try:
            from agentclaw.runtime.streaming import get_output_channel
            reasoning_channel = get_output_channel()
            if push_to_context:
                output_channel = reasoning_channel
        except ImportError:
            pass

        try:
            create_kwargs = {
                "model": config.azure_deployment or config.model,
                "messages": messages,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "stream": True,
            }
            if config.stream_usage:
                create_kwargs["stream_options"] = {"include_usage": True}
            if tools:
                create_kwargs["tools"] = tools
                create_kwargs["parallel_tool_calls"] = False
                if tool_choice:
                    create_kwargs["tool_choice"] = tool_choice

            # 应用自定义请求参数
            if config.extra_headers:
                create_kwargs["extra_headers"] = config.extra_headers
            if config.extra_body:
                create_kwargs["extra_body"] = config.extra_body

            create_kwargs.update(kwargs)

            # codex 渠道强制移除 stream 相关参数（不支持 stream_options）
            if config.channel == "codex":
                create_kwargs.pop("stream_options", None)

            if call_type == "harness_post_tool":
                logger.info(
                    "LLM stream create_kwargs: call_type=%s has_response_format=%s response_format=%r has_tools=%s tool_choice=%r parallel_tool_calls=%r stream=%r stream_options=%r max_tokens=%r temperature=%r keys=%s",
                    call_type,
                    "response_format" in create_kwargs,
                    create_kwargs.get("response_format"),
                    bool(create_kwargs.get("tools")),
                    create_kwargs.get("tool_choice"),
                    create_kwargs.get("parallel_tool_calls"),
                    create_kwargs.get("stream"),
                    create_kwargs.get("stream_options"),
                    create_kwargs.get("max_tokens"),
                    create_kwargs.get("temperature"),
                    sorted(create_kwargs.keys()),
                )

            try:
                response = await self._create_chat_completion_with_visible_retries(client, create_kwargs, config=config, call_type=call_type)
            except Exception as e:
                err_str = str(e)
                logger.error(f"LLM 请求失败 (model={config.id}, channel={config.channel}): {err_str[:300]}")
                if "stream_options" in create_kwargs and "stream_options" in err_str.lower():
                    logger.warning(f"stream_options 不被支持，降级重试: {config.id}")
                    create_kwargs.pop("stream_options", None)
                    config.stream_usage = False
                    response = await self._create_chat_completion_with_visible_retries(client, create_kwargs, config=config, call_type=call_type)
                else:
                    raise

            usage = None
            _logged_delta_attrs = False  # 只记录一次
            # <think> 标签流式分离状态（Qwen 等模型将 reasoning 嵌入 content）
            _in_think_tag = False
            _think_buffer = ""
            _tag_buffer = ""  # 用于缓冲可能的标签片段

            # 防御：某些代理可能返回字符串而非 AsyncStream
            if isinstance(response, str):
                logger.warning(f"LLM stream 返回了原始字符串而非 AsyncStream (model={config.id})")
                parsed = self._parse_raw_response(response)
                if parsed:
                    if output_channel:
                        await output_channel.push_text(parsed)
                    yield parsed
                return

            async for chunk in response:
                # 检查 usage（在最后一个 chunk 中）
                if hasattr(chunk, 'usage') and chunk.usage:
                    usage = chunk.usage
                
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # 调试：记录 delta 对象的所有属性（只记录一次，仅在有 model_extra 时）
                if not _logged_delta_attrs and hasattr(delta, 'model_extra') and delta.model_extra:
                    delta_attrs = {'model_extra': str(delta.model_extra)[:200]}
                    logger.debug(f"[Reasoning Debug] stream() delta.model_extra: {delta_attrs}")
                    _logged_delta_attrs = True
                
                reasoning_content = self._extract_reasoning_content(delta)
                if not reasoning_content and hasattr(chunk.choices[0], "message"):
                    reasoning_content = self._extract_reasoning_content(chunk.choices[0].message)
                
                if reasoning_content and reasoning_channel:
                    await reasoning_channel.push_reasoning(reasoning_content)
                if delta.content:
                    text = delta.content
                    # 将缓冲的标签片段与新内容拼接
                    if _tag_buffer:
                        text = _tag_buffer + text
                        _tag_buffer = ""

                    while text:
                        if _in_think_tag:
                            # 在 think 标签内，寻找 </think>
                            end_idx = text.find("</think>")
                            if end_idx != -1:
                                # 找到结束标签
                                final_reasoning = text[:end_idx]
                                if final_reasoning:
                                    _think_buffer += final_reasoning
                                    if reasoning_channel:
                                        await reasoning_channel.push_reasoning(final_reasoning)
                                _think_buffer = ""
                                _in_think_tag = False
                                text = text[end_idx + len("</think>"):]
                            elif any(text.endswith("</think>"[:i]) for i in range(2, len("</think>"))):
                                # 可能是不完整的结束标签，缓冲
                                for i in range(min(len(text), len("</think>") - 1), 0, -1):
                                    if "</think>".startswith(text[-i:]):
                                        reasoning_part = text[:-i]
                                        if reasoning_part:
                                            _think_buffer += reasoning_part
                                            if reasoning_channel:
                                                await reasoning_channel.push_reasoning(reasoning_part)
                                        _tag_buffer = text[-i:]
                                        text = ""
                                        break
                                else:
                                    if text:
                                        _think_buffer += text
                                        if reasoning_channel:
                                            await reasoning_channel.push_reasoning(text)
                                    text = ""
                            else:
                                if text:
                                    _think_buffer += text
                                    if reasoning_channel:
                                        await reasoning_channel.push_reasoning(text)
                                text = ""
                        else:
                            # 不在 think 标签内，寻找 <think>
                            start_idx = text.find("<think>")
                            if start_idx != -1:
                                # 输出 <think> 之前的正文
                                before = text[:start_idx]
                                if before:
                                    if output_channel:
                                        await output_channel.push_message(before)
                                    yield before
                                _in_think_tag = True
                                text = text[start_idx + len("<think>"):]
                            elif text.endswith("<") or any(text.endswith("<think>"[:i]) for i in range(2, len("<think>"))):
                                # 可能是不完整的开始标签，缓冲末尾
                                for i in range(min(len(text), len("<think>") - 1), 0, -1):
                                    if "<think>".startswith(text[-i:]):
                                        before = text[:-i]
                                        if before:
                                            if output_channel:
                                                await output_channel.push_message(before)
                                            yield before
                                        _tag_buffer = text[-i:]
                                        text = ""
                                        break
                                else:
                                    if output_channel:
                                        await output_channel.push_message(text)
                                    yield text
                                    text = ""
                            else:
                                if output_channel:
                                    await output_channel.push_message(text)
                                yield text
                                text = ""

            # 流结束后，刷出残留缓冲
            if _tag_buffer:
                leftover = _tag_buffer
                _tag_buffer = ""
                if _in_think_tag:
                    _think_buffer += leftover
                else:
                    if output_channel:
                        await output_channel.push_message(leftover)
                    yield leftover
            if _think_buffer and _in_think_tag:
                # Remaining reasoning was already streamed incrementally.
                _think_buffer = ""
            latency_ms = (time.perf_counter() - start_time) * 1000
            if usage:
                stats = UsageStats(
                    model_id=config.id,
                    model_name=config.model,
                    prompt_tokens=_usage_token_value(usage, "prompt_tokens"),
                    completion_tokens=_usage_token_value(usage, "completion_tokens"),
                    total_tokens=_usage_token_value(usage, "total_tokens"),
                    cached_tokens=_extract_cached_tokens(usage),
                    latency_ms=latency_ms,
                    success=True,
                )
                self._record_usage(stats)
                logger.info(f"LLM stream usage: call_type={call_type}, prompt={stats.prompt_tokens}, cached={stats.cached_tokens}, cache_ratio={stats.cache_ratio:.2%}, total={stats.total_tokens}, latency={latency_ms:.0f}ms")
            
            self._handle_success()
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            self._handle_failure(e)
            
            # 立即降级调用（不等待阈值）
            if not model_id:
                next_model = self._get_fallback_model_id(self._current_model_id)
                if next_model:
                    self._current_model_id = next_model
                    self._fallback_state.is_fallback = True
                    self._fallback_state.fallback_reason = str(e)
                    self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
                    logger.warning(f"LLM 流式调用失败，立即降级到: {next_model}, 原因: {e}")
                    async for chunk in self.stream(
                        messages, model_id=next_model, 
                        images=images, push_to_context=push_to_context, **kwargs
                    ):
                        yield chunk
                    return
            
            raise
    
    async def stream_with_tools(
        self,
        messages: List[dict],
        *,
        tools: Optional[List[dict]] = None,
        tool_choice: Optional[str] = None,
        model_id: Optional[str] = None,
        images: Optional[List["ImageInput"]] = None,
        push_to_context: bool = True,
        **kwargs,
    ) -> AsyncIterator[Union[str, "LLMResponse"]]:
        """
        流式调用 LLM（支持工具调用）
        
        这个方法会流式输出文本内容，同时累积工具调用。
        - 文本内容以字符串 chunk 形式 yield
        - 如果有工具调用，最后会 yield 一个 LLMResponse 对象
        
        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
            tool_choice: 工具选择策略（auto/required/none）
            model_id: 指定使用的模型 ID
            images: 图像输入列表
            push_to_context: 是否推送 chunk 到 StreamContext
        
        Yields:
            str: 文本内容 chunk
            LLMResponse: 最终响应（如果有工具调用）
        
        Example:
            async for chunk in llm.stream_with_tools(messages, tools=tools):
                if isinstance(chunk, str):
                    print(chunk, end="", flush=True)  # 流式输出文本
                elif isinstance(chunk, LLMResponse):
                    if chunk.tool_calls:
                        # 处理工具调用
                        for tc in chunk.tool_calls:
                            result = await execute_tool(tc.name, tc.arguments)
        """
        import time
        start_time = time.perf_counter()

        client, config = self._get_current_client(model_id)
        call_type = str(kwargs.pop("_call_type", "stream_with_tools") or "stream_with_tools")
        prefix_hash = _messages_prefix_hash(messages)
        prefix_shape = _messages_prefix_shape(messages)
        tools_sig = _tools_signature(tools)
        logger.info(
            f"LLM stream_with_tools: call_type={call_type}, requested={model_id}, actual={config.id}, "
            f"model={config.model}, current={self._current_model_id}, messages={len(messages)}, "
            f"tools={len(tools or [])}, tools_sig={tools_sig}, prefix_hash={prefix_hash}, prefix_shape={prefix_shape}"
        )

        # 处理图像输入
        if images:
            from agentclaw.model.vision import build_vision_messages
            vision_msgs = build_vision_messages("", images, provider="openai")
            messages = messages + [m for m in vision_msgs if m.get("role") == "user"]

        # 获取输出通道
        # reasoning 始终推送，message 推送受 push_to_context 控制
        output_channel = None
        reasoning_channel = None
        try:
            from agentclaw.runtime.streaming import get_output_channel
            reasoning_channel = get_output_channel()
            if push_to_context:
                output_channel = reasoning_channel
        except ImportError:
            pass
        
        try:
            create_kwargs = {
                "model": config.azure_deployment or config.model,
                "messages": messages,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "stream": True,
            }
            if config.stream_usage:
                create_kwargs["stream_options"] = {"include_usage": True}
            if tools:
                create_kwargs["tools"] = tools
                create_kwargs["parallel_tool_calls"] = False
                if tool_choice:
                    create_kwargs["tool_choice"] = tool_choice

            # 应用自定义请求参数
            if config.extra_headers:
                create_kwargs["extra_headers"] = config.extra_headers
            if config.extra_body:
                create_kwargs["extra_body"] = config.extra_body

            create_kwargs.update(kwargs)

            # codex 渠道强制移除 stream 相关参数（不支持 stream_options）
            if config.channel == "codex":
                create_kwargs.pop("stream_options", None)

            try:
                response = await self._create_chat_completion_with_visible_retries(client, create_kwargs, config=config, call_type=call_type)
            except Exception as e:
                err_str = str(e)
                logger.error(f"LLM 请求失败 (model={config.id}, channel={config.channel}): {err_str[:300]}")
                try:
                    dump_path = _maybe_dump_llm_failure_payload(
                        create_kwargs,
                        model_id=config.id,
                        channel=config.channel,
                    )
                    if dump_path:
                        logger.error(f"LLM 失败请求参数已按配置 dump 到: {dump_path}")
                except Exception:
                    pass
                # stream_options 降级：非 codex 渠道，自动重试
                if "stream_options" in create_kwargs and "stream_options" in err_str.lower():
                    logger.warning(f"stream_options 不被支持，降级重试: {config.id}")
                    create_kwargs.pop("stream_options", None)
                    config.stream_usage = False
                    response = await self._create_chat_completion_with_visible_retries(client, create_kwargs, config=config, call_type=call_type)
                else:
                    raise
            
            # 累积内容和工具调用
            content_chunks = []
            reasoning_chunks = []  # 思考内容
            tool_calls_map = {}  # id -> {id, name, arguments}
            tool_calls_by_index = {}  # index -> tool_call_data (用于无 ID 时查找)
            usage = None
            
            _logged_delta_attrs = False  # 只记录一次
            # <think> 标签流式分离状态
            _in_think_tag = False
            _think_buffer = ""
            _tag_buffer = ""

            # 防御：某些代理可能返回字符串而非 AsyncStream
            if isinstance(response, str):
                logger.warning(f"LLM stream_with_tools 返回了原始字符串而非 AsyncStream (model={config.id})")
                parsed = self._parse_raw_response(response)
                if output_channel and parsed:
                    await output_channel.push_text(parsed)
                yield LLMResponse(content=parsed or None, tool_calls=None)
                return

            async for chunk in response:
                # 检查 usage
                if hasattr(chunk, 'usage') and chunk.usage:
                    usage = chunk.usage
                
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # 调试：记录 delta 对象的 model_extra（只记录一次）
                if not _logged_delta_attrs and hasattr(delta, 'model_extra') and delta.model_extra:
                    logger.debug(f"[Reasoning Debug] stream_with_tools() delta.model_extra: {str(delta.model_extra)[:200]}")
                    _logged_delta_attrs = True
                
                reasoning_content = self._extract_reasoning_content(delta)
                if not reasoning_content and hasattr(chunk.choices[0], "message"):
                    reasoning_content = self._extract_reasoning_content(chunk.choices[0].message)
                
                if reasoning_content:
                    reasoning_chunks.append(reasoning_content)
                    if reasoning_channel:
                        await reasoning_channel.push_reasoning(reasoning_content)
                
                # 处理文本内容（含 <think> 标签分离）
                if delta.content:
                    text = delta.content
                    if _tag_buffer:
                        text = _tag_buffer + text
                        _tag_buffer = ""

                    while text:
                        if _in_think_tag:
                            end_idx = text.find("</think>")
                            if end_idx != -1:
                                final_reasoning = text[:end_idx]
                                if final_reasoning:
                                    _think_buffer += final_reasoning
                                    reasoning_chunks.append(final_reasoning)
                                    if reasoning_channel:
                                        await reasoning_channel.push_reasoning(final_reasoning)
                                _think_buffer = ""
                                _in_think_tag = False
                                text = text[end_idx + len("</think>"):]
                            elif any(text.endswith("</think>"[:i]) for i in range(2, len("</think>"))):
                                for i in range(min(len(text), len("</think>") - 1), 0, -1):
                                    if "</think>".startswith(text[-i:]):
                                        reasoning_part = text[:-i]
                                        if reasoning_part:
                                            _think_buffer += reasoning_part
                                            reasoning_chunks.append(reasoning_part)
                                            if reasoning_channel:
                                                await reasoning_channel.push_reasoning(reasoning_part)
                                        _tag_buffer = text[-i:]
                                        text = ""
                                        break
                                else:
                                    if text:
                                        _think_buffer += text
                                        reasoning_chunks.append(text)
                                        if reasoning_channel:
                                            await reasoning_channel.push_reasoning(text)
                                    text = ""
                            else:
                                if text:
                                    _think_buffer += text
                                    reasoning_chunks.append(text)
                                    if reasoning_channel:
                                        await reasoning_channel.push_reasoning(text)
                                text = ""
                        else:
                            start_idx = text.find("<think>")
                            if start_idx != -1:
                                before = text[:start_idx]
                                if before:
                                    content_chunks.append(before)
                                    if output_channel:
                                        await output_channel.push_message(before)
                                    yield before
                                _in_think_tag = True
                                text = text[start_idx + len("<think>"):]
                            elif any(text.endswith("<think>"[:i]) for i in range(2, len("<think>"))):
                                for i in range(min(len(text), len("<think>") - 1), 0, -1):
                                    if "<think>".startswith(text[-i:]):
                                        before = text[:-i]
                                        if before:
                                            content_chunks.append(before)
                                            if output_channel:
                                                await output_channel.push_message(before)
                                            yield before
                                        _tag_buffer = text[-i:]
                                        text = ""
                                        break
                                else:
                                    content_chunks.append(text)
                                    if output_channel:
                                        await output_channel.push_message(text)
                                    yield text
                                    text = ""
                            else:
                                content_chunks.append(text)
                                if output_channel:
                                    await output_channel.push_message(text)
                                yield text
                                text = ""

                # 处理工具调用（累积 chunks）
                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        tc_index = getattr(tc_chunk, 'index', 0) or 0
                        tc_id = tc_chunk.id

                        # 通过 index 查找或创建
                        if tc_index not in tool_calls_by_index:
                            tool_calls_by_index[tc_index] = {
                                "id": tc_id or f"temp_{tc_index}",
                                "index": tc_index,
                                "name": "",
                                "arguments": "",
                            }

                        target_tc = tool_calls_by_index[tc_index]

                        # 更新 ID（如果有新的）
                        if tc_id:
                            target_tc["id"] = tc_id

                        # 累积内容
                        if tc_chunk.function:
                            if tc_chunk.function.name:
                                target_tc["name"] += tc_chunk.function.name
                            if tc_chunk.function.arguments:
                                target_tc["arguments"] += tc_chunk.function.arguments

            # 流结束后，刷出残留缓冲
            if _tag_buffer:
                leftover = _tag_buffer
                _tag_buffer = ""
                if _in_think_tag:
                    _think_buffer += leftover
                else:
                    content_chunks.append(leftover)
                    if output_channel:
                        await output_channel.push_message(leftover)
                    yield leftover
            if _think_buffer and _in_think_tag:
                # Remaining reasoning was already streamed incrementally.
                _think_buffer = ""

            # 记录 usage 统计
            latency_ms = (time.perf_counter() - start_time) * 1000
            if usage:
                stats = UsageStats(
                    model_id=config.id,
                    model_name=config.model,
                    prompt_tokens=_usage_token_value(usage, "prompt_tokens"),
                    completion_tokens=_usage_token_value(usage, "completion_tokens"),
                    total_tokens=_usage_token_value(usage, "total_tokens"),
                    cached_tokens=_extract_cached_tokens(usage),
                    latency_ms=latency_ms,
                    success=True,
                )
                self._record_usage(stats)
                logger.info(
                    f"LLM stream_with_tools usage: call_type={call_type}, prompt={stats.prompt_tokens}, "
                    f"cached={stats.cached_tokens}, cache_ratio={stats.cache_ratio:.2%}, "
                    f"total={stats.total_tokens}, latency={latency_ms:.0f}ms"
                )
            
            self._handle_success()

            # 诊断日志：流式调用完成后汇总
            full_text = "".join(content_chunks)
            full_reasoning = "".join(reasoning_chunks)
            tc_names = [tc["name"] for tc in tool_calls_by_index.values()] if tool_calls_by_index else []
            logger.info(
                f"stream_with_tools 完成: call_type={call_type}, model={config.id}, "
                f"text_len={len(full_text)}, reasoning_len={len(full_reasoning)}, "
                f"tool_count={len(tc_names)}, tool_calls={tc_names}, "
                f"pushed_to_user={output_channel is not None}"
            )

            # 如果有工具调用，yield LLMResponse
            if tool_calls_by_index:
                yield LLMResponse(
                    content="".join(content_chunks) if content_chunks else None,
                    tool_calls=[
                        ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                        for tc in tool_calls_by_index.values()
                    ],
                    reasoning=full_reasoning or None,
                )
            elif content_chunks:
                # 没有工具调用，yield 最终的 LLMResponse（方便调用方判断）
                yield LLMResponse(content="".join(content_chunks), tool_calls=None, reasoning=full_reasoning or None)
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"LLM 流式工具调用失败 (model={config.id}, channel={config.channel}): {e}")
            self._handle_failure(e)
            
            # 降级处理
            if not model_id:
                next_model = self._get_fallback_model_id(self._current_model_id)
                if next_model:
                    self._current_model_id = next_model
                    self._fallback_state.is_fallback = True
                    self._fallback_state.fallback_reason = str(e)
                    self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
                    logger.warning(f"LLM 流式工具调用失败，降级到: {next_model}")
                    async for item in self.stream_with_tools(
                        messages, tools=tools, tool_choice=tool_choice,
                        model_id=next_model, images=images, 
                        push_to_context=push_to_context, **kwargs
                    ):
                        yield item
                    return
            
            raise

    async def invoke_with_tools(
        self,
        messages: List[dict],
        tools: List[dict],
        **kwargs,
    ) -> dict:
        """
        带工具调用的 LLM 调用
        
        Args:
            messages: 消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
        
        Returns:
            包含 content 和 tool_calls 的响应
        """
        client, config = self._get_current_client()
        
        try:
            response = await client.chat.completions.create(
                model=config.azure_deployment or config.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                **kwargs,
            )

            # 防御：某些代理不支持非流式，返回原始字符串
            if isinstance(response, str):
                logger.warning(f"LLM 返回了原始字符串，尝试解析 (model={config.id})")
                parsed = self._parse_raw_response(response)
                if parsed:
                    self._handle_success()
                    return {"content": parsed, "tool_calls": None}
                # 解析失败，回退到流式模式重试
                logger.info(f"代理可能不支持非流式，以流式模式重试 (model={config.id})")
                response = await client.chat.completions.create(
                    model=config.azure_deployment or config.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                    **kwargs,
                )

            # 如果返回的是异步迭代器（AsyncStream），消费并聚合
            if hasattr(response, '__aiter__'):
                logger.info(f"LLM 返回了流式响应，聚合为非流式结果 (model={config.id})")
                content_parts = []
                tool_calls_map = {}
                async for chunk in response:
                    if not getattr(chunk, 'choices', None):
                        continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        content_parts.append(delta.content)
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = getattr(tc, 'index', 0) or 0
                            if tc.id:
                                tool_calls_map[idx] = {"id": tc.id, "name": "", "arguments": ""}
                            if idx in tool_calls_map:
                                if hasattr(tc, 'function') and tc.function:
                                    if tc.function.name:
                                        tool_calls_map[idx]["name"] = tc.function.name
                                    if tc.function.arguments:
                                        tool_calls_map[idx]["arguments"] += tc.function.arguments
                self._handle_success()
                return {
                    "content": "".join(content_parts) or None,
                    "tool_calls": list(tool_calls_map.values()) if tool_calls_map else None,
                }

            # 防御：choices 为空
            if not getattr(response, 'choices', None):
                logger.warning(f"LLM 返回了空 choices (model={config.id})")
                raise RuntimeError(f"代理返回空 choices (model={config.id})")

            message = response.choices[0].message
            result = {
                "content": message.content,
                "tool_calls": None,
            }
            
            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in message.tool_calls
                ]
            
            self._handle_success()
            return result
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"LLM 工具调用失败: {e}")
            self._handle_failure(e)
            
            # 立即降级调用（不等待阈值）
            next_model = self._get_fallback_model_id(self._current_model_id)
            if next_model:
                self._current_model_id = next_model
                self._fallback_state.is_fallback = True
                self._fallback_state.fallback_reason = str(e)
                self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
                logger.warning(f"LLM 工具调用失败，立即降级到: {next_model}, 原因: {e}")
                return await self.invoke_with_tools(messages, tools, **kwargs)
            
            raise
    
    @property
    def is_fallback_active(self) -> bool:
        """是否正在使用降级模型"""
        return self._fallback_state.is_fallback
    
    @property
    def current_model(self) -> str:
        """当前使用的模型"""
        _, config = self._get_current_client()
        return config.model
    
    def force_fallback(self, reason: str = "手动触发") -> None:
        """强制切换到降级模型"""
        if self.fallback_id and self._is_chat_model_id(self.fallback_id):
            self._fallback_state.is_fallback = True
            self._fallback_state.fallback_reason = reason
            self._fallback_state.fallback_until = datetime.now() + timedelta(seconds=self.fallback_duration)
            logger.info(f"强制切换到降级模型: {reason}")
    
    def force_primary(self) -> None:
        """强制切换回主模型"""
        self._fallback_state.is_fallback = False
        self._fallback_state.failure_count = 0
        self._current_model_id = self.default_id
        logger.info("强制切换回主模型")
    
    # ============================================================
    # Admin Dashboard 扩展方法
    # ============================================================
    
    def get_all_models(self) -> List[LLMConfig]:
        """
        获取所有模型配置
        
        Returns:
            模型配置列表
        """
        return list(self._models_cache.values())
    
    def get_fallback_state(self) -> dict:
        """
        获取降级状态详情
        
        Returns:
            降级状态字典，包含：
            - is_fallback: 是否处于降级状态
            - fallback_reason: 降级原因
            - fallback_until: 降级结束时间
            - failure_count: 失败计数
            - current_model_id: 当前使用的模型 ID
            - default_model_id: 默认模型 ID
            - fallback_model_id: 降级模型 ID
        """
        return {
            "is_fallback": self._fallback_state.is_fallback,
            "fallback_reason": self._fallback_state.fallback_reason,
            "fallback_until": self._fallback_state.fallback_until.isoformat() 
                if self._fallback_state.fallback_until else None,
            "failure_count": self._fallback_state.failure_count,
            "current_model_id": self._current_model_id,
            "default_model_id": self.default_id,
            "fallback_model_id": self.fallback_id,
        }
    
    def update_model_config(self, model_id: str, **params) -> bool:
        """
        运行时更新模型参数
        
        只允许更新安全的参数（temperature, max_tokens, timeout），
        不允许修改 api_key 等敏感参数。
        
        Args:
            model_id: 模型 ID
            **params: 要更新的参数
            
        Returns:
            是否更新成功
        """
        if model_id not in self._models_cache:
            return False
        
        config = self._models_cache[model_id]
        
        # 允许更新的参数（安全参数）
        allowed_params = {"temperature", "max_tokens", "timeout"}
        
        updated = False
        for key, value in params.items():
            if key in allowed_params and hasattr(config, key):
                setattr(config, key, value)
                updated = True
                logger.info(f"更新模型 {model_id} 参数: {key}={value}")
        
        # 如果有更新，重新初始化客户端
        if updated:
            self._clients[model_id] = self._create_client(config)
        
        return updated
    
    def get_model_info(self, model_id: str) -> Optional[dict]:
        """
        获取单个模型的详细信息
        
        Args:
            model_id: 模型 ID
            
        Returns:
            模型信息字典，如果不存在返回 None
        """
        if model_id not in self._models_cache:
            return None
        
        config = self._models_cache[model_id]
        
        # 判断模型状态
        if model_id == self._current_model_id:
            status = "primary" if not self._fallback_state.is_fallback else "fallback"
        elif model_id == self.fallback_id:
            status = "fallback" if self._fallback_state.is_fallback else "standby"
        else:
            status = "standby"
        
        info = {
            "id": config.id,
            "channel": config.channel,
            "provider": config.provider,
            "model": config.model,
            "model_type": config.model_type,
            "supports_vision": config.supports_vision,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout": config.timeout,
            "status": status,
            "is_current": model_id == self._current_model_id,
        }
        if config.extra_body:
            info.update(config.extra_body)
        return info


def _usage_token_value(usage: Any, name: str) -> int:
    value = getattr(usage, name, 0) if usage is not None else 0
    try:
        return int(value or 0)
    except Exception:
        return 0


def _extract_cached_tokens(usage: Any) -> int:
    if usage is None:
        return 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is None:
        return 0
    if isinstance(details, dict):
        value = details.get("cached_tokens") or details.get("cache_read_input_tokens") or 0
    else:
        value = getattr(details, "cached_tokens", 0) or getattr(details, "cache_read_input_tokens", 0) or 0
    try:
        return int(value or 0)
    except Exception:
        return 0


def _messages_prefix_hash(messages: list[dict], *, limit: int = 8) -> str:
    stable_messages = []
    for message in (messages or [])[:limit]:
        stable_messages.append({
            "role": message.get("role"),
            "content": message.get("content", ""),
        })
    payload = json.dumps(stable_messages, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _messages_prefix_shape(messages: list[dict], *, limit: int = 12) -> str:
    parts = []
    for message in (messages or [])[:limit]:
        content = message.get("content", "")
        if isinstance(content, str):
            content_len = len(content)
        else:
            content_len = len(json.dumps(content, ensure_ascii=False, default=str))
        role = str(message.get("role") or "?")[:1]
        tool_calls = message.get("tool_calls")
        tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        tool_call_id = message.get("tool_call_id")
        marker = f"/{tool_count}tc" if tool_count else ""
        marker += "/tr" if tool_call_id else ""
        parts.append(f"{role}{content_len}{marker}")
    if len(messages or []) > limit:
        parts.append(f"+{len(messages or []) - limit}")
    return ",".join(parts)


def _tools_signature(tools: Optional[List[dict]]) -> str:
    names = []
    for tool in tools or []:
        name = tool.get("function", {}).get("name") if isinstance(tool, dict) else None
        if name:
            names.append(str(name))
    payload = json.dumps(names, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
