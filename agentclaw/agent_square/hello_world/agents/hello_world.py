"""
Example 01: Hello World
Basic LLM call with streaming output and multi-turn chat support.

Multi-turn chat is built-in — just use thread_id to maintain conversation.
No HumanNode required!

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input

# ============================================================
# Workflow 参数说明:
#   id              — 工作流唯一标识符，用于 API 调用和注册
#   name            — 显示名称，Dashboard 和日志中展示
#   welcome         — 前端开场白，新对话时显示（不影响 API 调用）
#   inputs          — 输入参数定义，支持 dict / Input 对象 / Pydantic BaseModel
#   user_input      — 指定哪个输入字段是用户消息（Dashboard 聊天框传入的字段）
# ============================================================
workflow = Workflow(
    id="hello_world",
    name="01 Hello World",
    description="最基础的 LLM 对话示例：单轮问答与多轮对话（thread_id）。",
    welcome="👋 你好！我是一个友好的聊天助手，随便聊点什么吧。",
    inputs=[
        # Input 参数说明:
        #   name        — 字段名，对应 run() 时传入的 key
        #   type        — 字段类型 (str, int, float, bool, list, dict)
        #   required    — 是否必填，默认 False
        #   description — 字段描述，用于 API 文档和前端提示
        Input("user_input", str, required=True, description="User message"),
    ],
    user_input="user_input",
)

# ============================================================
# LLMNode 参数说明:
#   id              — 节点唯一标识，也是输出写入 state 的默认 key
#   system_prompt   — 系统提示词，支持 {变量} 引用 state 中的值
#   stream          — 是否流式输出（SSE），默认 False
#   output_to_user  — 是否将输出发送给前端/用户，LLMNode 默认 False
#
# 上下文相关 (默认行为，此处未显式设置):
#   use_context=True       — 自动加载历史消息，支持多轮对话
#   save_to_context=True   — 将本轮对话写入历史
# ============================================================
workflow.add_node(LLMNode(
    id="chat",
    system_prompt="You are a friendly assistant. Keep responses brief.",
    stream=True,
    output_to_user=True,
))


async def main():
    # === 单轮对话 ===
    print("=== Single Turn ===")
    result = await workflow.run({"user_input": "Hello! What can you do?"})
    print(f"Response: {result['state'].get('chat', '')}")

    # === 多轮对话 ===
    # thread_id 是对话线程标识，相同 thread_id 的调用共享历史消息
    print("\n=== Multi-turn Chat ===")
    thread_id = "demo_session"

    result = await workflow.run(
        {"user_input": "Hi, I'm Alice. I love Python."},
        thread_id=thread_id
    )
    print(f"Turn 1: {result['state'].get('chat', '')}")

    # 第二轮 — LLM 能记住上轮对话内容
    result = await workflow.run(
        {"user_input": "What's my name and what do I like?"},
        thread_id=thread_id
    )
    print(f"Turn 2: {result['state'].get('chat', '')}")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
