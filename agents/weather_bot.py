from agentclaw import Workflow, LLMNode, Input
workflow = Workflow(
    id="weather_bot",
    name="天气助手",
    description="查询并分析天气的智能助手",
    inputs=[Input("user_input", str, required=True, description="请输入城市名")],
    user_input="user_input",
)
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="你是专业的天气助手。用户问天气时，给出详细、有用的天气描述和建议。用中文回答。",
    enable_memory=True,
    output_to_user=True,
))
workflow.publish()
