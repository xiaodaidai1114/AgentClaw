import pytest

from agentclaw import Input, Workflow
from agentclaw.api.registry import WorkflowRegistry
from agentclaw.api.builtin_agent import _compact_text
from agentclaw.graph.context import WorkflowContext
from agentclaw.node.llm import LLMNode
from agentclaw.skills import get_builtin_skills_dir
from agentclaw.skills.parser import SkillParser


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_agentic_prompt_injects_registered_workflow_capabilities():
    WorkflowRegistry.clear()
    try:
        WorkflowRegistry.register(Workflow(
            id="system_log_audit",
            name="System Log Audit",
            description="根据用户指定日期审查系统日志并生成 Markdown 审计报告。",
            inputs=[
                Input("user_input", str, required=False, description="Optional user note"),
                Input("audit_date", str, required=False, description="审计日期，格式 YYYY-MM-DD，默认当天"),
                Input("start_time", str, required=False, description="起始时间，ISO 或 YYYY-MM-DD HH:MM:SS"),
                Input("end_time", str, required=False, description="结束时间，ISO 或 YYYY-MM-DD HH:MM:SS"),
            ],
        ))
        WorkflowRegistry.register(Workflow(
            id="__builtin__",
            name="AgentClaw",
            description="内置智能体入口。",
        ), require_auth=False)

        node = LLMNode(
            id="agent",
            system_prompt="You are AgentClaw.",
            agent_style="agentic",
        )

        prompt = await node._resolve_prompt(
            {"user_input": "帮我生成2026-04-26的审计报告"},
            WorkflowContext(workflow_id="__builtin__", workflow_name="AgentClaw"),
        )

        assert "<agentclaw_workflow_capabilities>" in prompt
        assert "id: system_log_audit" in prompt
        assert "name: System Log Audit" in prompt
        assert "根据用户指定日期审查系统日志并生成 Markdown 审计报告。" in prompt
        assert "inputs:" in prompt
        assert "audit_date: string, optional, description=审计日期，格式 YYYY-MM-DD，默认当天" in prompt
        assert "start_time: string, optional, description=起始时间，ISO 或 YYYY-MM-DD HH:MM:SS" in prompt
        assert "end_time: string, optional, description=结束时间，ISO 或 YYYY-MM-DD HH:MM:SS" in prompt
        assert "id: __builtin__" not in prompt
        assert "use `agentclaw_api`" in prompt
        assert "`/_internal/*`" in prompt
        assert "Do not search source code or README" in prompt
    finally:
        WorkflowRegistry.clear()


def test_builtin_skill_descriptions_keep_high_level_operational_boundaries():
    skills_dir = get_builtin_skills_dir()

    api_skill = SkillParser.parse(skills_dir / "agentclaw_api")
    coding_skill = SkillParser.parse(skills_dir / "coding_skill")
    creator_skill = SkillParser.parse(skills_dir / "agent_creator")
    skill_creator = SkillParser.parse(skills_dir / "skill_creator")
    clawhub = SkillParser.parse(skills_dir / "clawhub")

    assert api_skill.description.startswith("Run existing workflows via local /_internal/* relay")
    assert "relay handles internal authentication" in api_skill.description
    assert "workflow/agent execution" in api_skill.description

    assert coding_skill.description.startswith("Inspect, edit, test, refactor, and validate project code")
    assert "source search" in coding_skill.description
    assert creator_skill.description.startswith("Create or modify AgentClaw workflows and agents")
    assert "workflow architecture" in creator_skill.description
    assert skill_creator.description.startswith("Create or modify AgentClaw skill packages")
    assert "trigger descriptions" in skill_creator.description
    assert clawhub.description.startswith("Use the ClawHub CLI")

    for skill in [api_skill, coding_skill, creator_skill, skill_creator, clawhub]:
        desc_lower = skill.description.lower()
        assert "do not" not in desc_lower
        assert "don't" not in desc_lower
        assert "not run" not in desc_lower


def test_builtin_skill_routing_terms_survive_compact_description_preview():
    skills_dir = get_builtin_skills_dir()

    api_preview = _compact_text(SkillParser.parse(skills_dir / "agentclaw_api").description, 72)
    coding_preview = _compact_text(SkillParser.parse(skills_dir / "coding_skill").description, 72)
    creator_preview = _compact_text(SkillParser.parse(skills_dir / "agent_creator").description, 72)

    assert "Run existing workflows" in api_preview
    assert "/_internal/* relay" in api_preview
    assert "Inspect" in coding_preview
    assert "edit" in coding_preview
    assert "test" in coding_preview
    assert "Create or modify" in creator_preview
    assert "workflows and agents" in creator_preview


@pytest.mark.asyncio
async def test_agentic_prompt_skips_workflows_with_capability_injection_disabled():
    WorkflowRegistry.clear()
    try:
        WorkflowRegistry.register(Workflow(
            id="visible_report",
            name="Visible Report",
            description="可被内置智能体复用的报告工作流。",
            inputs=[Input("report_date", str, required=True, description="报告日期")],
        ))
        WorkflowRegistry.register(Workflow(
            id="hidden_report",
            name="Hidden Report",
            description="不应注入内置智能体提示词的内部工作流。",
            inputs=[Input("report_date", str, required=True, description="报告日期")],
            inject_as_agentic_capability=False,
        ))

        node = LLMNode(
            id="agent",
            system_prompt="You are AgentClaw.",
            agent_style="agentic",
        )

        prompt = await node._resolve_prompt(
            {"user_input": "生成报告"},
            WorkflowContext(workflow_id="__builtin__", workflow_name="AgentClaw"),
        )

        assert "id: visible_report" in prompt
        assert "report_date: string, required, description=报告日期" in prompt
        assert "id: hidden_report" not in prompt
        assert "Hidden Report" not in prompt
    finally:
        WorkflowRegistry.clear()
