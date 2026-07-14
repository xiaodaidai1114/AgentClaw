"""
企业模板系统测试（Phase 3）

验证：
- templates/enterprise_agents/ 下 9 个 YAML
- TemplateStore 加载全部 9 个 domain
- TemplateMatcher 各 domain 匹配对应模板，未知 domain 兜底 general
- 外部 YAML 覆盖内置 sales/customer_support/general
- 每个 YAML 必填字段齐全
- generate_agent 项目根解析能找到模板目录
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentclaw.agent_factory.template_store import TemplateStore
from agentclaw.agent_factory.template_matcher import TemplateMatcher
from agentclaw.agent_factory.blueprint import AgentDomain


pytestmark = pytest.mark.unit

# 项目根（d:\agentclaw\AgentClaw）下的 templates/enterprise_agents/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "enterprise_agents"

ALL_DOMAINS = [
    AgentDomain.CUSTOMER_SUPPORT,
    AgentDomain.SALES,
    AgentDomain.FINANCE,
    AgentDomain.HR,
    AgentDomain.PROCUREMENT,
    AgentDomain.LEGAL,
    AgentDomain.KNOWLEDGE_BASE,
    AgentDomain.OPERATIONS,
    AgentDomain.GENERAL,
]


def test_templates_dir_has_9_yaml():
    files = sorted(TEMPLATES_DIR.glob("*.y*ml"))
    assert len(files) == 9, (
        f"期望 9 个 YAML，实际 {len(files)}: {[f.name for f in files]}"
    )


def test_all_9_domains_loaded():
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    loaded = {t.domain for t in store.list_all()}
    missing = [d for d in ALL_DOMAINS if d not in loaded]
    assert not missing, f"缺失 domain: {missing}"


def test_match_each_domain_returns_correct_template():
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    matcher = TemplateMatcher(store)
    for domain in ALL_DOMAINS:
        tpl = matcher.match(domain)
        assert tpl is not None, f"match({domain!r}) 返回 None"
        assert tpl.domain == domain, f"match({domain!r}) 返回了 {tpl.domain!r}"


def test_match_unknown_domain_falls_back_to_general():
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    matcher = TemplateMatcher(store)
    tpl = matcher.match("nonexistent_domain_xyz")
    assert tpl is not None
    assert tpl.domain == AgentDomain.GENERAL


def test_external_yaml_overrides_builtin():
    """外部 YAML 覆盖内置 sales / customer_support / general"""
    builtin = TemplateStore()  # 不加载外部目录
    external = TemplateStore(templates_dir=TEMPLATES_DIR)

    # sales：外部版新增 enrich_company 工具（内置只有 crm_query）
    ext_sales_tools = {t.name for t in external.get(AgentDomain.SALES).default_tools}
    assert "enrich_company" in ext_sales_tools, "外部 sales 模板未覆盖内置"

    # customer_support：外部版新增 sentiment_analysis 技能（内置只有 intent_classification）
    ext_cs_skills = {s.name for s in external.get(AgentDomain.CUSTOMER_SUPPORT).default_skills}
    assert "sentiment_analysis" in ext_cs_skills, "外部 customer_support 未覆盖内置"

    # general：外部版 display_name 为「通用助手」
    assert external.get(AgentDomain.GENERAL).display_name == "通用助手"
    # 确认外部加载后内置被替换（指针不同）
    assert external.get(AgentDomain.SALES) is not builtin.get(AgentDomain.SALES)


def test_every_template_has_required_fields():
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    for tpl in store.list_all():
        assert tpl.domain, "模板缺 domain"
        assert tpl.display_name, f"{tpl.domain} 缺 display_name"
        assert tpl.default_role, f"{tpl.domain} 缺 default_role"
        assert tpl.default_workflow, f"{tpl.domain} 缺 default_workflow"
        assert tpl.default_guardrails, f"{tpl.domain} 缺 default_guardrails"
        assert tpl.evaluation_metrics, f"{tpl.domain} 缺 evaluation_metrics"


def test_workflow_steps_have_step_id_and_name():
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    for tpl in store.list_all():
        ids = set()
        for step in tpl.default_workflow:
            assert step.step_id, f"{tpl.domain} workflow step 缺 step_id"
            assert step.name, f"{tpl.domain} workflow step 缺 name"
            assert step.step_id not in ids, f"{tpl.domain} workflow step_id 重复: {step.step_id}"
            ids.add(step.step_id)


def test_enterprise_templates_have_domain_specific_tools():
    """企业模板应配置领域专属工具（非空，除 general 兜底外）"""
    store = TemplateStore(templates_dir=TEMPLATES_DIR)
    for tpl in store.list_all():
        if tpl.domain == AgentDomain.GENERAL:
            # general 兜底可无工具
            continue
        tool_names = {t.name for t in tpl.default_tools}
        assert tool_names, f"{tpl.domain} 模板应至少配置一个领域工具"


def test_resolve_project_root_finds_templates_dir():
    """generate_agent 的项目根解析能找到 templates/enterprise_agents/"""
    from agentclaw.agent_factory.generator import _resolve_project_root

    root = _resolve_project_root(_PROJECT_ROOT)
    assert (root / "templates" / "enterprise_agents").exists()
