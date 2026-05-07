"""
知识库模型访问层

职责：
- 从 models.json 解析知识库相关模型角色
- 提供 embedding 调用
- 与聊天 LLMManager 解耦
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from agentclaw.logger.config import get_logger
from agentclaw.model.manager import LLMConfig

logger = get_logger(__name__)


class KnowledgeBaseModelGateway:
    """知识库模型访问层。"""

    def __init__(
        self,
        *,
        models_config_path: Optional[str],
        default_embedding_model: str = "",
        default_rerank_model: str = "",
        default_llm_model: str = "",
    ):
        self.models_config_path = Path(models_config_path).resolve() if models_config_path else None
        self.default_embedding_model = default_embedding_model.strip()
        self.default_rerank_model = default_rerank_model.strip()
        self.default_llm_model = default_llm_model.strip()
        self._raw_config: Optional[Dict[str, Any]] = None
        self._models: Dict[str, LLMConfig] = {}
        self._clients: Dict[str, Any] = {}
        self._load_models()

    def _load_models(self) -> None:
        if not self.models_config_path or not self.models_config_path.exists():
            logger.warning("KnowledgeBaseModelGateway: models.json 不存在，知识库模型解析将不可用")
            self._raw_config = {}
            self._models = {}
            return

        self._raw_config = json.loads(self.models_config_path.read_text(encoding="utf-8"))
        self._models = {
            item["id"]: LLMConfig.from_dict(item)
            for item in self._raw_config.get("models", [])
            if item.get("id")
        }

    def _get_role_defaults(self) -> Dict[str, str]:
        raw = self._raw_config or {}
        kb = raw.get("knowledgebase") or raw.get("knowledge_base") or {}
        return {
            "embedding": self.default_embedding_model or str(kb.get("embedding", "") or ""),
            "rerank": self.default_rerank_model or str(kb.get("rerank", "") or ""),
            "llm": self.default_llm_model or str(kb.get("llm", "") or kb.get("chat", "") or ""),
        }

    def get_default_model_id(self, role: str) -> str:
        defaults = self._get_role_defaults()
        configured = defaults.get(role, "").strip()
        if configured:
            return configured

        if role == "embedding":
            for model_id, cfg in self._models.items():
                if cfg.model_type == "embedding":
                    return model_id
        if role == "rerank":
            for model_id, cfg in self._models.items():
                if cfg.model_type == "rerank":
                    return model_id
        if role == "llm":
            return str((self._raw_config or {}).get("default", "") or "")
        return ""

    def resolve_model(self, *, role: str, model_id: str = "") -> LLMConfig:
        selected_id = (model_id or "").strip() or self.get_default_model_id(role)
        if not selected_id:
            raise RuntimeError(f"未配置知识库 {role} 模型，请在 models.json 或知识库配置中指定")
        config = self._models.get(selected_id)
        if not config:
            raise RuntimeError(f"模型 '{selected_id}' 不存在于 models.json")
        return config

    def _get_client(self, config: LLMConfig):
        client = self._clients.get(config.id)
        if client is not None:
            return client

        if config.provider == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout,
            )
        elif config.provider == "azure":
            from openai import AsyncAzureOpenAI

            client = AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=config.azure_endpoint,
                api_version=config.api_version or "2024-02-15-preview",
                timeout=config.timeout,
            )
        else:
            raise RuntimeError(
                f"知识库当前仅支持 openai/azure 兼容 embedding 调用，收到 provider={config.provider!r}"
            )

        self._clients[config.id] = client
        return client

    async def embed_texts(self, texts: List[str], *, model_id: str = "") -> List[List[float]]:
        normalized = [text.strip() for text in texts if text and text.strip()]
        if not normalized:
            return []

        config = self.resolve_model(role="embedding", model_id=model_id)
        client = self._get_client(config)
        vectors: List[List[float]] = []

        batch_size = 32
        for start in range(0, len(normalized), batch_size):
            batch = normalized[start:start + batch_size]
            response = await client.embeddings.create(
                model=config.model,
                input=batch,
                extra_headers=config.extra_headers,
                extra_body=config.extra_body,
            )
            data = getattr(response, "data", None) or []
            vectors.extend([list(item.embedding) for item in data])

        return vectors

    async def rerank_texts(
        self,
        *,
        query: str,
        texts: List[str],
        model_id: str = "",
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        normalized = [text.strip() for text in texts if text and text.strip()]
        if not query.strip() or not normalized:
            return []

        config = self.resolve_model(role="rerank", model_id=model_id)
        base_url = (config.base_url or "").rstrip("/")
        if not base_url:
            raise RuntimeError(f"知识库 rerank 模型 '{config.id}' 缺少 base_url 配置")
        if not config.api_key:
            raise RuntimeError(f"知识库 rerank 模型 '{config.id}' 缺少 api_key 配置")

        payload: Dict[str, Any] = {
            "model": config.model,
            "query": query,
            "documents": normalized,
            "top_n": int(top_n or len(normalized)),
            "return_documents": False,
        }
        if config.extra_body:
            payload.update(config.extra_body)

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        if config.extra_headers:
            headers.update(config.extra_headers)

        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(
                f"{base_url}/rerank",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()

        results = body.get("results") or body.get("data") or []
        ranked: List[Dict[str, Any]] = []
        for item in results:
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            score = float(item.get("relevance_score", item.get("score", 0.0)) or 0.0)
            ranked.append({"index": index, "score": score})
        return ranked
