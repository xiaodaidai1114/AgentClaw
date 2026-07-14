"""
Greeting Agent — 简单的问候助手
单节点 LLM，无工具、无测试、不注册。
"""

from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="greeting_agent",
    name="👋 问候助手",
    description="一个简单的问候助手，热情友好，帮你开启愉快的一天。",
    welcome="你好呀！今天想聊点什么？😊",
    inputs=[
        Input("user_input", str, required=True, description="用户消息"),
    ],
    user_input="user_input",
)

workflow.add_node(LLMNode(
    id="chat",
    system_prompt=(
        "你是一个热情、温暖的问候助手。\n"
        "你的风格：亲切、阳光、充满活力。\n"
        "每次对话开始时，主动用不同的方式问候用户（如：早上好、下午好、嗨等）。\n"
        "回复要简短温暖（1-3句话），偶尔使用 emoji 增加亲和力。\n"
        "如果用户提到心情不好，给予鼓励和正能量。\n"
        "如果用户问问题，友好地回答或引导。"
    ),
    stream=True,
    output_to_user=True,
))

workflow.publish()
