"""
Skill Publisher - 发布 approved 的 Skill Candidate 到 Skill Registry

发布目录结构（与 skill_creator 约定一致）：
    skills/enterprise/{domain}/{skill_name}/
        SKILL.md         技能说明（触发条件/步骤/规则）
        rules.yaml       业务规则
        examples.json    示例
        metadata.yaml    元数据（来源 pattern / 置信度 / 状态）

只有 approved 状态的 candidate 可发布；发布后状态置为 published。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .skill_candidate import SkillCandidate, STATUS_APPROVED, STATUS_PUBLISHED


class SkillPublisher:
    """发布 Skill Candidate 到 Skill Registry"""

    def __init__(self, registry_dir) -> None:
        self.registry_dir = Path(registry_dir)

    def publish(self, candidate: SkillCandidate) -> Path:
        """
        发布 approved 的 candidate。

        Raises:
            ValueError: candidate 未 approved
        """
        if candidate.status != STATUS_APPROVED:
            raise ValueError(
                f"只有 approved 的 candidate 可发布，当前状态: {candidate.status}"
            )

        skill_dir = self.registry_dir / candidate.domain / candidate.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        (skill_dir / "SKILL.md").write_text(self._render_skill_md(candidate), encoding="utf-8")
        (skill_dir / "rules.yaml").write_text(self._render_rules(candidate), encoding="utf-8")
        (skill_dir / "examples.json").write_text(
            json.dumps(candidate.examples, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (skill_dir / "metadata.yaml").write_text(
            self._render_metadata(candidate), encoding="utf-8"
        )

        candidate.status = STATUS_PUBLISHED
        return skill_dir

    def is_publishable(self, candidate: SkillCandidate) -> bool:
        return candidate.status == STATUS_APPROVED

    def list_published(self) -> List[Path]:
        """列出 registry 中已发布的 skill 目录"""
        if not self.registry_dir.exists():
            return []
        result: List[Path] = []
        for domain_dir in self.registry_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            for skill_dir in domain_dir.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    result.append(skill_dir)
        return sorted(result)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render_skill_md(self, c: SkillCandidate) -> str:
        lines: List[str] = [f"# {c.name}", "", c.description, ""]
        if c.trigger_conditions:
            lines.append("## 触发条件")
            lines.extend(f"- {x}" for x in c.trigger_conditions)
            lines.append("")
        if c.steps:
            lines.append("## 执行步骤")
            lines.extend(f"{i + 1}. {s}" for i, s in enumerate(c.steps))
            lines.append("")
        if c.rules:
            lines.append("## 业务规则")
            lines.extend(f"- {r}" for r in c.rules)
            lines.append("")
        if c.required_tools:
            lines.append("## 所需工具")
            lines.extend(f"- {t}" for t in c.required_tools)
            lines.append("")
        lines.append(
            f"> 由 Skill Evolution 从 {len(c.source_patterns)} 个 pattern 沉淀，"
            f"置信度 {c.confidence:.2f}"
        )
        return "\n".join(lines)

    def _render_rules(self, c: SkillCandidate) -> str:
        lines = [
            f"domain: {c.domain}",
            f"name: {c.name}",
            f"confidence: {c.confidence}",
            "rules:",
        ]
        if c.rules:
            for r in c.rules:
                # YAML 简单字符串，避免引号问题
                safe = r.replace(":", "：").replace("\n", " ")
                lines.append(f"  - {safe}")
        else:
            lines.append("  []")
        return "\n".join(lines)

    def _render_metadata(self, c: SkillCandidate) -> str:
        lines = [
            f"candidate_id: {c.candidate_id}",
            f"domain: {c.domain}",
            f"name: {c.name}",
            f"confidence: {c.confidence}",
            "status: published",
            "source_patterns:",
        ]
        if c.source_patterns:
            for p in c.source_patterns:
                lines.append(f"  - {p}")
        else:
            lines.append("  []")
        return "\n".join(lines)
