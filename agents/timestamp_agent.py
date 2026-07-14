"""
timestamp_agent - 端到端验证：调用企业工具 get_timestamp

验证：enterprise-tools MCP server 加载 tools/specs/get_timestamp.yaml
→ workflow 自动加载 mcp.json（_try_load_mcp）
→ LLMNode tools=["get_timestamp"] 引用 → agent 调用工具
"""
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="timestamp_agent",
    name="时间戳助手",
    description="调用 get_timestamp 企业工具获取当前时间戳",
    inputs=[
        Input("user_input", str, required=True, description="用户输入"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="agent",
    system_prompt="你是时间助手。用户询问时间时，调用 get_timestamp 工具获取当前 Unix 时间戳，并告知用户当前时间戳是多少。",
    agent_style="agentic",
    tools=["get_timestamp"],
    output_to_user=True,
))

workflow.publish()
