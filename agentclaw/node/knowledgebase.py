"""
KnowledgeBaseNode - 知识库检索节点

从知识库中检索与输入查询相关的内容分块，支持溯源（返回来源文档信息）。

Example:
    workflow.add_node(KnowledgeBaseNode(
        id="kb_search",
        input_key="query",           # 从 state 中读取查询文本
        knowledgebase_id="xxx",       # 指定知识库 ID（留空则使用默认知识库）
        top_k=5,
        mode="hybrid",               # dense / keyword / hybrid
    ))

输出结构（写入 state[output_key]）:
    {
        "chunks": [
            {
                "content": "分块内容...",
                "score": 0.85,
                "document_name": "intro.pdf",
                "source_path": "/path/to/intro.pdf",
                "download_url": "/api/files/{file_id}",
                "chunk_id": "abc123",
                "document_id": "def456",
                "chunk_index": 0,
                "dense_score": 0.9,
                "keyword_score": 0.7,
            },
            ...
        ],
        "sources": [
            {
                "document_name": "intro.pdf",
                "source_path": "/path/to/intro.pdf",
                "download_url": "/api/files/{file_id}",
            },
            ...
        ],
        "query": "用户的查询",
        "total": 5,
        "strategy": "hybrid",
    }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentclaw.node.custom import CustomNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext

logger = get_logger(__name__)


class KnowledgeBaseNode(CustomNode):
    """
    知识库检索节点

    根据输入查询从知识库中检索相关内容分块，输出包含溯源信息。

    Args:
        id: 节点 ID
        input_key: state 中查询文本的 key，默认 "query"
        knowledgebase_id: 目标知识库 ID（空字符串使用默认知识库）
        top_k: 返回的最大分块数
        mode: 检索策略 - "dense" / "keyword" / "hybrid"
        score_threshold: 分数过滤阈值（None 表示不过滤）
        rerank_model_id: rerank 模型 ID（None 使用知识库配置的默认模型）
        content_template: 内容模板，用于格式化每个分块写入 state 的文本。
            可用变量: {content}, {document_name}, {score}, {chunk_index}
            默认 None 表示原样输出 chunks 列表。
    """

    def __init__(
        self,
        id: str,
        input_key: str = "query",
        knowledgebase_id: str = "",
        top_k: int = 5,
        mode: str = "hybrid",
        score_threshold: Optional[float] = None,
        rerank_model_id: Optional[str] = None,
        content_template: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(id, **kwargs)
        self.input_key = input_key
        self.knowledgebase_id = knowledgebase_id
        self.top_k = top_k
        self.mode = mode
        self.score_threshold = score_threshold
        self.rerank_model_id = rerank_model_id
        self.content_template = content_template

    def process(self, **kwargs) -> Dict[str, Any]:
        raise RuntimeError("KnowledgeBaseNode 是异步节点，请通过 async_execute 调用")

    async def async_execute(self, state: dict, context: "WorkflowContext") -> Dict[str, Any]:
        from agentclaw.knowledgebase import get_knowledgebase_service

        service = get_knowledgebase_service()
        if service is None:
            logger.warning("KnowledgeBaseNode: 知识库服务未初始化，跳过检索")
            return {self.get_output_key(): {"chunks": [], "sources": [], "query": "", "total": 0, "strategy": ""}}

        query = state.get(self.input_key) or ""
        if isinstance(query, list):
            # 兼容 messages 列表：取最后一条用户消息
            for msg in reversed(query):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    query = msg.get("content", "")
                    break
                elif hasattr(msg, "content"):
                    query = msg.content
                    break
            else:
                query = ""

        query = str(query).strip()
        if not query:
            logger.warning(f"KnowledgeBaseNode: 查询为空 (input_key={self.input_key})")
            return {self.get_output_key(): {"chunks": [], "sources": [], "query": "", "total": 0, "strategy": ""}}

        logger.info(f"KnowledgeBaseNode: 检索 query={query[:80]}... top_k={self.top_k} mode={self.mode}")

        result = await service.search(
            query=query,
            knowledgebase_id=self.knowledgebase_id,
            top_k=self.top_k,
            mode=self.mode,
            score_threshold=self.score_threshold,
            rerank_model_id=self.rerank_model_id,
        )

        # 查找各文档的 file_hash，用于生成统一下载 URL
        doc_file_ids: Dict[str, str] = {}  # document_id -> file_id
        unique_doc_ids = {hit.document_id for hit in result.hits if hit.document_id}
        for doc_id in unique_doc_ids:
            try:
                doc = await service.get_document(result.knowledgebase_id, doc_id)
                if doc and doc.file_hash:
                    doc_file_ids[doc_id] = doc.file_hash[:32]
            except Exception:
                pass

        # 构建 chunks 列表（带溯源）
        chunks: List[Dict[str, Any]] = []
        seen_sources: Dict[str, Dict[str, str]] = {}  # document_id -> source info

        for hit in result.hits:
            file_id = doc_file_ids.get(hit.document_id)
            if file_id:
                from agentclaw.api.files.signing import get_signed_file_url

                download_url = get_signed_file_url(file_id)
            else:
                download_url = f"/admin/knowledgebases/{result.knowledgebase_id}/documents/{hit.document_id}/download"
            chunk_data = {
                "content": hit.content,
                "score": hit.score,
                "document_name": hit.document_name,
                "source_path": hit.source_path,
                "download_url": download_url,
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "chunk_index": hit.chunk_index,
                "dense_score": hit.dense_score,
                "keyword_score": hit.keyword_score,
            }
            if hit.metadata:
                chunk_data["metadata"] = hit.metadata
            chunks.append(chunk_data)

            # 去重收集溯源来源
            if hit.document_id and hit.document_id not in seen_sources:
                seen_sources[hit.document_id] = {
                    "document_id": hit.document_id,
                    "document_name": hit.document_name,
                    "source_path": hit.source_path,
                    "download_url": download_url,
                }

        sources = list(seen_sources.values())

        logger.info(f"KnowledgeBaseNode: 检索完成 hits={len(chunks)} sources={len(sources)} strategy={result.strategy}")

        output = {
            "chunks": chunks,
            "sources": sources,
            "query": query,
            "total": len(chunks),
            "strategy": result.strategy,
        }

        # 如果设置了 content_template，额外生成格式化文本便于 LLMNode 直接使用
        if self.content_template and chunks:
            formatted_parts = []
            for chunk in chunks:
                try:
                    formatted_parts.append(self.content_template.format(**chunk))
                except KeyError:
                    formatted_parts.append(chunk["content"])
            output["formatted_text"] = "\n\n".join(formatted_parts)

        return {self.get_output_key(): output}
