"""
Example 06: Skills Integration
Use skills to inject domain knowledge into LLM.

Skills are markdown files (SKILL.md) containing domain expertise.
AgentClaw auto-loads them from ./skills/ — no manual configuration needed.
This example uses the slack-gif-creator skill included in ./skills/

Demonstrates:
- Explicit skill selection: skills=["skill-name"]
- Wildcard auto-matching: skills="*"
- Agent mode with builtin tools

Run:
    agentclaw up  # or: agentclaw serve
"""

import asyncio
from agentclaw import Workflow, LLMNode, Input

# ============================================================
# Skills 自动发现:
#   框架自动从 ./skills/ 目录加载技能，无需手动配置 skills_dir
#   每个技能是一个文件夹，包含 SKILL.md（带 YAML frontmatter）
#   如需指定其他路径，可设置 skills_dir="path/to/skills"
# ============================================================
workflow = Workflow(
    id="gif_agent",
    name="06A GIF Creator Agent",
    description="技能注入示例：通过 SKILL.md 向 LLM 注入领域知识，辅助创建 Slack 动画表情。",
    welcome="🎨 我可以帮你创建 Slack 动画表情，告诉我你想做什么样的 GIF！",
    inputs=[
        Input("user_input", str, required=True, description="User request"),
    ],
    user_input="user_input",
)

# ============================================================
# LLMNode 技能参数说明:
#   skills              — 技能列表或 "*" 通配符
#                         列表: ["slack-gif-creator"] — 显式指定技能名
#                         "*": 根据用户输入自动匹配相关技能
#   enable_builtin_skills — 是否启用内置技能（agent_creator, coding_skill）
#                           默认 False，仅使用项目 skills/ 中的技能
#   enable_builtin_tools  — 是否启用内置工具（skill-tools 提供的 python, shell,
#                           read_file, write_file 等），默认 False
#   agent_style           — Agent 风格:
#                           "default"  — 标准模式，适合简单问答（默认）
#                           "agentic" — 增强模式，注入 Agent 增强提示词，
#                                       适合需要多步骤推理和工具调用的场景
# ============================================================
workflow.add_node(LLMNode(
    id="agent",
    system_prompt="""You are a creative assistant that helps users create animated GIFs for Slack.
Use the slack-gif-creator skill to understand Slack's requirements and create optimized GIFs.""",
    skills=["slack-gif-creator"],
    stream=True,
    output_to_user=True,
    enable_builtin_tools=True,
    agent_style="agentic",
))


async def main():
    print("=== Skills Demo ===\n")

    result = await workflow.run({
        "user_input": "How do I create a bouncing ball GIF for Slack emoji?"
    })
    print(f"Response: {result['state'].get('agent', '')[:500]}...")


workflow.publish()


if __name__ == "__main__":
    asyncio.run(main())
