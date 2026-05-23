"""
Example 08: Custom Nodes
@workflow.node() decorator and CustomNode class for injecting Python logic.

Custom nodes handle deterministic processing that doesn't need LLM:
data parsing, validation, formatting, external API calls, business rules, etc.

Demonstrates:
- @workflow.node() — function-based custom node (decorator)
- CustomNode class — class-based custom node (configurable, reusable)
- condition — conditional node execution
- ErrorStrategy — error handling (ABORT / RETRY / SKIP / FALLBACK)

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
import re
from agentclaw import Workflow, LLMNode, CustomNode, Input
from agentclaw.node.types import ErrorStrategy


workflow = Workflow(
    id="custom_demo",
    name="08 数据报告生成器",
    description="自定义节点示例：数据解析 → LLM 分析 → 格式化报告。",
    welcome="📊 输入一组数据（如业绩评分、销售额等），我来分析并生成报告。",
    inputs=[
        Input("user_input", str, required=True, description="待分析的数据文本"),
        Input("report_title", str, default="数据分析报告", description="报告标题"),
    ],
    user_input="user_input",
)


# ============================================================
# 方式 1: @workflow.node() 装饰器
#
# 将普通 Python 函数注册为工作流节点
# 适合一次性的数据处理逻辑
#
# 参数:
#   id            — 节点 ID（默认使用函数名）
#   description   — 节点描述（Dashboard 展示用）
#   on_error      — 错误策略: ABORT / RETRY / SKIP / FALLBACK
#   max_retries   — 最大重试次数（RETRY 策略）
#   fallback_value — 降级返回值（FALLBACK 策略）
#   condition     — 条件函数 (state) -> bool，返回 False 时跳过
#
# 函数签名: def func(state) -> dict | None
#   返回 dict → 合并到 state
#   返回 None → state 不变
# ============================================================
@workflow.node(
    id="parse_data",
    description="解析输入数据，提取数值并计算统计",
    on_error=ErrorStrategy.FALLBACK,
    fallback_value={"numbers": [], "stats": "无法解析数据"},
)
def parse_data(state):
    """从用户输入中提取数值并计算基础统计"""
    text = state.get("user_input", "")

    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", text)]

    if not numbers:
        return {"numbers": [], "stats": "未找到数值数据"}

    return {
        "numbers": numbers,
        "stats": {
            "count": len(numbers),
            "sum": sum(numbers),
            "avg": round(sum(numbers) / len(numbers), 2),
            "max": max(numbers),
            "min": min(numbers),
        },
    }


# LLM 分析节点 — 基于自定义节点提取的结构化数据生成洞察
workflow.add_node(LLMNode(
    id="analyze",
    system_prompt="""你是数据分析师。根据以下统计结果给出简要分析（2-3 句话）:

统计: {stats}
原始数据: {numbers}""",
    user_prompt="{user_input}",
    output_key="analysis",
    output_to_user=True,
    stream=True,
))


# ============================================================
# 方式 2: CustomNode 类
#
# 继承 CustomNode，实现 process(**state) 方法
# 适合封装可复用的业务逻辑，支持通过构造参数注入配置
#
# process() 接收 state 中所有字段作为关键字参数
# 返回 dict → 合并到 state
# ============================================================
class ReportNode(CustomNode):
    """生成格式化报告 — 可配置分隔符和宽度"""

    def __init__(self, separator: str = "─", width: int = 40, **kwargs):
        super().__init__(**kwargs)
        self.separator = separator
        self.width = width

    def process(self, report_title="报告", stats=None, analysis="", **_):
        line = self.separator * self.width

        if isinstance(stats, dict):
            summary = (
                f"数量: {stats['count']}  |  总计: {stats['sum']}  |  均值: {stats['avg']}\n"
                f"最大: {stats['max']}  |  最小: {stats['min']}"
            )
        else:
            summary = str(stats or "无数据")

        return {
            "report": f"\n{line}\n  {report_title}\n{line}\n\n{summary}\n\n{analysis}\n\n{line}",
        }


workflow.add_node(ReportNode(
    id="report",
    description="生成格式化报告",
    output_to_user=True,
    separator="═",
    width=36,
    # 仅在成功解析出数据时生成报告
    condition=lambda state: bool(state.get("numbers")),
))

workflow.add_edge("__start__", "parse_data")
workflow.add_edge("parse_data", "analyze")
workflow.add_edge("analyze", "report")


async def main():
    print("=== Example 08: Custom Nodes ===\n")

    result = await workflow.run({
        "user_input": "本月各部门业绩评分: 市场部 85, 研发部 92, 销售部 78, 运营部 96, 客服部 88",
        "report_title": "部门月度评估报告",
    })
    print(result["state"].get("report", ""))


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
