"""
Blueprint Generator - 综合「需求 + 领域 + 模板」生成 AgentBlueprint

输入：RequirementAnalysis + domain + EnterpriseTemplate
输出：AgentBlueprint（v0.1 雏形）

模板提供默认骨架，需求覆盖/补充关键字段。生成物不要求完美，
后续通过 Skill Evolution 持续增强。
"""

from __future__ import annotations

from .blueprint import (
    AgentBlueprint,
    AgentStatus,
    DEFAULT_VERSION,
    MemorySpec,
)
from .requirement_analyzer import RequirementAnalysis
from .template_store import EnterpriseTemplate


class BlueprintGenerator:
    """从需求 + 模板生成 AgentBlueprint"""

    def generate(
        self,
        requirement: RequirementAnalysis,
        domain: str,
        template: EnterpriseTemplate,
    ) -> AgentBlueprint:
        name = self._ensure_valid_name(requirement.agent_name)

        # goals 以模板为骨架
        goals = list(template.default_goals)
        # responsibilities 以模板为骨架，补充需求中显式提到的能力
        responsibilities = list(template.default_responsibilities)
        for cap in requirement.required_capabilities:
            if cap not in responsibilities:
                responsibilities.append(cap)

        description = requirement.business_goal or template.description

        blueprint = AgentBlueprint(
            name=name,
            display_name=template.display_name or name,
            description=description,
            domain=domain,
            role=template.default_role or "AI 助手",
            goals=goals,
            responsibilities=responsibilities,
            inputs=self._derive_inputs(template),
            outputs=self._derive_outputs(template),
            skills=list(template.default_skills),
            tools=list(template.default_tools),
            knowledge_sources=list(template.recommended_knowledge_sources),
            memory=MemorySpec(type="workflow", persist=True, description="工作流级长期记忆"),
            workflow=list(template.default_workflow),
            constraints=[],
            guardrails=list(template.default_guardrails),
            version=DEFAULT_VERSION,
            status=AgentStatus.DRAFT,
        )
        return blueprint

    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_valid_name(name: str) -> str:
        """确保 name 是合法 Python 标识符（用作 Workflow.id 与模块名）"""
        import re

        cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name or "").strip("_")
        cleaned = re.sub(r"_+", "_", cleaned)
        if not cleaned:
            cleaned = "agent"
        if cleaned[0].isdigit():
            cleaned = f"agent_{cleaned}"
        return cleaned

    @staticmethod
    def _derive_inputs(template: EnterpriseTemplate) -> list[str]:
        inputs = [step.input for step in template.default_workflow if step.input]
        if not inputs:
            inputs = ["user_input"]
        # 去重保序
        seen, result = set(), []
        for i in inputs:
            if i not in seen:
                seen.add(i)
                result.append(i)
        return result

    @staticmethod
    def _derive_outputs(template: EnterpriseTemplate) -> list[str]:
        outputs = [step.output for step in template.default_workflow if step.output]
        if not outputs:
            outputs = ["response"]
        seen, result = set(), []
        for o in outputs:
            if o not in seen:
                seen.add(o)
                result.append(o)
        return result
