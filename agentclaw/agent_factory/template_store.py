"""
Enterprise Template Store - 企业 Agent 模板存储

Phase 2 内置 general + sales 两个模板（让「不同领域匹配不同模板」可验收）。
Phase 3 会把完整 9 个领域模板放到 templates/enterprise_agents/*.yaml，
TemplateStore 扫描加载后自动覆盖内置模板。

模板字段与 Phase 3 YAML 结构一致。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .blueprint import (
    AgentDomain,
    SkillSpec,
    ToolSpec,
    WorkflowStep,
    KnowledgeSourceSpec,
)


class EnterpriseTemplate(BaseModel):
    """企业 Agent 模板"""
    domain: str
    display_name: str
    description: str = ""
    default_role: str = ""
    default_goals: List[str] = Field(default_factory=list)
    default_responsibilities: List[str] = Field(default_factory=list)
    default_skills: List[SkillSpec] = Field(default_factory=list)
    default_tools: List[ToolSpec] = Field(default_factory=list)
    default_workflow: List[WorkflowStep] = Field(default_factory=list)
    default_guardrails: List[str] = Field(default_factory=list)
    recommended_knowledge_sources: List[KnowledgeSourceSpec] = Field(default_factory=list)
    evaluation_metrics: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# 内置模板（Phase 2 最小集；Phase 3 的 YAML 会覆盖/扩展）
# ------------------------------------------------------------------

BUILTIN_TEMPLATES: Dict[str, EnterpriseTemplate] = {
    AgentDomain.GENERAL: EnterpriseTemplate(
        domain=AgentDomain.GENERAL,
        display_name="通用助手",
        description="一个可运行的通用智能体雏形，作为无匹配领域时的兜底模板",
        default_role="通用 AI 助手",
        default_goals=["理解用户需求并给出有帮助的回答", "必要时调用工具完成任务"],
        default_responsibilities=["响应用户提问", "调用必要工具", "生成清晰回复"],
        default_skills=[],
        default_tools=[],
        default_workflow=[
            WorkflowStep(step_id="chat", name="对话", input="user_input", output="response"),
        ],
        default_guardrails=["遵守企业安全策略", "不泄露敏感信息", "不确定时如实说明"],
        recommended_knowledge_sources=[],
        evaluation_metrics=["task_success_rate", "human_feedback_score"],
    ),
    AgentDomain.SALES: EnterpriseTemplate(
        domain=AgentDomain.SALES,
        display_name="销售分析助手",
        description="分析销售线索、给出跟进优先级、识别高价值客户的销售智能体",
        default_role="销售线索分析师",
        default_goals=["分析销售线索", "给出跟进优先级", "识别高价值客户"],
        default_responsibilities=["线索评分", "客户分析", "跟进建议", "报告生成"],
        default_skills=[
            SkillSpec(name="lead_scoring", description="线索评分", type="builtin",
                      source="builtin", confidence=0.7),
        ],
        default_tools=[
            ToolSpec(name="crm_query", description="查询 CRM 客户与线索数据",
                     permission_level="read_only"),
        ],
        default_workflow=[
            WorkflowStep(step_id="collect", name="收集线索", input="user_input",
                         output="leads", tools=["crm_query"]),
            WorkflowStep(step_id="analyze", name="分析评分", input="leads",
                         output="scored_leads", skills=["lead_scoring"]),
            WorkflowStep(step_id="report", name="生成建议", input="scored_leads",
                         output="followup_advice"),
        ],
        default_guardrails=["不泄露客户隐私", "仅处理脱敏后的线索数据", "高价值判定需人工复核"],
        recommended_knowledge_sources=[
            KnowledgeSourceSpec(name="product_kb", type="knowledge_base",
                                description="产品知识库"),
        ],
        evaluation_metrics=["task_success_rate", "human_feedback_score", "correction_rate"],
    ),
    AgentDomain.CUSTOMER_SUPPORT: EnterpriseTemplate(
        domain=AgentDomain.CUSTOMER_SUPPORT,
        display_name="客服助手",
        description="识别用户意图、分类工单、给出回复建议的客服智能体",
        default_role="客户支持专员",
        default_goals=["识别用户意图", "分类工单", "给出回复建议"],
        default_responsibilities=["意图识别", "工单分类", "回复建议", "情绪安抚"],
        default_skills=[
            SkillSpec(name="intent_classification", description="意图分类",
                      type="builtin", source="builtin", confidence=0.7),
        ],
        default_tools=[
            ToolSpec(name="ticket_search", description="查询历史工单",
                     permission_level="read_only"),
        ],
        default_workflow=[
            WorkflowStep(step_id="classify", name="意图分类", input="user_input",
                         output="intent", skills=["intent_classification"]),
            WorkflowStep(step_id="draft", name="起草回复", input="intent",
                         output="reply"),
        ],
        default_guardrails=["不承诺超出政策范围的补偿", "敏感投诉转人工"],
        recommended_knowledge_sources=[
            KnowledgeSourceSpec(name="support_kb", type="knowledge_base",
                                description="客服知识库"),
        ],
        evaluation_metrics=["task_success_rate", "human_feedback_score", "fallback_rate"],
    ),
}


class TemplateStore:
    """模板存储：内置模板 + 可选的外部目录扫描（Phase 3）"""

    def __init__(self, templates_dir: Optional[Path] = None) -> None:
        self._templates: Dict[str, EnterpriseTemplate] = dict(BUILTIN_TEMPLATES)
        self._templates_dir = templates_dir
        if templates_dir and Path(templates_dir).exists():
            self._load_from_dir(Path(templates_dir))

    def _load_from_dir(self, dir_path: Path) -> None:
        """从 templates/enterprise_agents/ 加载 YAML 模板，覆盖内置同名 domain"""
        try:
            import yaml  # type: ignore
        except ImportError:
            return
        for yaml_file in sorted(dir_path.glob("*.y*ml")):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("domain"):
                    tpl = EnterpriseTemplate.model_validate(data)
                    self._templates[tpl.domain] = tpl
            except Exception:
                # 模板加载失败不应影响主流程，跳过单个坏模板
                continue

    def get(self, domain: str) -> Optional[EnterpriseTemplate]:
        return self._templates.get(domain)

    def list_all(self) -> List[EnterpriseTemplate]:
        return list(self._templates.values())

    def has(self, domain: str) -> bool:
        return domain in self._templates
