"""
示例工作流 - Hello World
"""

from agentclaw import Workflow, LLMNode, Input

# 创建工作流
workflow = Workflow(
    id="hello_world",
    name="Hello World",
    description="一个简单的问候工作流",
    inputs=[
        Input("user_input", str, required=True, description="请输入想让助手回答的内容"),
    ],
    user_input="user_input",
)

# 添加 LLM 节点
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是一个友好的助手，用简洁的语言回答问题。",
    enable_memory=True,
    output_to_user=True,
))

# 发布工作流
workflow.publish()
