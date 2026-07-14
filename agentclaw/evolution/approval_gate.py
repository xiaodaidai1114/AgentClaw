"""
Approval Gate - 人工审批门

企业环境中，Skill Candidate 不自动发布到生产。必须经人工审批：
    candidate → pending_approval → approved（可发布） / rejected

这是 Skill Evolution 的安全闸门：AI 只负责挖掘与生成，人决定是否采纳。
"""

from __future__ import annotations

from typing import List

from .skill_candidate import (
    CandidateStore,
    SkillCandidate,
    STATUS_APPROVED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    _now_utc,
)


class ApprovalGate:
    """人工审批门"""

    def __init__(self, store: CandidateStore) -> None:
        self.store = store

    def submit_for_approval(self, candidate: SkillCandidate) -> SkillCandidate:
        """提交审批：状态置为 pending_approval"""
        candidate.status = STATUS_PENDING_APPROVAL
        return self.store.save(candidate)

    def approve(
        self,
        candidate_id: str,
        approver: str = "admin",
    ) -> SkillCandidate:
        """批准（仅 pending_approval 可批准）"""
        c = self.store.get(candidate_id)
        if c is None:
            raise ValueError(f"candidate 不存在: {candidate_id}")
        if c.status != STATUS_PENDING_APPROVAL:
            raise ValueError(f"只有 pending_approval 状态可批准，当前状态: {c.status}")
        c.status = STATUS_APPROVED
        c.approved_by = approver
        c.approved_at = _now_utc()
        return self.store.save(c)

    def reject(
        self,
        candidate_id: str,
        reason: str = "",
    ) -> SkillCandidate:
        """拒绝（任意非 published 状态可拒绝）"""
        c = self.store.get(candidate_id)
        if c is None:
            raise ValueError(f"candidate 不存在: {candidate_id}")
        c.status = STATUS_REJECTED
        c.rejection_reason = reason
        return self.store.save(c)

    def list_pending(self) -> List[SkillCandidate]:
        """列出待审批的 candidate"""
        return self.store.list_pending()
