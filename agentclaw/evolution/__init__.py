"""
Skill Evolution Engine - 从使用轨迹沉淀新 Skill

完整流程：
    Trajectory（Phase 4）
        → PatternMiner        挖掘重复模式（business_rule / tool_combination / failure）
        → SkillExtractor      Pattern → SkillCandidate
        → SkillEvaluator      评估（confidence + evidence）
        → ApprovalGate        人工审批（pending → approved / rejected）
        → SkillPublisher      发布 approved 到 Skill Registry

企业安全闸门：AI 只负责挖掘与生成，人决定是否采纳发布。
本 Phase 为纯新增模块，不依赖运行时；后续可从 trajectories.jsonl 自动挖掘。
"""

from .approval_gate import ApprovalGate
from .pattern_miner import (
    ALL_PATTERN_TYPES,
    PATTERN_BUSINESS_RULE,
    PATTERN_FAILURE,
    PATTERN_TOOL_COMBINATION,
    Pattern,
    PatternMiner,
)
from .skill_candidate import (
    ALL_STATUSES,
    CandidateStore,
    STATUS_APPROVED,
    STATUS_CANDIDATE,
    STATUS_DEPRECATED,
    STATUS_PENDING_APPROVAL,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
    SkillCandidate,
    stable_id,
)
from .skill_evaluator import (
    RECOMMEND_PROMOTE,
    RECOMMEND_REJECT,
    RECOMMEND_REVIEW,
    EvaluationResult,
    SkillEvaluator,
)
from .skill_extractor import SkillExtractor
from .skill_publisher import SkillPublisher

__all__ = [
    # Schema / 存储
    "SkillCandidate",
    "CandidateStore",
    "stable_id",
    "STATUS_CANDIDATE",
    "STATUS_PENDING_APPROVAL",
    "STATUS_APPROVED",
    "STATUS_PUBLISHED",
    "STATUS_DEPRECATED",
    "STATUS_REJECTED",
    "ALL_STATUSES",
    # 模式挖掘
    "Pattern",
    "PatternMiner",
    "PATTERN_BUSINESS_RULE",
    "PATTERN_TOOL_COMBINATION",
    "PATTERN_FAILURE",
    "ALL_PATTERN_TYPES",
    # 提取 / 评估
    "SkillExtractor",
    "SkillEvaluator",
    "EvaluationResult",
    "RECOMMEND_PROMOTE",
    "RECOMMEND_REVIEW",
    "RECOMMEND_REJECT",
    # 审批 / 发布
    "ApprovalGate",
    "SkillPublisher",
]
