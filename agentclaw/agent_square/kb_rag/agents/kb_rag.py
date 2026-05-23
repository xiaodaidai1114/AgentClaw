"""
Example 11: Knowledge Base RAG
知识库 RAG 工作流示例

流程: 用户提问 → 知识库检索 → LLM 基于检索结果回答（附带引用来源）

环境要求:
  - PostgreSQL + Milvus (或 Milvus Lite)
  - models.json 中配置 embedding / rerank 模型
  - 至少创建一个知识库并上传文档
"""

import os

from agentclaw import Workflow, LLMNode, KnowledgeBaseNode
from agentclaw.inputs.types import Input

# ============================================================
# 工作流定义
# ============================================================

workflow = Workflow(
    id="kb_rag",
    name="11 知识库问答",
    description="基于知识库检索的 RAG 问答工作流。检索相关文档分块后，由 LLM 生成带引用来源的回答。",
    welcome="你好！我会根据知识库中的文档来回答你的问题。请问有什么想了解的？",
    inputs=[
        Input("user_input", str, required=True, description="用户问题"),
    ],
    user_input="user_input",
)

# ============================================================
# 节点 1: 知识库检索
# ============================================================
KB_RAG_KNOWLEDGEBASE_ID = os.getenv("KB_RAG_KNOWLEDGEBASE_ID", "")

# KnowledgeBaseNode 从 state["user_input"] 读取查询文本，
# 将检索结果写入 state["kb_result"]，结构如下:
#   {
#       "chunks": [{content, score, document_name, download_url, ...}, ...],
#       "sources": [{document_name, download_url, ...}, ...],
#       "query": "...",
#       "total": 3,
#       "strategy": "hybrid+rerank",
#   }

workflow.add_node(KnowledgeBaseNode(
    id="kb_search",
    input_key="user_input",
    # KB_RAG_KNOWLEDGEBASE_ID 可在 .env 中指向一个已创建的知识库；
    # 留空时使用 DEFAULT_KNOWLEDGEBASE_ID 或默认知识库。
    knowledgebase_id=KB_RAG_KNOWLEDGEBASE_ID,
    top_k=5,
    mode="hybrid",
    output_to_user=False,
))

# ============================================================
# 节点 2: LLM 生成回答
# ============================================================
# system_prompt 中通过 {kb_search} 引用上一个节点的输出，
# 框架会自动将 state["kb_search"] 的内容注入到提示词中。

RAG_SYSTEM_PROMPT = """\
你是一个专业的知识库问答助手。请根据下面提供的参考资料来回答用户的问题。

## 回答要求
1. 仅基于参考资料中的内容回答，不要编造信息
2. 如果参考资料中没有相关内容，请如实告知用户
3. 在回答末尾列出引用的来源文档

## 参考资料
{kb_search}
"""

workflow.add_node(LLMNode(
    id="answer",
    system_prompt=RAG_SYSTEM_PROMPT,
    stream=True,
    output_to_user=True,
))

# 连接节点: kb_search → answer
workflow.add_edge("kb_search", "answer")

# 发布
workflow.publish()
