"""
Example 09: Advanced LLM Configuration
Fine-tune model selection, parameters, error handling, and context control.

Scenario: Weekly Report Generator
Input bullet points of your work → organized categorization → detailed report → TL;DR summary.

Demonstrates:
- model_params: temperature, max_tokens per node
- Error handling: retry, fallback_model
- Context control: use_context, save_to_context, compression
- Workflow-level timeout and recursion limit

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input
from agentclaw.node.types import ErrorStrategy

# ============================================================
# Workflow 高级参数:
#   timeout          — 超时秒数，默认 300
#   recursion_limit  — 递归上限，默认 50（防止条件边无限循环）
#   tracing          — 启用执行追踪（Dashboard /traces 查看），默认 True
#   cancel_on_disconnect — 客户端断开时取消执行，默认 True
#   models_config    — 模型配置文件路径，None 自动查找 ./models.json
# ============================================================
workflow = Workflow(
    id="weekly_report",
    name="09 周报生成器",
    description="输入工作要点，自动生成分类整理、详细周报和一句话摘要。",
    welcome="📝 列出你本周做了什么（每行一条），我帮你生成周报。",
    timeout=120,
    recursion_limit=30,
    inputs=[
        Input("user_input", str, required=True, description="工作要点（每行一条）"),
    ],
    user_input="user_input",
)


# ============================================================
# 节点 1: 整理分类 — 低温度 + 结构化输出
#
# model_params 常用参数:
#   temperature  — 0.0 确定性，1.0 创造性
#   max_tokens   — 最大输出 token 数
#   top_p        — 核采样参数
#   stop         — 停止词列表
#
# model_id     — 指定模型（对应 models.json 中的配置），None 使用默认模型
# output_format — "text"(默认) / "json" (强制 JSON 输出)
# save_to_context — 是否写入对话历史，False 避免污染后续节点
# ============================================================
workflow.add_node(LLMNode(
    id="organize",
    description="整理分类",
    system_prompt="""将用户的工作要点按以下类别整理，每条保持简洁:
- 项目进展
- 技术工作
- 协作沟通
- 其他

如果某个类别没有内容则省略。直接输出整理结果，不要添加额外说明。""",
    user_prompt="{user_input}",
    model_params={"temperature": 0.1, "max_tokens": 500},
    save_to_context=False,  # 中间结果，不写入对话历史
))


# ============================================================
# 节点 2: 撰写周报 — 高 token + 流式输出 + 错误重试
#
# 错误处理参数 (继承自 BaseNode):
#   on_error       — ABORT(终止) / RETRY(重试) / SKIP(跳过) / FALLBACK(降级)
#   max_retries    — 最大重试次数（RETRY 策略），默认 3
#   retry_delay    — 重试间隔秒数（指数退避），默认 1.0
#
# 模型降级参数 (LLMNode 特有):
#   fallback_model_id  — 主模型失败时自动切换的备用模型
#   auto_fallback      — 是否启用自动降级，None 使用全局配置
# ============================================================
workflow.add_node(LLMNode(
    id="write_report",
    description="撰写周报正文",
    system_prompt="""你是一位专业的技术团队成员。根据整理好的工作分类，撰写一份正式的周报。

要求:
- 使用 Markdown 格式
- 每个类别作为二级标题
- 语言简练专业，突出成果和进展
- 末尾加上"下周计划"（根据本周内容合理推测）

整理后的工作分类:
{organize}""",
    user_prompt="原始工作要点: {user_input}",
    model_params={"temperature": 0.5, "max_tokens": 2048},
    on_error=ErrorStrategy.RETRY,
    max_retries=2,
    retry_delay=2.0,
    stream=True,
    output_to_user=True,
))


# ============================================================
# 节点 3: 一句话摘要 — 独立上下文 + 低 token
#
# 上下文控制参数:
#   use_context          — 是否加载历史消息，默认 True
#                          False 则每次调用是全新对话（无历史）
#   save_to_context      — 是否将本轮对话写入历史，默认 True
#   max_context_messages — 最大历史条数，None 使用全局配置
#
# 上下文压缩参数:
#   enable_compression     — 是否启用上下文压缩，默认 True
#   compression_threshold  — 压缩阈值 (token 数)，超过时用 LLM 压缩历史
#   compression_model      — 压缩用的模型，None 使用默认模型
# ============================================================
workflow.add_node(LLMNode(
    id="tldr",
    description="生成一句话摘要",
    system_prompt="将以下周报浓缩为一句话摘要（不超过 30 字），概括本周核心成果。直接输出摘要。",
    user_prompt="{write_report}",
    use_context=False,      # 独立调用，不需要历史
    save_to_context=False,  # 摘要不污染对话历史
    enable_compression=False,
    model_params={"temperature": 0.2, "max_tokens": 100},
    output_to_user=True,
))

workflow.add_edge("__start__", "organize")
workflow.add_edge("organize", "write_report")
workflow.add_edge("write_report", "tldr")


async def main():
    print("=== Example 09: Weekly Report Generator ===\n")

    result = await workflow.run({
        "user_input": """完成用户认证模块的 JWT 重构
修复了 3 个生产环境 bug
和前端团队对接了新版 API 接口
参加了架构评审会议
写了单元测试，覆盖率从 62% 提到 78%
Review 了两个同事的 PR""",
    })

    state = result["state"]
    print(f"\nTL;DR: {state.get('tldr', '')}")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
