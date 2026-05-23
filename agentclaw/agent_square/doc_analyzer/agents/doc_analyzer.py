"""
Example 10: Document Processing
Parse documents (PDF, DOCX, PPTX, etc.) and analyze with LLM.

DocumentNode uses markitdown to convert documents to Markdown text,
then passes the result to downstream LLM nodes for analysis.

Requires:
    pip install agentclaw-ai[document]

Demonstrates:
- DocumentNode for file parsing (single and multi-file)
- Files type for multi-file upload
- Chaining document parsing → LLM analysis

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input
from agentclaw.inputs.types import Files
from agentclaw.node.document import DocumentNode

workflow = Workflow(
    id="doc_analyzer",
    name="10 Document Analyzer",
    description="文档处理示例：上传多个文档，解析内容后由 LLM 综合分析。",
    welcome="📄 上传文档（支持多文件：PDF/DOCX/PPTX/TXT），我来帮你分析内容。",
    inputs=[
        # Files 类型 — 前端显示多文件上传控件
        # state 中的值为文件 meta 列表: [{file_path, original_name, mime_type, size}, ...]
        Input("documents", Files, required=True, description="文档文件（支持多个）"),
        Input("question", str, default="请总结这些文档的主要内容", description="分析问题"),
    ],
)

# ============================================================
# DocumentNode 参数说明:
#   id               — 节点 ID
#   input_key        — state 中文档路径的 key
#                      支持: str(单个路径), list[str], list[dict]
#                      Files 类型传入 [{file_path, original_name, ...}]
#   output_key       — 解析结果存入 state 的 key，默认为节点 id
#   include_metadata — 是否包含文档元数据（文件名、大小等），默认 False
#   max_length       — 最大输出长度（字符数），0 表示不限制
#   description      — 节点描述，Dashboard 展示用
#
# 支持的文件格式:
#   PDF, DOCX, PPTX, XLSX, HTML, Markdown, TXT, CSV, JSON,
#   图片 (OCR), 音频 (Whisper 转录) 等 — 依赖 markitdown
# ============================================================
workflow.add_node(DocumentNode(
    id="parse",
    input_key="documents",
    output_key="doc_content",
    include_metadata=True,
    max_length=50000,
    description="解析文档",
))

# LLM 分析解析后的文档内容
workflow.add_node(LLMNode(
    id="analyze",
    system_prompt="""你是一位文档分析专家。基于以下文档内容回答用户的问题。

文档内容:
{doc_content}""",
    user_prompt="{question}",
    stream=True,
    output_to_user=True,
    model_params={"max_tokens": 4096},
))

workflow.add_edge("__start__", "parse")
workflow.add_edge("parse", "analyze")


async def main():
    import os

    # 创建测试文件
    files = []
    for i, (name, content) in enumerate([
        ("overview.txt", """AgentClaw Framework Overview

AgentClaw is a lightweight AI agent framework for building
production-ready intelligent agents. Key features:
1. Declarative Workflows
2. Built-in Dashboard
3. MCP Integration
Architecture: FastAPI + LangGraph + Vue 3
"""),
        ("changelog.txt", """Changelog v1.2.0

- Added scheduler module with cron/interval/date triggers
- Added webhook trigger support
- Fixed parallel node execution ordering
- Improved context compression performance
"""),
    ]):
        path = f"/tmp/test_doc_{i}.txt"
        with open(path, "w") as f:
            f.write(content)
        files.append({"file_path": path, "original_name": name, "mime_type": "text/plain", "size": len(content)})

    print("=== Example 10: Document Processing (Multi-file) ===\n")
    result = await workflow.run({
        "documents": files,
        "question": "综合两份文档，列出项目核心功能和最近更新",
    })
    print(f"\nAnalysis:\n{result['state'].get('analyze', '')}")

    for f in files:
        os.remove(f["file_path"])


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
