"""
Skill Evaluator - 评估 SkillCandidate

基于 confidence + evidence_count 给出评分与建议（promote / review / reject）。
评估结果供审批门参考，不自动决定发布。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .skill_candidate import SkillCandidate


RECOMMEND_PROMOTE = "promote"
RECOMMEND_REVIEW = "review"
RECOMMEND_REJECT = "reject"


class EvaluationResult(BaseModel):
    """Skill Candidate 评估结果"""
    candidate_id: str
    score: float                # 0-1 综合评分
    evidence_count: int
    confidence: float
    recommendation: str         # promote / review / reject


class SkillEvaluator:
    """Skill Candidate 评估器"""

    def __init__(
        self,
        *,
        promote_threshold: float = 0.7,
        review_threshold: float = 0.4,
    ) -> None:
        self.promote_threshold = promote_threshold
        self.review_threshold = review_threshold

    def evaluate(
        self,
        candidate: SkillCandidate,
        evidence_count: Optional[int] = None,
    ) -> EvaluationResult:
        """
        评估候选 Skill。

        Args:
            candidate: 待评估的候选
            evidence_count: 支持证据数（来自 source Pattern）；None 时用 source_patterns 数量
        """
        evidence = evidence_count if evidence_count is not None else len(candidate.source_patterns)
        # 评分 = confidence * 0.6 + 证据饱和度 * 0.4
        score = candidate.confidence * 0.6 + min(evidence / 10.0, 1.0) * 0.4
        if score >= self.promote_threshold:
            recommendation = RECOMMEND_PROMOTE
        elif score >= self.review_threshold:
            recommendation = RECOMMEND_REVIEW
        else:
            recommendation = RECOMMEND_REJECT
        return EvaluationResult(
            candidate_id=candidate.candidate_id,
            score=round(score, 3),
            evidence_count=evidence,
            confidence=candidate.confidence,
            recommendation=recommendation,
        )
