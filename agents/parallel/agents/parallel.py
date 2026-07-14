"""
Example 05: Parallel Execution
Run multiple analysis tasks in parallel, then combine results.

Demonstrates:
- Fan-out: one node triggers multiple parallel nodes
- Fan-in: multiple nodes converge to one combiner node
- output_key for cross-node data passing

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="parallel",
    name="05 Parallel Analysis",
    description="Fan-out/Fan-in 并行执行：同时分析情感、关键词、摘要，最后合并报告。",
    welcome="📊 输入一段文本，我会并行分析情感、关键词和摘要，最后生成综合报告。",
    inputs=[
        Input("user_input", str, required=True, description="Text to analyze"),
    ],
    user_input="user_input",
)

# ============================================================
# 预处理节点 — 提取主题
#
# output_key — 输出写入 state["topic"]，后续节点可用 {topic} 引用
# ============================================================
workflow.add_node(LLMNode(
    id="preprocess",
    system_prompt="Extract the main topic from: {user_input}",
    output_key="topic",
))

# ============================================================
# 并行分析节点 — 三个节点同时执行
#
# save_to_context=False — 这些是独立分析任务，不需要共享对话历史
# output_key            — 每个节点输出到不同的 state key，避免覆盖
# ============================================================
workflow.add_node(LLMNode(
    id="sentiment",
    system_prompt="Analyze the sentiment of this text. Return: positive/negative/neutral with brief explanation.\nText: {user_input}",
    output_key="sentiment_result",
    save_to_context=False,
))

workflow.add_node(LLMNode(
    id="keywords",
    system_prompt="Extract 3-5 key phrases from this text.\nText: {user_input}",
    output_key="keywords_result",
    save_to_context=False,
))

workflow.add_node(LLMNode(
    id="summary",
    system_prompt="Write a one-sentence summary of this text.\nText: {user_input}",
    output_key="summary_result",
    save_to_context=False,
))

# ============================================================
# 合并节点 — 汇总所有并行节点的结果
#
# system_prompt 中引用了上游节点的 output_key:
#   {topic}            — 来自 preprocess 节点
#   {sentiment_result} — 来自 sentiment 节点
#   {keywords_result}  — 来自 keywords 节点
#   {summary_result}   — 来自 summary 节点
# ============================================================
workflow.add_node(LLMNode(
    id="combine",
    system_prompt="""Combine these analysis results into a structured report:

Topic: {topic}
Sentiment: {sentiment_result}
Keywords: {keywords_result}
Summary: {summary_result}

Format as a brief analysis report.""",
    output_key="final_report",
    output_to_user=True,
))

# ============================================================
# 边连接 — Fan-out / Fan-in 模式
#
# add_edge(from, [to1, to2, to3])
#   列表语法表示并行执行，三个节点同时启动，全部完成后才继续
#
# Fan-in: 多个节点都连接到同一个目标，该目标等所有上游完成后执行
# ============================================================
workflow.add_edge("__start__", "preprocess")

# Fan-out: preprocess 完成后，三个分析节点并行执行
workflow.add_edge("preprocess", ["sentiment", "keywords", "summary"])

# Fan-in: 三个分析节点全部完成后，合并结果
workflow.add_edge("sentiment", "combine")
workflow.add_edge("keywords", "combine")
workflow.add_edge("summary", "combine")

workflow.add_edge("combine", "__end__")


async def main():
    text = """
    AgentClaw is a lightweight AI agent framework that makes building
    production-ready agents incredibly simple. With its declarative approach,
    developers can focus on what they want to achieve rather than how to
    implement complex orchestration logic. The framework handles state
    management, streaming, and tool integration automatically.
    """

    print("=== Parallel Analysis Demo ===")
    print(f"Input text: {text[:100]}...")
    print("\nRunning parallel analysis (sentiment, keywords, summary)...")

    import time
    start = time.time()
    result = await workflow.run({"user_input": text})
    elapsed = time.time() - start

    print(f"\n⏱️ Completed in {elapsed:.2f}s (parallel execution)")
    print("\n=== Final Report ===")
    print(result["state"].get("final_report", ""))


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
