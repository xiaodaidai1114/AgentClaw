"""
Skill Evolution Engine 单元测试（Phase 5）

覆盖：
- PatternMiner（business_rule / tool_combination / failure 三类挖掘）
- SkillExtractor（Pattern → SkillCandidate）
- SkillEvaluator（评分 + recommendation）
- ApprovalGate（submit/approve/reject；未审批不能发布）
- SkillPublisher（只有 approved 可发布；生成 skill 文件）
- 端到端：重复人工修正 → pending candidate → approved → published skill
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentclaw.experience import ToolCalledEvent, Trajectory
from agentclaw.evolution import (
    ALL_PATTERN_TYPES,
    ApprovalGate,
    CandidateStore,
    PatternMiner,
    PATTERN_BUSINESS_RULE,
    PATTERN_FAILURE,
    PATTERN_TOOL_COMBINATION,
    RECOMMEND_PROMOTE,
    SkillCandidate,
    SkillEvaluator,
    SkillExtractor,
    SkillPublisher,
    STATUS_APPROVED,
    STATUS_CANDIDATE,
    STATUS_PENDING_APPROVAL,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
)


pytestmark = pytest.mark.unit


def _traj(
    tid: str,
    agent: str,
    *,
    correction: str = "",
    tools=None,
    success: bool = True,
    failed_step=None,
) -> Trajectory:
    """构造测试用 Trajectory"""
    t = Trajectory(trajectory_id=tid, agent_id=agent, task="x")
    t.tool_calls = [
        ToolCalledEvent(agent_id=agent, task_id=tid, tool_name=n) for n in (tools or [])
    ]
    t.human_correction = correction
    t.human_feedback = correction
    t.success = success
    if not success and failed_step:
        t.steps = [{"type": "failed", "failed_step": failed_step}]
    return t


# ------------------------------------------------------------------
# PatternMiner
# ------------------------------------------------------------------

def test_mine_business_rule_from_repeated_corrections():
    """验收核心：重复人工修正 → business_rule pattern"""
    miner = PatternMiner(min_evidence=3, min_similarity=0.3)
    trajs = [
        _traj("t1", "sales_agent", correction="预算大于50万应标记高价值"),
        _traj("t2", "sales_agent", correction="预算大于50万标记为高价值客户"),
        _traj("t3", "sales_agent", correction="预算大于50万需标记高价值"),
        _traj("t4", "sales_agent", correction="完全无关的反馈"),  # 噪声
    ]
    patterns = miner.mine(trajs)
    br = [p for p in patterns if p.pattern_type == PATTERN_BUSINESS_RULE]
    assert len(br) == 1
    assert br[0].evidence_count == 3
    assert br[0].confidence > 0
    assert len(br[0].sample_corrections) == 3


def test_mine_tool_combination():
    miner = PatternMiner(min_evidence=2)
    trajs = [
        _traj("t1", "a", tools=["crm_query", "enrich"]),
        _traj("t2", "a", tools=["crm_query", "enrich"]),
        _traj("t3", "a", tools=["crm_query"]),  # 单工具不计入组合
    ]
    patterns = miner.mine(trajs)
    tc = [p for p in patterns if p.pattern_type == PATTERN_TOOL_COMBINATION]
    assert len(tc) == 1
    assert tc[0].evidence_count == 2


def test_mine_failure_pattern():
    miner = PatternMiner(min_evidence=2)
    trajs = [
        _traj("t1", "a", success=False, failed_step="query"),
        _traj("t2", "a", success=False, failed_step="query"),
        _traj("t3", "a", success=True),
    ]
    patterns = miner.mine(trajs)
    fail = [p for p in patterns if p.pattern_type == PATTERN_FAILURE]
    assert len(fail) == 1
    assert fail[0].evidence_count == 2


def test_mine_nothing_below_min_evidence():
    miner = PatternMiner(min_evidence=5)
    trajs = [_traj(f"t{i}", "a", correction="相同反馈") for i in range(3)]
    assert miner.mine(trajs) == []


def test_pattern_types_complete():
    assert ALL_PATTERN_TYPES == frozenset({
        PATTERN_BUSINESS_RULE, PATTERN_TOOL_COMBINATION, PATTERN_FAILURE,
    })


# ------------------------------------------------------------------
# SkillExtractor
# ------------------------------------------------------------------

def test_extractor_business_rule_to_candidate():
    miner = PatternMiner(min_evidence=2, min_similarity=0.3)
    trajs = [_traj(f"t{i}", "sales_agent", correction="预算大于50万应标记高价值") for i in range(3)]
    patterns = miner.mine(trajs)
    cand = SkillExtractor().extract(patterns[0])
    assert cand.domain == "sales_agent"
    assert cand.status == STATUS_CANDIDATE
    assert cand.confidence > 0
    assert len(cand.rules) >= 1  # 来自 sample_corrections
    assert cand.source_patterns


def test_extractor_extract_many():
    miner = PatternMiner(min_evidence=2)
    trajs = [
        _traj(f"t{i}", "a", correction="规则一应满足", tools=["x", "y"]) for i in range(3)
    ]
    patterns = miner.mine(trajs)
    candidates = SkillExtractor().extract_many(patterns)
    assert len(candidates) == len(patterns)
    assert all(c.status == STATUS_CANDIDATE for c in candidates)


# ------------------------------------------------------------------
# SkillEvaluator
# ------------------------------------------------------------------

def test_evaluator_promotes_high_confidence():
    cand = SkillCandidate(
        candidate_id="c1", name="x", description="d", domain="a",
        confidence=0.9, source_patterns=["p1", "p2", "p3"],
    )
    result = SkillEvaluator().evaluate(cand, evidence_count=8)
    assert result.recommendation == RECOMMEND_PROMOTE
    assert result.score >= 0.7


def test_evaluator_does_not_promote_low():
    cand = SkillCandidate(
        candidate_id="c1", name="x", description="d", domain="a",
        confidence=0.2, source_patterns=["p1"],
    )
    result = SkillEvaluator().evaluate(cand, evidence_count=1)
    assert result.recommendation != RECOMMEND_PROMOTE


# ------------------------------------------------------------------
# ApprovalGate（关键：未审批不能发布）
# ------------------------------------------------------------------

def test_approval_flow(tmp_path):
    store = CandidateStore(tmp_path / "candidates.jsonl")
    gate = ApprovalGate(store)

    cand = SkillCandidate(
        candidate_id="c1", name="x", description="d", domain="a", confidence=0.8
    )
    store.save(cand)

    gate.submit_for_approval(cand)
    assert store.get("c1").status == STATUS_PENDING_APPROVAL
    assert len(gate.list_pending()) == 1

    approved = gate.approve("c1", approver="manager")
    assert approved.status == STATUS_APPROVED
    assert approved.approved_by == "manager"
    assert approved.approved_at is not None
    assert gate.list_pending() == []

    cand2 = SkillCandidate(candidate_id="c2", name="y", description="d", domain="a")
    store.save(cand2)
    gate.submit_for_approval(cand2)
    rejected = gate.reject("c2", reason="不适用")
    assert rejected.status == STATUS_REJECTED
    assert rejected.rejection_reason == "不适用"


def test_cannot_approve_non_pending(tmp_path):
    store = CandidateStore(tmp_path / "candidates.jsonl")
    gate = ApprovalGate(store)
    cand = SkillCandidate(candidate_id="c1", name="x", description="d", domain="a")
    store.save(cand)
    # 状态是 candidate（未提交审批），不能直接 approve
    with pytest.raises(ValueError):
        gate.approve("c1")


def test_approve_missing_candidate_raises(tmp_path):
    gate = ApprovalGate(CandidateStore(tmp_path / "c.jsonl"))
    with pytest.raises(ValueError):
        gate.approve("nonexistent")


# ------------------------------------------------------------------
# SkillPublisher（关键：只有 approved 可发布）
# ------------------------------------------------------------------

def test_publisher_rejects_non_approved(tmp_path):
    pub = SkillPublisher(tmp_path / "registry")
    cand = SkillCandidate(candidate_id="c1", name="x", description="d", domain="a")
    with pytest.raises(ValueError):
        pub.publish(cand)  # candidate 状态，拒绝


def test_publisher_publishes_approved(tmp_path):
    pub = SkillPublisher(tmp_path / "registry")
    cand = SkillCandidate(
        candidate_id="c1", name="high_value", description="高价值判定",
        domain="sales", confidence=0.8,
        status=STATUS_APPROVED,
        rules=["预算>50万标记高价值"],
        steps=["检查预算", "标记"],
        trigger_conditions=["销售线索分析"],
        source_patterns=["p1"],
    )
    skill_dir = pub.publish(cand)
    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "rules.yaml").exists()
    assert (skill_dir / "examples.json").exists()
    assert (skill_dir / "metadata.yaml").exists()
    assert cand.status == STATUS_PUBLISHED
    # 路径：registry/sales/high_value/
    assert skill_dir.parent.name == "sales"
    assert skill_dir.name == "high_value"


def test_publisher_list_published(tmp_path):
    pub = SkillPublisher(tmp_path / "registry")
    cand = SkillCandidate(
        candidate_id="c1", name="rule_a", description="d",
        domain="sales", status=STATUS_APPROVED,
    )
    pub.publish(cand)
    assert len(pub.list_published()) == 1


# ------------------------------------------------------------------
# CandidateStore
# ------------------------------------------------------------------

def test_candidate_store_upsert_and_filter(tmp_path):
    store = CandidateStore(tmp_path / "c.jsonl")
    c1 = SkillCandidate(candidate_id="c1", name="x", description="d", domain="a")
    store.save(c1)
    c1.status = STATUS_PENDING_APPROVAL
    store.save(c1)  # upsert
    assert len(store.list_all()) == 1
    assert len(store.list_all(status=STATUS_PENDING_APPROVAL)) == 1
    assert store.get("c1").status == STATUS_PENDING_APPROVAL


# ------------------------------------------------------------------
# 端到端：trajectory → mine → candidate → approve → publish
# ------------------------------------------------------------------

def test_end_to_end_evolution(tmp_path):
    """验收标准：多次重复人工修正 → pending candidate → approved → published skill"""
    # 1. 构造带重复反馈的 trajectory
    trajs = [
        _traj(f"t{i}", "sales_agent", correction="预算大于50万应标记高价值客户")
        for i in range(5)
    ]

    # 2. 挖掘 pattern
    miner = PatternMiner(min_evidence=3, min_similarity=0.3)
    patterns = miner.mine(trajs)
    assert any(p.pattern_type == PATTERN_BUSINESS_RULE for p in patterns)

    # 3. 提取 candidate 并提交审批
    store = CandidateStore(tmp_path / "candidates.jsonl")
    extractor = SkillExtractor()
    gate = ApprovalGate(store)
    br_patterns = [p for p in patterns if p.pattern_type == PATTERN_BUSINESS_RULE]
    for p in br_patterns:
        gate.submit_for_approval(extractor.extract(p))
    assert len(gate.list_pending()) >= 1  # 生成 pending candidate

    # 4. 人工审批
    pending = gate.list_pending()[0]
    gate.approve(pending.candidate_id, approver="reviewer")

    # 5. 发布
    pub = SkillPublisher(tmp_path / "registry")
    approved = store.get(pending.candidate_id)
    skill_dir = pub.publish(approved)
    assert skill_dir.exists()
    assert approved.status == STATUS_PUBLISHED
    # SKILL.md 含业务规则
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "业务规则" in skill_md or "预算" in skill_md or "执行步骤" in skill_md
