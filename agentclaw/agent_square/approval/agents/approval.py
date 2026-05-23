"""
Example 04: Human Review (人工审核)

场景：客服邮件回复审核
1. 用户输入客户投诉内容
2. LLM 自动起草回复邮件
3. 工作流中断，等待人工审核（文本输入）
4. LLM 意图识别路由（add_llm_router）：
   - 有修改意见 → 返回 draft 重新起草（带上修改意见）
   - 没有意见 → LLM 生成确认反馈话术

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, HumanNode, Input

workflow = Workflow(
    id="approval",
    name="04 Human Review",
    description="客服邮件审核：LLM 起草 → 人工审核 → 修改或发送",
    welcome="请输入客户投诉内容，我会起草回复邮件供你审核。",
    inputs=[
        Input("user_input", str, required=True, description="客户投诉内容"),
    ],
    user_input="user_input",
)

# Step 1: LLM 起草回复邮件
workflow.add_node(LLMNode(
    id="draft",
    system_prompt=(
        "根据客户投诉内容，起草一封专业的中文回复邮件。语气诚恳，表达歉意并提出解决方案。\n"
        "如果有审核修改意见，请据此修改：{review_feedback}"
    ),
    output_key="draft_email",
    output_to_user=True,
    save_to_context=False,
))

# Step 2: 人工审核（工作流在此中断，用户输入文本反馈）
workflow.add_node(HumanNode(
    id="review",
    feedback_field="review_feedback",
    save_to_context=True,
))

# Step 3: 审核通过，生成确认反馈话术
workflow.add_node(LLMNode(
    id="finalize",
    system_prompt=(
        "邮件草稿已通过人工审核，确认发送。请生成一段简短的确认反馈话术，告知审核人员邮件已确认发送。\n"
        "包含：确认发送的通知、邮件摘要（一句话）、后续跟进建议。\n\n"
        "已确认的邮件内容：\n{draft_email}"
    ),
    output_key="final_feedback",
    output_to_user=True,
    save_to_context=False,
))

# 边连接
workflow.add_edge("__start__", "draft")
workflow.add_edge("draft", "review")

# LLM 意图识别路由：自动判断用户反馈意图并路由
workflow.add_llm_router(
    after="review",
    routes={
        "approved": "finalize",
        "revise": "draft",
        "default": "draft",
    },
    prompt="判断用户审核意见：满意/没意见/可以发送→approved，有修改意见→revise",
    input_field="review_feedback",
)


async def main():
    thread_id = "approval_demo"

    # Step 1: 提交投诉，生成草稿
    print("=== Step 1: 生成草稿 ===")
    result = await workflow.run(
        {"user_input": "我的订单已经等了两周还没到，客服电话也打不通"},
        thread_id=thread_id,
    )
    print(f"\n草稿:\n{result['state'].get('draft_email', '')}")
    print("\n--- 等待审核 ---")

    # Step 2: 模拟用户审核通过
    print("\n=== Step 2: 用户反馈 ===")
    result = await workflow.resume(thread_id, "没问题")
    state = result.get("state", result) if isinstance(result, dict) else {}
    print(f"\n反馈:\n{state.get('final_feedback', '')}")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
