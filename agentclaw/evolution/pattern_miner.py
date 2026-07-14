"""
Pattern Miner - 从 Trajectory 挖掘重复模式

挖掘类型：
- business_rule      重复的人工修正（Skill Evolution 最有价值的信号）
- tool_combination   高频工具组合
- failure_pattern    高频失败步骤

聚类用字符 n-gram Jaccard 相似度（无需中文分词依赖），确定性可测试。
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Set, Tuple

from pydantic import BaseModel, Field

from agentclaw.experience.event_schema import Trajectory

from .skill_candidate import stable_id


PATTERN_BUSINESS_RULE = "business_rule"
PATTERN_TOOL_COMBINATION = "tool_combination"
PATTERN_FAILURE = "failure_pattern"

ALL_PATTERN_TYPES = frozenset({
    PATTERN_BUSINESS_RULE,
    PATTERN_TOOL_COMBINATION,
    PATTERN_FAILURE,
})


class Pattern(BaseModel):
    """挖掘出的重复模式"""
    pattern_id: str
    pattern_type: str
    domain: str
    description: str
    evidence_count: int
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_trajectory_ids: List[str] = Field(default_factory=list)
    sample_corrections: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# 相似度工具
# ------------------------------------------------------------------

def _ngrams(text: str, n: int = 2) -> Set[str]:
    text = (text or "").strip()
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _jaccard(a: str, b: str) -> float:
    """字符 n-gram Jaccard 相似度（0-1）"""
    na, nb = _ngrams(a), _ngrams(b)
    if not na or not nb:
        return 0.0
    return len(na & nb) / len(na | nb)


# ------------------------------------------------------------------
# PatternMiner
# ------------------------------------------------------------------

class PatternMiner:
    """从 Trajectory 列表挖掘重复模式"""

    def __init__(
        self,
        *,
        min_evidence: int = 3,
        min_similarity: float = 0.3,
    ) -> None:
        self.min_evidence = min_evidence
        self.min_similarity = min_similarity

    def mine(self, trajectories: List[Trajectory]) -> List[Pattern]:
        patterns: List[Pattern] = []
        patterns.extend(self._mine_business_rules(trajectories))
        patterns.extend(self._mine_tool_combinations(trajectories))
        patterns.extend(self._mine_failures(trajectories))
        return patterns

    # ------------------------------------------------------------------
    @staticmethod
    def _domain_of(traj: Trajectory) -> str:
        """用 agent_id 作为 domain 线索（如 sales_agent → sales_agent）"""
        return traj.agent_id or "general"

    def _mine_business_rules(self, trajs: List[Trajectory]) -> List[Pattern]:
        # 收集 (traj_id, domain, correction)
        by_domain: Dict[str, List[Tuple[str, str]]] = {}
        for t in trajs:
            if t.human_correction:
                by_domain.setdefault(self._domain_of(t), []).append(
                    (t.trajectory_id, t.human_correction)
                )

        patterns: List[Pattern] = []
        for dom, items in by_domain.items():
            for cluster in self._cluster(items):
                if len(cluster) < self.min_evidence:
                    continue
                samples = [c[1] for c in cluster[:5]]
                traj_ids = [c[0] for c in cluster]
                desc = max(samples, key=len)
                patterns.append(Pattern(
                    pattern_id=stable_id("br", dom, desc),
                    pattern_type=PATTERN_BUSINESS_RULE,
                    domain=dom,
                    description=f"重复人工修正：{desc}",
                    evidence_count=len(cluster),
                    confidence=min(0.9, 0.3 + len(cluster) * 0.1),
                    evidence_trajectory_ids=traj_ids,
                    sample_corrections=samples,
                ))
        return patterns

    def _mine_tool_combinations(self, trajs: List[Trajectory]) -> List[Pattern]:
        counter: Counter = Counter()
        traj_map: Dict[Tuple[str, ...], List[str]] = {}
        for t in trajs:
            tools = tuple(sorted({tc.tool_name for tc in t.tool_calls}))
            if len(tools) >= 2:
                counter[tools] += 1
                traj_map.setdefault(tools, []).append(t.trajectory_id)

        patterns: List[Pattern] = []
        for tools, count in counter.items():
            if count >= self.min_evidence:
                patterns.append(Pattern(
                    pattern_id=stable_id("tc", "+".join(tools)),
                    pattern_type=PATTERN_TOOL_COMBINATION,
                    domain="general",
                    description=f"高频工具组合: {' + '.join(tools)}",
                    evidence_count=count,
                    confidence=min(0.9, 0.3 + count * 0.1),
                    evidence_trajectory_ids=traj_map[tools][:20],
                ))
        return patterns

    def _mine_failures(self, trajs: List[Trajectory]) -> List[Pattern]:
        counter: Counter = Counter()
        traj_map: Dict[str, List[str]] = {}
        for t in trajs:
            if not t.success:
                for step in t.steps:
                    if step.get("type") == "failed":
                        key = step.get("failed_step") or step.get("error_type") or "unknown"
                        counter[key] += 1
                        traj_map.setdefault(key, []).append(t.trajectory_id)

        patterns: List[Pattern] = []
        for key, count in counter.items():
            if count >= self.min_evidence:
                patterns.append(Pattern(
                    pattern_id=stable_id("fail", key),
                    pattern_type=PATTERN_FAILURE,
                    domain="general",
                    description=f"高频失败步骤: {key}（{count} 次）",
                    evidence_count=count,
                    confidence=min(0.9, 0.3 + count * 0.1),
                    evidence_trajectory_ids=traj_map[key][:20],
                ))
        return patterns

    def _cluster(self, items: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
        """贪心聚类：与簇代表（首个）相似度 >= min_similarity 归入同簇"""
        clusters: List[List[Tuple[str, str]]] = []
        for tid, corr in items:
            best_cluster: List[Tuple[str, str]] = []
            best_sim = 0.0
            for cluster in clusters:
                sim = _jaccard(corr, cluster[0][1])
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = cluster
            if best_cluster and best_sim >= self.min_similarity:
                best_cluster.append((tid, corr))
            else:
                clusters.append([(tid, corr)])
        return clusters
