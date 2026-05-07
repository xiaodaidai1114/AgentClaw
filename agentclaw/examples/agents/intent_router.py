"""
Example 02: Intent Router
Classify user intent and route to different handlers.

Demonstrates:
- Conditional routing with add_router()
- JSON output format for structured classification
- user_prompt template (explicit user message control)
- Stateless nodes (save_to_context=False)

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input

workflow = Workflow(
    id="router",
    name="02 Intent Router",
    description="自动识别用户意图（提问/投诉/打招呼），路由到对应处理节点。",
    welcome="🔀 我会自动识别你的意图（提问/投诉/打招呼）并分配给对应的处理节点。试试看！",
    inputs=[
        Input("user_input", str, required=True, description="User message to classify"),
    ],
    user_input="user_input",
)

# ============================================================
# 分类节点 — 使用 user_prompt 显式控制用户消息
#
# LLMNode Prompt 参数说明:
#   system_prompt   — 系统提示词，定义 LLM 的角色和规则
#                     支持 {变量} 引用 state 中的值
#                     支持 {@prompt_key} 引用 PromptManager 中的提示词
#   user_prompt     — 用户消息模板，默认 None
#                     None: 自动使用 user_input 字段作为用户消息
#                     设置后: 用模板替代原始用户输入，{变量} 从 state 取值
#                     适合需要对用户输入做包装/格式化的场景
#   output_format   — 输出格式: "text" (默认) 或 "json"
#                     json 模式下 LLM 返回合法 JSON，自动解析为 dict 存入 state
#   save_to_context — 是否将本轮对话写入历史，默认 True
#                     分类/判断节点建议设为 False，避免污染对话历史
# ============================================================
workflow.add_node(LLMNode(
    id="classify",
    system_prompt="""You are an intent classifier. Classify the intent as one of:
- question: user is asking a question
- complaint: user is making a complaint
- greeting: user is greeting

Output JSON only with the intent field.""",
    user_prompt="Classify this message: {user_input}",
    output_format="json",
    save_to_context=False,
))

# ============================================================
# 处理节点
#
# output_to_user  — 设为 True，将 LLM 回复发送给前端用户
#                   LLMNode 默认为 False（区别于 BaseNode 默认 True）
# ============================================================
workflow.add_node(LLMNode(
    id="answer",
    system_prompt="Answer the user's question helpfully and concisely.",
    output_to_user=True,
))

workflow.add_node(LLMNode(
    id="handle_complaint",
    system_prompt="The user has a complaint. Apologize sincerely and offer to help.",
    output_to_user=True,
))

workflow.add_node(LLMNode(
    id="greet",
    system_prompt="Respond with a friendly, brief greeting.",
    output_to_user=True,
))

# ============================================================
# add_router 参数说明:
#   after     — 路由源节点 ID，路由在该节点执行完后触发
#   routes    — 路由映射 {条件值: 目标节点ID}
#               支持 "default" 作为兜底路由（当条件值不匹配任何 key 时）
#   condition — 条件函数，接收 state dict，返回路由 key (字符串)
#               也可以传字段名字符串（支持嵌套访问如 "classify.intent"）
# ============================================================
workflow.add_router(
    after="classify",
    routes={
        "question": "answer",
        "complaint": "handle_complaint",
        "greeting": "greet",
        "default": "answer",
    },
    condition="classify.intent",
)


async def main():
    test_inputs = [
        "What is the capital of France?",
        "Your service is terrible!",
        "Hello there!",
    ]

    for user_input in test_inputs:
        print(f"\n=== Input: {user_input} ===")
        result = await workflow.run({"user_input": user_input})

        state = result["state"]
        for key in ["answer", "handle_complaint", "greet"]:
            if key in state and state[key]:
                print(f"Handler: {key}")
                print(f"Response: {state[key]}")
                break


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
