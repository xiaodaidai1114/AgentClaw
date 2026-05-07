"""
Example 07: MCP Integration
Use service-published MCP tools from examples/mcps/example_tools.py.
Also use the external fetch MCP server configured in mcp.json.

Demonstrates:
- Reusing service-published MCP tools in LLMNode
- Combining service-published tools and external MCP tools in one node

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio

from agentclaw import Workflow, LLMNode, Input


workflow = Workflow(
    id="mcp_agent",
    name="07 MCP Agent",
    description="调用注册到 AgentClaw 服务的 MCP 示例工具，完成文本分析与 Markdown 报告生成。",
    welcome="🔌 我可以调用服务内注册的 MCP 工具，帮你分析文本并生成 Markdown 报告。",
    inputs=[
        Input("user_input", str, required=True, description="User request"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="""You are a helpful assistant with access to MCP tools.

Use analyze_text before giving conclusions about user-provided text.
Use build_markdown_report when the user asks for a Markdown report or structured summary.
Use fetch when the user asks you to read, inspect, or summarize a URL.
Explain briefly which MCP tool you used and include the final result in Chinese unless the user asks otherwise.""",
    tools=["analyze_text", "build_markdown_report", "fetch"],
    tool_choice="auto",
    max_tool_rounds=3,
    stream=True,
    output_to_user=True,
))


async def main():
    print("=== Example 07: MCP Integration ===")
    print("MCP (Model Context Protocol) 让工具能力通过服务端点复用")
    print("本示例调用服务内注册的 analyze_text / build_markdown_report 工具")
    print("同时也可以调用 mcp.json 中配置的 fetch 工具读取 URL\n")

    print("--- 分析文本并生成报告 ---")
    result = await workflow.run({
        "user_input": (
            "请分析这段运维记录并生成 Markdown 报告："
            "凌晨任务执行失败，出现 timeout 和 permission denied，"
            "部分用户同步延迟，需要给出风险等级和处理建议。"
        )
    })
    print(f"\nResponse: {result['state'].get('agent', '')}")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
