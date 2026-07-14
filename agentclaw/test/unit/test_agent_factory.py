"""
Agent Factory 单元测试（Phase 2）

覆盖验收标准：
- 一句话生成 Blueprint + 完整 Agent 目录结构
- 不同领域匹配不同模板
- 生成的 agent 可热注册到 WorkflowRegistry（即可被 POST /api/workflow/run 调用）
- CLI create-agent 可用
- 配置开关默认关闭，不影响现有流程
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentclaw.agent_factory import (
    AgentBlueprint,
    RequirementAnalyzer,
    DomainClassifier,
    TemplateMatcher,
    TemplateStore,
    BlueprintGenerator,
    ScaffoldGenerator,
    generate_agent,
    register_workflow_file,
    AgentDomain,
)
from agentclaw.api.registry import WorkflowRegistry


pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# RequirementAnalyzer
# ------------------------------------------------------------------

def test_requirement_analyzer_sales_request():
    req = RequirementAnalyzer().analyze("创建一个销售线索分析助手")
    assert req.domain == AgentDomain.SALES
    assert req.intent == "create_agent"
    assert req.agent_name == "sales_lead_analysis_agent"
    assert req.business_goal  # 非空
    assert "销售团队" in req.expected_users
    assert "线索评分" in req.required_capabilities


def test_requirement_analyzer_customer_support():
    req = RequirementAnalyzer().analyze("做一个客服工单分类助手")
    assert req.domain == AgentDomain.CUSTOMER_SUPPORT
    assert req.agent_name == "support_ticket_agent"


def test_requirement_analyzer_general_fallback():
    req = RequirementAnalyzer().analyze("随便聊聊天气")
    assert req.domain == AgentDomain.GENERAL


def test_requirement_analyzer_empty_request():
    req = RequirementAnalyzer().analyze("")
    assert req.domain == AgentDomain.GENERAL
    assert req.intent == "unknown"


# ------------------------------------------------------------------
# DomainClassifier
# ------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("销售线索分析", AgentDomain.SALES),
    ("客服工单投诉处理", AgentDomain.CUSTOMER_SUPPORT),
    ("财务报销发票审核", AgentDomain.FINANCE),
    ("招聘简历筛选", AgentDomain.HR),
    ("采购供应商审批", AgentDomain.PROCUREMENT),
    ("法务合同合规审查", AgentDomain.LEGAL),
    ("知识库问答检索", AgentDomain.KNOWLEDGE_BASE),
    ("运营数据报表监控", AgentDomain.OPERATIONS),
    ("今天天气真好", AgentDomain.GENERAL),
])
def test_domain_classifier(text, expected):
    assert DomainClassifier().classify(text) == expected


def test_derive_agent_slug_removes_action_and_suffix_words():
    dc = DomainClassifier()
    # 「创建」「助手」不应进入 slug
    assert dc.derive_agent_slug("创建一个销售线索分析助手", "sales") == "sales_lead_analysis"
    # 「员工」→agent 后缀保留
    assert dc.derive_agent_slug("销售线索分析的 AI 员工", "sales") == "sales_lead_analysis_agent"


# ------------------------------------------------------------------
# TemplateMatcher
# ------------------------------------------------------------------

def test_template_matcher_sales():
    tpl = TemplateMatcher().match(AgentDomain.SALES)
    assert tpl.domain == AgentDomain.SALES
    assert tpl.display_name == "销售分析助手"
    assert any(s.name == "lead_scoring" for s in tpl.default_skills)


def test_template_matcher_fallback_to_general():
    # finance 无内置模板，回退 general
    tpl = TemplateMatcher().match(AgentDomain.FINANCE)
    assert tpl.domain == AgentDomain.GENERAL


def test_template_matcher_different_domains_match_different_templates():
    store = TemplateStore()
    sales_tpl = TemplateMatcher(store).match(AgentDomain.SALES)
    support_tpl = TemplateMatcher(store).match(AgentDomain.CUSTOMER_SUPPORT)
    general_tpl = TemplateMatcher(store).match(AgentDomain.GENERAL)
    assert sales_tpl.domain == AgentDomain.SALES
    assert support_tpl.domain == AgentDomain.CUSTOMER_SUPPORT
    assert general_tpl.domain == AgentDomain.GENERAL
    # 三者互不相同
    assert len({sales_tpl.domain, support_tpl.domain, general_tpl.domain}) == 3


def test_template_store_builtin_count():
    store = TemplateStore()
    assert store.has(AgentDomain.GENERAL)
    assert store.has(AgentDomain.SALES)
    assert store.has(AgentDomain.CUSTOMER_SUPPORT)


# ------------------------------------------------------------------
# BlueprintGenerator
# ------------------------------------------------------------------

def test_blueprint_generator_uses_template_and_requirement():
    req = RequirementAnalyzer().analyze("创建一个销售线索分析助手")
    domain = AgentDomain.SALES
    tpl = TemplateMatcher().match(domain)
    bp = BlueprintGenerator().generate(req, domain, tpl)

    assert bp.name == "sales_lead_analysis_agent"
    assert bp.domain == AgentDomain.SALES
    assert bp.role == "销售线索分析师"
    assert bp.version == "v0.1"
    assert bp.status == "draft"
    # 模板 skills 被继承
    assert any(s.name == "lead_scoring" for s in bp.skills)
    # 模板 tools 被继承
    assert any(t.name == "crm_query" for t in bp.tools)
    # template workflow 被继承
    assert len(bp.workflow) == 3
    # guardrails 继承
    assert any("隐私" in g for g in bp.guardrails)


def test_blueprint_generator_name_is_valid_identifier():
    req = RequirementAnalyzer().analyze("做一个 123 分析")
    bp = BlueprintGenerator().generate(
        req, AgentDomain.GENERAL, TemplateMatcher().match(AgentDomain.GENERAL)
    )
    assert bp.name.isidentifier()


# ------------------------------------------------------------------
# ScaffoldGenerator
# ------------------------------------------------------------------

def test_scaffold_generator_creates_full_structure(tmp_path):
    req = RequirementAnalyzer().analyze("创建一个销售线索分析助手")
    tpl = TemplateMatcher().match(AgentDomain.SALES)
    bp = BlueprintGenerator().generate(req, AgentDomain.SALES, tpl)

    result = ScaffoldGenerator().generate(bp, project_dir=tmp_path)

    # 资产目录
    assert result.scaffold_dir == tmp_path / "agents" / "sales_lead_analysis_agent"
    assert result.agent_yaml.exists()
    assert result.prompt_md.exists()
    assert result.workflow_json.exists()
    assert result.readme.exists()
    # 占位目录
    assert (result.scaffold_dir / "skills").exists()
    assert (result.scaffold_dir / "tools").exists()
    assert (result.scaffold_dir / "knowledge").exists()
    # 版本目录
    assert (result.scaffold_dir / "versions" / "v0.1" / "agent.yaml").exists()
    assert (result.scaffold_dir / "versions" / "v0.1" / "changelog.md").exists()
    # 可运行 .py
    assert result.workflow_file == tmp_path / "agents" / "sales_lead_analysis_agent.py"
    assert result.workflow_file.exists()


def test_scaffold_generator_workflow_py_is_valid_python(tmp_path):
    import py_compile

    bp = AgentBlueprint(name="test_agent", domain="general", role="助手")
    result = ScaffoldGenerator().generate(bp, project_dir=tmp_path)
    # 编译验证语法
    py_compile.compile(str(result.workflow_file), doraise=True)
    # 内容含关键 API
    content = result.workflow_file.read_text(encoding="utf-8")
    assert "from agentclaw import Workflow, LLMNode, Input" in content
    assert "id='test_agent'" in content
    assert "workflow.publish()" in content


def test_scaffold_generator_agent_yaml_roundtrip(tmp_path):
    from agentclaw.agent_factory import load

    bp = AgentBlueprint(name="roundtrip_agent", domain="general", role="助手",
                        goals=["g1"], guardrails=["g1"])
    result = ScaffoldGenerator().generate(bp, project_dir=tmp_path)
    restored = load(result.agent_yaml)
    assert restored.name == "roundtrip_agent"
    assert restored.goals == ["g1"]
    assert restored.guardrails == ["g1"]


def test_scaffold_generator_prompt_md_contains_role_and_guardrails(tmp_path):
    bp = AgentBlueprint(
        name="x", domain="general", role="测试员",
        goals=["目标A"], guardrails=["护栏X"],
    )
    result = ScaffoldGenerator().generate(bp, project_dir=tmp_path)
    content = result.prompt_md.read_text(encoding="utf-8")
    assert "测试员" in content
    assert "目标A" in content
    assert "护栏X" in content


# ------------------------------------------------------------------
# generate_agent 端到端
# ------------------------------------------------------------------

def test_generate_agent_end_to_end_sales(tmp_path):
    result = generate_agent("创建一个销售线索分析助手", project_dir=tmp_path)
    assert result.blueprint.name == "sales_lead_analysis_agent"
    assert result.domain == AgentDomain.SALES
    assert result.template.display_name == "销售分析助手"
    # 完整目录结构
    assert result.scaffold.agent_yaml.exists()
    assert result.scaffold.prompt_md.exists()
    assert result.scaffold.workflow_json.exists()
    assert result.scaffold.readme.exists()
    assert result.scaffold.workflow_file.exists()
    assert (result.scaffold.versions_dir / "agent.yaml").exists()
    assert (result.scaffold.versions_dir / "changelog.md").exists()
    # 默认不注册
    assert result.registered is False


def test_generate_agent_different_domains_different_templates(tmp_path):
    r1 = generate_agent("创建一个销售线索分析助手", project_dir=tmp_path / "sales")
    r2 = generate_agent("做一个客服工单分类助手", project_dir=tmp_path / "support")
    assert r1.template.domain == AgentDomain.SALES
    assert r2.template.domain == AgentDomain.CUSTOMER_SUPPORT


# ------------------------------------------------------------------
# register_workflow_file 热注册
# ------------------------------------------------------------------

def test_register_workflow_file_registers_to_registry(tmp_path):
    result = generate_agent("创建一个销售线索分析助手", project_dir=tmp_path)
    name = result.blueprint.name
    try:
        assert register_workflow_file(name, result.scaffold.workflow_file) is True
        assert WorkflowRegistry.get(name) is not None
    finally:
        if WorkflowRegistry.get(name) is not None:
            WorkflowRegistry.unregister(name)


def test_register_workflow_file_supports_re_registration(tmp_path):
    """重新生成同名 agent 应能覆盖注册"""
    result = generate_agent("创建一个销售线索分析助手", project_dir=tmp_path)
    name = result.blueprint.name
    try:
        assert register_workflow_file(name, result.scaffold.workflow_file) is True
        # 再次注册（模拟重新生成）
        assert register_workflow_file(name, result.scaffold.workflow_file) is True
        assert WorkflowRegistry.get(name) is not None
    finally:
        if WorkflowRegistry.get(name) is not None:
            WorkflowRegistry.unregister(name)


def test_register_workflow_file_missing_file_returns_false(tmp_path):
    assert register_workflow_file("nope", tmp_path / "missing.py") is False


def test_generate_agent_with_register_flag(tmp_path):
    result = generate_agent(
        "创建一个销售线索分析助手", project_dir=tmp_path, register=True
    )
    name = result.blueprint.name
    try:
        assert result.registered is True
        assert WorkflowRegistry.get(name) is not None
    finally:
        if WorkflowRegistry.get(name) is not None:
            WorkflowRegistry.unregister(name)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def test_cli_create_agent(tmp_path):
    from click.testing import CliRunner
    from agentclaw.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["create-agent", "创建一个销售线索分析助手", "-d", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "sales_lead_analysis_agent" in result.output
    assert (tmp_path / "agents" / "sales_lead_analysis_agent" / "agent.yaml").exists()


# ------------------------------------------------------------------
# 配置开关
# ------------------------------------------------------------------

def test_agent_factory_config_default_disabled(monkeypatch):
    monkeypatch.delenv("AGENTCLAW_ENABLE_AGENT_FACTORY", raising=False)
    from agentclaw.config import AgentFactoryConfig

    cfg = AgentFactoryConfig.from_env()
    assert cfg.enabled is False
    assert cfg.auto_register is False


def test_env_config_contains_agent_factory_section():
    from agentclaw.env_config import visible_env_var_names

    names = visible_env_var_names()
    assert "AGENTCLAW_ENABLE_AGENT_FACTORY" in names
    assert "AGENTCLAW_AGENT_FACTORY_AUTO_REGISTER" in names


# ------------------------------------------------------------------
# 独立性：默认不挂载 API 路由（开关默认 False，见 test_agent_factory_config_default_disabled）
# ------------------------------------------------------------------
