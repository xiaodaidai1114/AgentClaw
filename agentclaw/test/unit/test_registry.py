"""
Registry + 版本管理单元测试（Phase 6）

覆盖：
- AgentRegistry：注册（自动 initial 版本）/ 查询 / 状态过滤 / 状态更新 / 删除
- SkillRegistry：注册 / 按 domain/agent 查询 / enable/disable / link_agent
- VersionManager：创建版本（递增）/ 列表 / diff / 回滚 / 标记生产
- 端到端：注册 → 加 skill 版本 → diff → 回滚 → 标记生产
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentclaw.agent_factory.blueprint import AgentStatus
from agentclaw.registry import (
    AgentRecord,
    AgentRegistry,
    CHANGE_INITIAL,
    CHANGE_ROLLBACK,
    CHANGE_SKILL_ADDED,
    SkillRecord,
    SkillRegistry,
    VersionManager,
)


pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# AgentRegistry
# ------------------------------------------------------------------

def test_agent_register_adds_initial_version(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    reg.register(AgentRecord(agent_id="sales_agent", name="sales", domain="sales"))
    got = reg.get("sales_agent")
    assert got is not None
    assert got.status == AgentStatus.DRAFT
    assert got.current_version == "v0.1"
    assert len(got.versions) == 1
    assert got.versions[0].change_type == CHANGE_INITIAL


def test_agent_list_filters_by_domain_and_status(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    reg.register(AgentRecord(agent_id="a2", name="b", domain="hr"))
    reg.register(AgentRecord(agent_id="a3", name="c", domain="sales", status=AgentStatus.PRODUCTION))
    assert len(reg.list_all(domain="sales")) == 2
    assert len(reg.list_all(status=AgentStatus.PRODUCTION)) == 1
    assert len(reg.list_all()) == 3


def test_agent_update_status(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    updated = reg.update_status("a1", AgentStatus.PRODUCTION)
    assert updated.status == AgentStatus.PRODUCTION
    assert reg.get("a1").status == AgentStatus.PRODUCTION


def test_agent_update_invalid_status_raises(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    with pytest.raises(ValueError):
        reg.update_status("a1", "bogus_status")


def test_agent_remove(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    assert reg.remove("a1") is True
    assert reg.get("a1") is None
    assert reg.remove("a1") is False


# ------------------------------------------------------------------
# SkillRegistry
# ------------------------------------------------------------------

def test_skill_register_and_query(tmp_path):
    reg = SkillRegistry(tmp_path / "skills.jsonl")
    reg.register(SkillRecord(skill_id="lead_scoring", name="lead_scoring", domain="sales"))
    assert reg.exists("lead_scoring")
    assert reg.get("lead_scoring").domain == "sales"


def test_skill_list_by_domain_and_agent(tmp_path):
    reg = SkillRegistry(tmp_path / "skills.jsonl")
    reg.register(SkillRecord(skill_id="s1", name="s1", domain="sales", agent_ids=["a1"]))
    reg.register(SkillRecord(skill_id="s2", name="s2", domain="hr"))
    reg.register(SkillRecord(skill_id="s3", name="s3", domain="sales", agent_ids=["a1", "a2"]))
    assert len(reg.list_by_domain("sales")) == 2
    assert len(reg.list_by_agent("a1")) == 2
    assert len(reg.list_by_agent("a2")) == 1


def test_skill_enable_disable(tmp_path):
    reg = SkillRegistry(tmp_path / "skills.jsonl")
    reg.register(SkillRecord(skill_id="s1", name="s1", domain="sales"))
    disabled = reg.disable("s1")
    from agentclaw.evolution.skill_candidate import STATUS_DEPRECATED, STATUS_PUBLISHED
    assert disabled.status == STATUS_DEPRECATED
    enabled = reg.enable("s1")
    assert enabled.status == STATUS_PUBLISHED


def test_skill_link_unlink_agent(tmp_path):
    reg = SkillRegistry(tmp_path / "skills.jsonl")
    reg.register(SkillRecord(skill_id="s1", name="s1", domain="sales"))
    reg.link_agent("s1", "a1")
    reg.link_agent("s1", "a1")  # 幂等
    assert reg.get("s1").agent_ids == ["a1"]
    reg.unlink_agent("s1", "a1")
    assert reg.get("s1").agent_ids == []


def test_skill_missing_raises(tmp_path):
    reg = SkillRegistry(tmp_path / "skills.jsonl")
    with pytest.raises(ValueError):
        reg.enable("nonexistent")


# ------------------------------------------------------------------
# VersionManager
# ------------------------------------------------------------------

def test_create_version_bumps_and_appends(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    v = vm.create_version("a1", change_type=CHANGE_SKILL_ADDED,
                          added_skills=["high_value"], changed_by="evolution")
    assert v.version == "v0.2"
    got = reg.get("a1")
    assert got.current_version == "v0.2"
    assert len(got.versions) == 2  # initial + new
    assert got.versions[1].added_skills == ["high_value"]


def test_list_and_get_version(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    vm.create_version("a1", change_type=CHANGE_SKILL_ADDED, added_skills=["s1"])
    versions = vm.list_versions("a1")
    assert len(versions) == 2
    assert vm.get_version("a1", "v0.1") is not None
    assert vm.get_version("a1", "v9.9") is None


def test_diff_detects_added_skills(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    vm.create_version("a1", change_type=CHANGE_SKILL_ADDED, added_skills=["skill_a"])
    d = vm.diff("a1", "v0.1", "v0.2")
    assert "skill_a" in d["added"]
    assert d["removed"] == []


def test_rollback_creates_new_version(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    vm.create_version("a1", change_type=CHANGE_SKILL_ADDED, added_skills=["skill_a"])  # v0.2
    rb = vm.rollback("a1", "v0.1")  # → v0.3
    assert rb.version == "v0.3"
    assert rb.change_type == CHANGE_ROLLBACK
    got = reg.get("a1")
    assert got.current_version == "v0.3"
    assert len(got.versions) == 3  # initial + skill_added + rollback


def test_rollback_missing_version_raises(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    with pytest.raises(ValueError):
        vm.rollback("a1", "v9.9")


def test_mark_production_and_deprecated(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    vm = VersionManager(reg)
    reg.register(AgentRecord(agent_id="a1", name="a", domain="sales"))
    vm.mark_production("a1")
    assert reg.get("a1").status == AgentStatus.PRODUCTION
    vm.mark_deprecated("a1")
    assert reg.get("a1").status == AgentStatus.DEPRECATED


# ------------------------------------------------------------------
# 端到端：注册 → 加 skill 版本 → diff → 回滚 → 标记生产
# ------------------------------------------------------------------

def test_end_to_end_registry_versioning(tmp_path):
    reg = AgentRegistry(tmp_path / "agents.jsonl")
    sreg = SkillRegistry(tmp_path / "skills.jsonl")
    vm = VersionManager(reg)

    # 1. 注册 agent（v0.1 initial）
    reg.register(AgentRecord(
        agent_id="sales_agent", name="sales", domain="sales",
        file_path="agents/sales.py",
    ))
    assert reg.get("sales_agent").current_version == "v0.1"

    # 2. 发布新 skill（来自 Phase 5）并关联 agent + 版本递增
    sreg.register(SkillRecord(
        skill_id="high_value", name="high_value", domain="sales",
        source_candidate_id="cand_xxx",
    ))
    sreg.link_agent("high_value", "sales_agent")
    vm.create_version(
        "sales_agent", change_type=CHANGE_SKILL_ADDED,
        added_skills=["high_value"], changed_by="skill_evolution",
        changelog="Added skill: high_value (from repeated human feedback)",
    )
    assert reg.get("sales_agent").current_version == "v0.2"

    # 3. diff 看新增了什么
    d = vm.diff("sales_agent", "v0.1", "v0.2")
    assert "high_value" in d["added"]

    # 4. 查 skill 被 agent 引用
    assert len(sreg.list_by_agent("sales_agent")) == 1

    # 5. 回滚 + 标记生产
    vm.rollback("sales_agent", "v0.1")
    assert reg.get("sales_agent").current_version == "v0.3"
    vm.mark_production("sales_agent")
    assert reg.get("sales_agent").status == AgentStatus.PRODUCTION
