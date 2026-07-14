"""
Skill Extractor - Pattern → SkillCandidate

根据 Pattern 类型生成结构化的 SkillCandidate（触发条件/步骤/规则/示例）。
候选 Skill 不自动发布，需经评估与人工审批。
"""

from __future__ import annotations

import re
from typing import List

from .pattern_miner import (
    PATTERN_BUSINESS_RULE,
    PATTERN_FAILURE,
    PATTERN_TOOL_COMBINATION,
    Pattern,
)
from .skill_candidate import SkillCandidate, stable_id


def _slugify(text: str, fallback_prefix: str = "skill", max_len: int = 40) -> str:
    """从描述派生英文 slug；中文描述回退为稳定 hash id"""
    s = re.sub(r"[^\w一-鿿]", " ", text or "").strip()
    s = re.sub(r"\s+", "_", s).lower()
    s = re.sub(r"[^a-z0-9_]", "", s)  # 去中文，保留英文/数字/下划线
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) < 3:
        s = stable_id(fallback_prefix, text)[:max_len]
    return s[:max_len]


class SkillExtractor:
    """根据 Pattern 生成 SkillCandidate"""

    def extract(self, pattern: Pattern) -> SkillCandidate:
        if pattern.pattern_type == PATTERN_BUSINESS_RULE:
            return self._extract_business_rule(pattern)
        if pattern.pattern_type == PATTERN_TOOL_COMBINATION:
            return self._extract_tool_combo(pattern)
        if pattern.pattern_type == PATTERN_FAILURE:
            return self._extract_failure(pattern)
        return self._extract_generic(pattern)

    def extract_many(self, patterns: List[Pattern]) -> List[SkillCandidate]:
        return [self.extract(p) for p in patterns]

    def _extract_business_rule(self, pattern: Pattern) -> SkillCandidate:
        name = _slugify(pattern.description, fallback_prefix="rule")
        return SkillCandidate(
            candidate_id=stable_id("cand", pattern.domain, name),
            name=name,
            description=pattern.description,
            domain=pattern.domain,
            trigger_conditions=["当任务涉及该业务场景时触发"],
            steps=[
                "检查输入是否满足规则条件",
                "应用规则给出修正建议",
                "记录规则应用结果",
            ],
            rules=list(pattern.sample_corrections),
            examples=[
                {"correction": c, "source": "human_feedback"}
                for c in pattern.sample_corrections
            ],
            source_patterns=[pattern.pattern_id],
            confidence=pattern.confidence,
        )

    def _extract_tool_combo(self, pattern: Pattern) -> SkillCandidate:
        name = _slugify(pattern.description, fallback_prefix="toolcombo")
        # 从 description 解析工具列表："高频工具组合: a + b + c"
        tools_part = pattern.description.replace("高频工具组合:", "").strip()
        tools = [t.strip() for t in tools_part.split("+") if t.strip()]
        return SkillCandidate(
            candidate_id=stable_id("cand", pattern.domain, name),
            name=name,
            description=pattern.description,
            domain=pattern.domain,
            trigger_conditions=["当任务需要该工具组合时触发"],
            steps=["按组合依次调用工具", "汇总工具结果"],
            required_tools=tools,
            source_patterns=[pattern.pattern_id],
            confidence=pattern.confidence,
        )

    def _extract_failure(self, pattern: Pattern) -> SkillCandidate:
        name = _slugify(pattern.description, fallback_prefix="failure")
        return SkillCandidate(
            candidate_id=stable_id("cand", pattern.domain, name),
            name=name,
            description=pattern.description,
            domain=pattern.domain,
            trigger_conditions=["当任务执行到易失败步骤时触发"],
            steps=["识别失败风险", "提供规避建议", "建议转人工或重试"],
            source_patterns=[pattern.pattern_id],
            confidence=pattern.confidence,
        )

    def _extract_generic(self, pattern: Pattern) -> SkillCandidate:
        name = _slugify(pattern.description, fallback_prefix="skill")
        return SkillCandidate(
            candidate_id=stable_id("cand", pattern.domain, name),
            name=name,
            description=pattern.description,
            domain=pattern.domain,
            source_patterns=[pattern.pattern_id],
            confidence=pattern.confidence,
        )
