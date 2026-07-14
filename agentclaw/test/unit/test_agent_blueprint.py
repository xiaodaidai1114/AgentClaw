"""
AgentBlueprint 系统单元测试（Phase 1）

覆盖验收标准：
- AgentBlueprint 可创建并序列化为 YAML/JSON
- 可从 YAML/JSON 加载还原
- 缺失必填字段（name/domain/role）报 ValidationError
- version 默认 "v0.1"
- 文件 save/load 按扩展名自动选择格式
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from agentclaw.agent_factory import (
    AgentBlueprint,
    SkillSpec,
    ToolSpec,
    KnowledgeSourceSpec,
    MemorySpec,
    WorkflowStep,
    DEFAULT_VERSION,
    to_dict,
    from_dict,
    to_json,
    from_json,
    to_yaml,
    from_yaml,
    save,
    load,
    yaml_available,
)


pytestmark = pytest.mark.unit

# YAML 测试在 pyyaml 不可用时跳过（环境通常有间接依赖）
requires_yaml = pytest.mark.skipif(not yaml_available(), reason="pyyaml 未安装")


def _sample_blueprint() -> AgentBlueprint:
    """构造一个覆盖大部分字段的示例 Blueprint"""
    return AgentBlueprint(
        name="sales_lead_analysis_agent",
        display_name="销售线索分析助手",
        description="分析销售线索并给出跟进建议",
        domain="sales",
        role="销售线索分析师",
        goals=["识别高价值线索", "给出跟进优先级"],
        responsibilities=["线索评分", "客户分析", "报告生成"],
        inputs=["客户线索列表"],
        outputs=["优先级排序", "跟进建议"],
        skills=[
            SkillSpec(
                name="lead_scoring",
                description="线索评分",
                type="builtin",
                required=True,
                source="builtin",
                confidence=0.8,
            ),
        ],
        tools=[
            ToolSpec(
                name="crm_query",
                description="查询 CRM",
                permission_level="read_only",
            ),
        ],
        knowledge_sources=[
            KnowledgeSourceSpec(name="product_kb", type="knowledge_base"),
        ],
        workflow=[
            WorkflowStep(
                step_id="s1",
                name="评分",
                input="线索",
                output="分数",
                tools=["crm_query"],
                skills=["lead_scoring"],
            ),
        ],
        guardrails=["不泄露客户隐私"],
        constraints=["仅处理脱敏后的线索数据"],
    )


# ------------------------------------------------------------------
# 创建与默认值
# ------------------------------------------------------------------

def test_blueprint_can_be_created_with_full_fields():
    bp = _sample_blueprint()
    assert bp.name == "sales_lead_analysis_agent"
    assert bp.domain == "sales"
    assert bp.role == "销售线索分析师"
    assert len(bp.skills) == 1
    assert bp.skills[0].name == "lead_scoring"
    assert len(bp.workflow) == 1


def test_blueprint_minimal_creation_only_requires_name_domain_role():
    bp = AgentBlueprint(name="minimal", domain="general", role="助手")
    assert bp.display_name == ""
    assert bp.goals == []
    assert bp.skills == []
    assert bp.tools == []
    assert bp.workflow == []
    assert isinstance(bp.memory, MemorySpec)
    assert bp.memory.persist is True


def test_blueprint_default_version_is_v01():
    bp = AgentBlueprint(name="x", domain="general", role="助手")
    assert bp.version == DEFAULT_VERSION == "v0.1"


def test_blueprint_default_status_is_draft():
    bp = AgentBlueprint(name="x", domain="general", role="助手")
    assert bp.status == "draft"


def test_blueprint_default_timestamps_set():
    bp = AgentBlueprint(name="x", domain="general", role="助手")
    assert isinstance(bp.created_at, datetime)
    assert isinstance(bp.updated_at, datetime)
    assert bp.created_at <= bp.updated_at or bp.created_at == bp.updated_at


def test_blueprint_touch_updates_updated_at():
    bp = AgentBlueprint(name="x", domain="general", role="助手")
    old = bp.updated_at
    bp.touch()
    assert bp.updated_at >= old


# ------------------------------------------------------------------
# 必填字段校验
# ------------------------------------------------------------------

def test_missing_name_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(domain="general", role="助手")


def test_missing_domain_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(name="x", role="助手")


def test_missing_role_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(name="x", domain="general")


def test_blank_string_name_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(name="   ", domain="general", role="助手")


def test_blank_string_domain_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(name="x", domain="  ", role="助手")


def test_blank_string_role_raises():
    with pytest.raises(ValidationError):
        AgentBlueprint(name="x", domain="general", role="")


def test_skill_spec_requires_name():
    with pytest.raises(ValidationError):
        SkillSpec(name="", confidence=0.5)


def test_tool_spec_requires_name():
    with pytest.raises(ValidationError):
        ToolSpec(name="  ")


def test_workflow_step_requires_step_id_and_name():
    with pytest.raises(ValidationError):
        WorkflowStep(step_id="", name="x")
    with pytest.raises(ValidationError):
        WorkflowStep(step_id="s1", name="")


def test_skill_spec_confidence_bounds():
    with pytest.raises(ValidationError):
        SkillSpec(name="x", confidence=1.5)
    with pytest.raises(ValidationError):
        SkillSpec(name="x", confidence=-0.1)
    assert SkillSpec(name="x", confidence=0.5).confidence == 0.5
    assert SkillSpec(name="x", confidence=0.0).confidence == 0.0
    assert SkillSpec(name="x", confidence=1.0).confidence == 1.0


# ------------------------------------------------------------------
# JSON 序列化
# ------------------------------------------------------------------

def test_serialize_to_json_contains_fields():
    bp = _sample_blueprint()
    text = to_json(bp)
    assert "sales_lead_analysis_agent" in text
    assert "domain" in text
    # 中文默认不转义
    assert "销售线索分析助手" in text
    # 合法 JSON
    data = json.loads(text)
    assert data["domain"] == "sales"
    assert data["role"] == "销售线索分析师"


def test_json_roundtrip_preserves_data():
    bp = _sample_blueprint()
    restored = from_json(to_json(bp))
    assert restored.name == bp.name
    assert restored.domain == bp.domain
    assert restored.role == bp.role
    assert restored.goals == bp.goals
    assert restored.skills == bp.skills
    assert restored.workflow == bp.workflow
    assert restored.tools == bp.tools
    assert restored.version == "v0.1"


def test_json_roundtrip_preserves_timestamps():
    bp = _sample_blueprint()
    restored = from_json(to_json(bp))
    assert restored.created_at == bp.created_at
    assert restored.updated_at == bp.updated_at


def test_dict_roundtrip():
    bp = _sample_blueprint()
    restored = from_dict(to_dict(bp))
    assert restored.name == bp.name
    assert restored.skills == bp.skills


# ------------------------------------------------------------------
# YAML 序列化
# ------------------------------------------------------------------

@requires_yaml
def test_serialize_to_yaml_contains_fields():
    bp = _sample_blueprint()
    text = to_yaml(bp)
    assert "sales_lead_analysis_agent" in text
    assert "销售线索分析助手" in text
    assert "domain: sales" in text


@requires_yaml
def test_yaml_roundtrip_preserves_data():
    bp = _sample_blueprint()
    restored = from_yaml(to_yaml(bp))
    assert restored.name == bp.name
    assert restored.domain == bp.domain
    assert restored.role == bp.role
    assert len(restored.skills) == 1
    assert restored.skills[0].name == "lead_scoring"
    assert restored.skills[0].confidence == 0.8
    assert restored.version == "v0.1"


@requires_yaml
def test_yaml_roundtrip_preserves_nested_lists():
    bp = _sample_blueprint()
    restored = from_yaml(to_yaml(bp))
    assert restored.goals == bp.goals
    assert restored.workflow[0].tools == ["crm_query"]
    assert restored.workflow[0].skills == ["lead_scoring"]
    assert restored.tools[0].permission_level == "read_only"
    assert restored.guardrails == bp.guardrails


@requires_yaml
def test_yaml_roundtrip_minimal_blueprint():
    bp = AgentBlueprint(name="minimal", domain="general", role="助手")
    restored = from_yaml(to_yaml(bp))
    assert restored.name == "minimal"
    assert restored.version == "v0.1"
    assert restored.skills == []


@requires_yaml
def test_from_yaml_empty_raises():
    with pytest.raises(ValueError):
        from_yaml("")


# ------------------------------------------------------------------
# 文件 save / load
# ------------------------------------------------------------------

@requires_yaml
def test_save_and_load_yaml(tmp_path):
    bp = _sample_blueprint()
    path = tmp_path / "agent.yaml"
    save(bp, path)
    assert path.exists()
    restored = load(path)
    assert restored.name == bp.name
    assert restored.domain == bp.domain
    assert restored.skills == bp.skills


def test_save_and_load_json(tmp_path):
    bp = _sample_blueprint()
    path = tmp_path / "agent.json"
    save(bp, path)
    assert path.exists()
    restored = load(path)
    assert restored.name == bp.name
    assert restored.domain == bp.domain


@requires_yaml
def test_save_and_load_yml_extension(tmp_path):
    bp = _sample_blueprint()
    path = tmp_path / "agent.yml"
    save(bp, path)
    restored = load(path)
    assert restored.name == bp.name


@requires_yaml
def test_save_creates_parent_directories(tmp_path):
    bp = _sample_blueprint()
    path = tmp_path / "nested" / "dir" / "agent.yaml"
    save(bp, path)
    assert path.exists()


def test_save_unsupported_extension_raises(tmp_path):
    bp = _sample_blueprint()
    with pytest.raises(ValueError):
        save(bp, tmp_path / "agent.txt")


def test_load_unsupported_extension_raises(tmp_path):
    path = tmp_path / "agent.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)


# ------------------------------------------------------------------
# 独立性：不依赖运行时配置
# ------------------------------------------------------------------

def test_blueprint_creation_does_not_require_runtime_config(monkeypatch):
    # 清掉可能影响配置加载的环境变量，确认 Blueprint 创建纯独立
    for key in ("PG_HOST", "REDIS_HOST", "ADMIN_TOKEN", "AGENTCLAW_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)
    bp = AgentBlueprint(name="isolated", domain="general", role="助手")
    assert bp.name == "isolated"
