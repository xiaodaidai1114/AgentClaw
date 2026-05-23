"""
Example 03: Tool-Calling Agent
LLM with custom tools for web search, calculations, and weather.

Demonstrates:
- @workflow.tool decorator for registering tools
- Tool calling with tool_choice and max_tool_rounds
- Streaming output

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="tool_agent",
    name="03 Tool Agent",
    description="LLM 工具调用示例：搜索网页、数学计算、天气查询。",
    welcome="🔧 我可以搜索网页、计算数学表达式、查询天气。问我试试！",
    inputs=[
        Input("user_input", str, required=True, description="User query"),
    ],
    user_input="user_input",
)


# ============================================================
# @workflow.tool — 注册自定义工具
#
# 工具函数要求:
#   - 必须有 docstring（LLM 据此理解工具用途）
#   - 参数需要有类型标注（用于生成 JSON Schema）
#   - 支持同步和异步函数
#   - 工具名称 = 函数名（在 LLMNode.tools 中引用）
# ============================================================
@workflow.tool
async def search_web(query: str) -> str:
    """
    Search the web for information.

    Args:
        query: Search query string
    """
    return f"Search results for '{query}': Found 3 relevant articles about {query}."


@workflow.tool
async def calculate(expression: str) -> str:
    """
    Calculate a mathematical expression.

    Args:
        expression: Math expression like "2 + 2" or "sqrt(16)"
    """
    try:
        import math
        allowed = {"__builtins__": {}, "math": math, "sqrt": math.sqrt, "pow": pow}
        result = eval(expression, allowed)
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {e}"


@workflow.tool
async def get_weather(city: str) -> str:
    """
    Get current weather for a city.

    Args:
        city: City name
    """
    return f"Weather in {city}: 22°C, Partly cloudy, Humidity 65%"


# ============================================================
# LLMNode 工具调用参数说明:
#   tools           — 工具名称列表，引用 @workflow.tool 注册的函数名
#                     也可以传 "*" 使用所有已注册工具
#   tool_choice     — 工具调用策略:
#                     "auto"     — LLM 自行决定是否调用工具（默认）
#                     "required" — 强制至少调用一个工具
#                     "none"     — 禁止调用工具
#   max_tool_rounds — 最大工具调用轮数，防止无限循环
#                     None 表示使用环境变量 MAX_TOOL_ROUNDS（默认 0，不限制）
#   stream          — 流式输出，工具调用过程中实时推送中间结果
# ============================================================
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="""You are a helpful assistant with access to tools.
Use tools when needed to answer questions accurately.""",
    tools=["search_web", "calculate", "get_weather"],
    tool_choice="auto",
    max_tool_rounds=3,
    stream=True,
    output_to_user=True,
))


async def main():
    test_queries = [
        "What's the weather in Tokyo?",
        "Calculate 15 * 7 + 23",
        "Search for Python best practices",
    ]

    for query in test_queries:
        print(f"\n=== Query: {query} ===")
        result = await workflow.run({"user_input": query})
        print(f"Response: {result['state'].get('agent', '')[:200]}...")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
